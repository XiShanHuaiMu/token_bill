#!/usr/bin/env python3
"""
Token Bill Generator — combine ccusage usage data with LiteLLM unit pricing
to produce reconciled cost records.

Usage:
    python generate_bill.py                  # Today's bill, grouped by project
    python generate_bill.py --days 7         # Multi-day, grouped by project
    python generate_bill.py --view           # View bill ledger
    python generate_bill.py --stats          # Stats: by project + model + daily
    python generate_bill.py --stats --days 30  # Monthly stats

Architecture:
    npx ccusage  ──→  token counts + model names
    LiteLLM JSON ──→  unit prices ($/token)
    ─────────────────────────────────────────
    tokens × prices = reconciled cost → bill record
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Paths ---
SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
PRICING_FILE = DATA_DIR / "model_prices.json"
PRICING_META = DATA_DIR / "pricing_meta.json"
BILL_FILE = DATA_DIR / "bill.jsonl"

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# --- Pricing Data ---

def fetch_pricing() -> Dict:
    """Download LiteLLM pricing JSON."""
    print("[pricing] Fetching LiteLLM data ...", file=sys.stderr)
    req = urllib.request.Request(LITELLM_URL,
                                 headers={"User-Agent": "token-bill/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    data.pop("sample_spec", None)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PRICING_FILE, "w") as f:
        json.dump(data, f, indent=2)
    with open(PRICING_META, "w") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "model_count": len(data)}, f)
    print(f"[pricing] Cached {len(data)} models", file=sys.stderr)
    return data


def load_pricing() -> Dict:
    """Load pricing cache, refresh if > 24h old or missing."""
    if PRICING_FILE.exists():
        age_h = (time.time() - PRICING_FILE.stat().st_mtime) / 3600
        if age_h < 24:
            with open(PRICING_FILE) as f:
                return json.load(f)
        print(f"[pricing] Cache {age_h:.0f}h old, refreshing ...", file=sys.stderr)
    return fetch_pricing()


def find_price(pricing: Dict, model_name: str) -> Optional[Tuple[str, Dict]]:
    """Match a ccusage model name to a LiteLLM pricing entry."""
    ml = model_name.lower()
    candidates = []
    for key, info in pricing.items():
        if info.get("mode") not in ("chat", "completion", None):
            continue
        kl = key.lower()
        if ml in kl or kl in ml:
            provider = info.get("litellm_provider", "")
            score = 0 if provider in ("anthropic", "openai", "deepseek", "google") else 1
            candidates.append((score, len(key), key, info))
    if not candidates:
        return None
    candidates.sort()
    return (candidates[0][2], candidates[0][3])


# --- Formatting ---

def fmt_price(per_token: Optional[float]) -> str:
    if per_token is None:
        return "N/A"
    c = per_token * 1_000_000
    if c >= 1:
        return f"${c:.2f}"
    elif c >= 0.01:
        s = f"{c:.4f}".rstrip("0").rstrip(".")
        if len(s.split(".")[-1]) < 2:
            s = f"{c:.2f}"
        return f"${s}"
    return f"${c:.6f}"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:,.0f}K"
    return str(n)


def fmt_money(n: float) -> str:
    return f"${n:.4f}"


# --- ccusage ---

def run_ccusage(cmd: str, extra: List[str] = None) -> Dict:
    args = ["npx", "ccusage", "claude", cmd, "--json"]
    if extra:
        args.extend(extra)
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"[error] ccusage: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


# --- Bill Record ---

def append_bill(entry: dict) -> bool:
    """Append a cost record to bill.jsonl, skipping duplicates.

    Dedup key: sessionId + model + date. Returns True if written, False if skipped.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        **entry,
    }
    dedup_key = (entry.get("sessionId"), entry.get("model"), entry.get("date"))
    if BILL_FILE.exists():
        with open(BILL_FILE) as f:
            for line in f:
                try:
                    e = json.loads(line.strip())
                    if (e.get("sessionId"), e.get("model"), e.get("date")) == dedup_key:
                        return False  # Already recorded
                except json.JSONDecodeError:
                    continue
    with open(BILL_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def load_bill(days: int = None) -> List[Dict]:
    if not BILL_FILE.exists():
        return []
    entries = []
    cutoff = None
    if days:
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    with open(BILL_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if cutoff is None or e.get("date", "") >= cutoff:
                    entries.append(e)
            except json.JSONDecodeError:
                continue
    return entries


# --- Helpers ---

def norm_path(proj: str) -> str:
    """Normalize ccusage project path to readable form.

    ccusage encodes paths by replacing / with -. A leading / becomes a leading -.
    -Users-urthy-claude → /Users/urthy/claude → ~/claude
    """
    # Restore slashes
    p = proj.replace("-", "/")
    # Collapse home directory to ~
    home = os.path.expanduser("~")
    if p.startswith(home):
        p = "~" + p[len(home):]
    return p


# --- Main Command ---

def cmd_bill(pricing: Dict, cmd: str = "session", extra: List[str] = None,
             auto_record: bool = None, by: str = "project"):
    """Generate a bill: ccusage data + LiteLLM pricing = cost record.

    Always uses session mode for project-level granularity.
    Groups by project by default; use by='day' or by='month' for time-based grouping.
    """
    # Always use session mode to get projectPath
    data = run_ccusage("session", extra)
    sessions = data.get("sessions", [])
    totals = data.get("totals", {})

    # Determine period label
    period = "today"
    if extra:
        period = f"{extra[-1]} → today" if extra[0] == "--since" else "custom"

    # --- Group data ---
    # Aggregate: project → models → {tokens, cost}
    projects = {}
    all_records = []

    for sess in sessions:
        proj_raw = sess.get("projectPath", "(unknown)")
        proj = norm_path(proj_raw)
        date_str = sess.get("firstActivity", "")[:10]

        if proj not in projects:
            projects[proj] = {"cost": 0.0, "tokens": 0, "sessions": 0, "models": {}}

        projects[proj]["sessions"] += 1

        for mb in sess.get("modelBreakdowns", []):
            model = mb["modelName"]
            inp_t = mb.get("inputTokens", 0)
            out_t = mb.get("outputTokens", 0)
            cache_t = mb.get("cacheReadTokens", 0)
            cc_cost = mb.get("cost", 0)
            total_t = inp_t + out_t + cache_t

            if model not in projects[proj]["models"]:
                projects[proj]["models"][model] = {
                    "inputTokens": 0, "outputTokens": 0,
                    "cacheReadTokens": 0, "totalTokens": 0, "cost": 0.0,
                }
            m = projects[proj]["models"][model]
            m["inputTokens"] += inp_t
            m["outputTokens"] += out_t
            m["cacheReadTokens"] += cache_t
            m["totalTokens"] += total_t
            m["cost"] += cc_cost

            projects[proj]["cost"] += cc_cost
            projects[proj]["tokens"] += total_t

            # Build individual record for bill storage
            result = find_price(pricing, model)
            record = {
                "date": date_str,
                "projectPath": proj_raw,
                "project": proj,
                "sessionId": sess.get("sessionId", ""),
                "model": model,
                "inputTokens": inp_t,
                "outputTokens": out_t,
                "cacheReadTokens": cache_t,
                "totalTokens": total_t,
                "cost": cc_cost,
            }
            if result:
                _, info = result
                inp_price = info.get("input_cost_per_token")
                out_price = info.get("output_cost_per_token")
                cache_price = info.get("cache_read_input_token_cost")
                exp_in = inp_t * (inp_price or 0)
                exp_out = out_t * (out_price or 0)
                exp_cache = cache_t * (cache_price or 0)
                record["calculatedCost"] = round(exp_in + exp_out + exp_cache, 6)
                record["unitInput"] = round((inp_price or 0) * 1_000_000, 6)
                record["unitOutput"] = round((out_price or 0) * 1_000_000, 6)
                record["unitCacheRead"] = round((cache_price or 0) * 1_000_000, 6)
            all_records.append(record)

    # --- Render ---
    grand_cc = totals.get("totalCost", 0)
    grand_calc = sum(r.get("calculatedCost", r.get("cost", 0)) for r in all_records)

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║              Token Bill — By Project                            ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print(f"║  Period: {period:<55}║")
    print(f"║  Projects: {len(projects):<52}║")
    print(f"║  Total cost: {fmt_money(grand_cc):<48}║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # Sort projects by cost (most expensive first)
    sorted_projects = sorted(projects.items(), key=lambda x: -x[1]["cost"])

    for proj, pdata in sorted_projects:
        pct = pdata["cost"] / grand_cc * 100 if grand_cc > 0 else 0
        print(f"  ▸ {proj}")
        print(f"    Cost: {fmt_money(pdata['cost'])} ({pct:.1f}%)  |  "
              f"Tokens: {pdata['tokens']:,}  |  Sessions: {pdata['sessions']}")
        print()

        # Models within this project
        sorted_models = sorted(pdata["models"].items(), key=lambda x: -x[1]["cost"])
        for model, mdata in sorted_models:
            result = find_price(pricing, model)
            if result:
                _, info = result
                inp_p = fmt_price(info.get("input_cost_per_token"))
                out_p = fmt_price(info.get("output_cost_per_token"))
                cache_p = fmt_price(info.get("cache_read_input_token_cost"))
                exp_total = (
                    mdata["inputTokens"] * (info.get("input_cost_per_token") or 0)
                    + mdata["outputTokens"] * (info.get("output_cost_per_token") or 0)
                    + mdata["cacheReadTokens"] * (info.get("cache_read_input_token_cost") or 0)
                )
                delta = mdata["cost"] - exp_total
                flag = "✓" if abs(delta) < 0.005 else f"Δ {delta:+.4f}"
                cache_rate = (mdata["cacheReadTokens"]
                              / (mdata["inputTokens"] + mdata["cacheReadTokens"]) * 100
                              if (mdata["inputTokens"] + mdata["cacheReadTokens"]) > 0 else 0)

                print(f"    ┌─ {model}  (in {inp_p}  out {out_p}  cache {cache_p})")
                print(f"    │  {fmt_tokens(mdata['inputTokens']):>8} in  "
                      f"{fmt_tokens(mdata['outputTokens']):>8} out  "
                      f"{fmt_tokens(mdata['cacheReadTokens']):>8} cache  "
                      f"→ {fmt_money(mdata['cost'])}  {flag}")
                if cache_rate > 0:
                    print(f"    │  Cache rate: {cache_rate:.1f}%")
                print(f"    └{'─' * 56}")
            else:
                print(f"    ⚠ {model}: {fmt_tokens(mdata['totalTokens'])} → {fmt_money(mdata['cost'])} (no pricing)")
        print()

    # Grand total footer
    print(f"  ═══ Total: {fmt_money(grand_cc)}  |  Calculated: {fmt_money(grand_calc)}  ═══")
    if abs(grand_cc - grand_calc) < 0.01:
        print(f"  ✓ All projects reconciled")
    else:
        print(f"  ⚠ Discrepancy: {fmt_money(grand_cc - grand_calc)}")
    print()

    # --- Ask to record ---
    should_record = auto_record
    if should_record is None:
        try:
            ans = input("  Save to bill? (Y/n): ").strip().lower()
            should_record = ans in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            should_record = False

    if should_record and all_records:
        written = sum(1 for rec in all_records if append_bill(rec))
        skipped = len(all_records) - written
        msg = f"  ✓ {written} record(s) saved to bill.jsonl"
        if skipped:
            msg += f" ({skipped} skipped — already recorded)"
        print(msg + "\n")


def cmd_view(days: int = 7, project: str = None, model: str = None):
    """Display bill history, grouped by project."""
    entries = load_bill(days)

    # Apply filters
    if project:
        entries = [e for e in entries if project.lower() in
                   (e.get("project", "") + e.get("projectPath", "")).lower()]
    if model:
        entries = [e for e in entries if model.lower() in e.get("model", "").lower()]

    if not entries:
        print("No bill entries found.\n")
        return

    # Group by project
    projects = {}
    for e in entries:
        proj = e.get("project", norm_path(e.get("projectPath", "(unknown)")))
        if proj not in projects:
            projects[proj] = {"cost": 0.0, "tokens": 0, "entries": [], "models": {}}
        projects[proj]["cost"] += e.get("cost", 0)
        projects[proj]["tokens"] += e.get("totalTokens", 0)
        projects[proj]["entries"].append(e)
        m = e.get("model", "?")
        if m not in projects[proj]["models"]:
            projects[proj]["models"][m] = {"cost": 0.0, "tokens": 0}
        projects[proj]["models"][m]["cost"] += e.get("cost", 0)
        projects[proj]["models"][m]["tokens"] += e.get("totalTokens", 0)

    t_cost = sum(p["cost"] for p in projects.values())
    t_tok = sum(p["tokens"] for p in projects.values())

    print(f"\n  Bill Ledger — last {days} days ({len(entries)} entries)")
    if project:
        print(f"  Filter: project ~ '{project}'")
    if model:
        print(f"  Filter: model ~ '{model}'")

    for proj, pdata in sorted(projects.items(), key=lambda x: -x[1]["cost"]):
        pct = pdata["cost"] / t_cost * 100 if t_cost > 0 else 0
        print(f"\n  ▸ {proj}  {fmt_money(pdata['cost'])} ({pct:.1f}%)  {pdata['tokens']:,} tokens  {len(pdata['entries'])} records")
        print(f"    {'Date':<12} {'Model':<25} {'Tokens':>10} {'Cost':>8}")
        print(f"    {'-'*12} {'-'*25} {'-'*10} {'-'*8}")
        for e in pdata["entries"]:
            tok = e.get("totalTokens", 0)
            cost = e.get("cost", 0)
            calc = e.get("calculatedCost")
            flag = " ✓" if calc and abs(cost - calc) < 0.001 else ""
            print(f"    {e.get('date','?'):<12} {e.get('model','?')[:25]:<25} {tok:>10,}  ${cost:>7.4f}{flag}")

    print(f"\n  ═══ {len(projects)} projects  |  {len(entries)} entries  |  {fmt_money(t_cost)}  |  {t_tok:,} tokens ═══\n")


def cmd_stats(days: int = 30, project: str = None):
    """Bill statistics — by project and model."""
    entries = load_bill(days)
    if project:
        entries = [e for e in entries if project.lower() in
                   (e.get("project", "") + e.get("projectPath", "")).lower()]
    if not entries:
        print("No bill entries found.\n")
        return

    # Aggregate: project → models → tokens/cost
    projects = {}
    daily = {}
    model_totals = {}
    for e in entries:
        proj = e.get("project", norm_path(e.get("projectPath", "(unknown)")))
        model = e.get("model", "?")
        cost = e.get("cost", 0)
        tokens = e.get("totalTokens", 0)

        # Per project
        if proj not in projects:
            projects[proj] = {"cost": 0.0, "tokens": 0, "entries": 0, "models": {}}
        projects[proj]["cost"] += cost
        projects[proj]["tokens"] += tokens
        projects[proj]["entries"] += 1
        if model not in projects[proj]["models"]:
            projects[proj]["models"][model] = {"cost": 0.0, "tokens": 0}
        projects[proj]["models"][model]["cost"] += cost
        projects[proj]["models"][model]["tokens"] += tokens

        # Global model totals
        if model not in model_totals:
            model_totals[model] = {"cost": 0.0, "tokens": 0, "count": 0}
        model_totals[model]["cost"] += cost
        model_totals[model]["tokens"] += tokens
        model_totals[model]["count"] += 1

        # Daily
        d = e.get("date", "")
        daily[d] = daily.get(d, 0.0) + cost

    tc = sum(p["cost"] for p in projects.values())
    tt = sum(p["tokens"] for p in projects.values())

    print(f"\n  Bill Stats — last {days} days")
    print(f"  Entries: {len(entries)}   Cost: {fmt_money(tc)}   Tokens: {tt:,}")
    if daily:
        avg = tc / len(daily)
        print(f"  Days active: {len(daily)}   Avg/day: {fmt_money(avg)}")
        if len(daily) >= 28:
            print(f"  Est. monthly: {fmt_money(avg * 30)}")

    # By project
    print(f"\n  ── By Project ──")
    for proj, p in sorted(projects.items(), key=lambda x: -x[1]["cost"]):
        pct = p["cost"] / tc * 100 if tc > 0 else 0
        bar = "█" * max(1, int(pct))
        print(f"  {proj:<45} {fmt_money(p['cost']):>8} ({pct:5.1f}%)  {p['tokens']:>12,} tokens  {p['entries']:>3} entries")
        for m, mv in sorted(p["models"].items(), key=lambda x: -x[1]["cost"]):
            print(f"    └─ {m:<40} {fmt_money(mv['cost']):>8}  {mv['tokens']:>12,} tokens")

    # By model (global)
    print(f"\n  ── By Model ──")
    for m, v in sorted(model_totals.items(), key=lambda x: -x[1]["cost"]):
        pct = v["cost"] / tc * 100 if tc > 0 else 0
        print(f"  {m:<30} {fmt_money(v['cost']):>8}  ({pct:5.1f}%)  {v['tokens']:>12,} tokens  {v['count']:>3} sessions")

    # Daily sparkline
    print(f"\n  ── Daily ──")
    max_cost = max(daily.values()) if daily else 1
    for d in sorted(daily.keys())[-14:]:
        bar = "█" * max(1, int(daily[d] / max_cost * 35))
        print(f"    {d}  {fmt_money(daily[d])}  {bar}")
    print()


# --- CLI ---

def main():
    import argparse
    p = argparse.ArgumentParser(description="Token Bill Generator — by project")
    p.add_argument("--days", type=int, default=1, help="Days to cover (default: 1 = today)")
    p.add_argument("--record", "-r", action="store_true", default=None,
                   help="Auto-save to bill without prompt")
    p.add_argument("--no-record", action="store_true", help="Skip bill prompt")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Record only, no bill display")
    p.add_argument("--view", "-v", action="store_true", help="View bill ledger")
    p.add_argument("--stats", action="store_true", help="Statistics")
    p.add_argument("--project", "-p", default=None, help="Filter by project name")
    p.add_argument("--model", "-m", default=None, help="Filter by model name")

    args = p.parse_args()

    if args.view:
        cmd_view(args.days, project=args.project, model=args.model)
        return
    if args.stats:
        cmd_stats(args.days, project=args.project)
        return

    pricing = load_pricing()
    extra = []
    if args.days > 1:
        since = (date.today() - timedelta(days=args.days - 1)).isoformat()
        extra = ["--since", since]

    auto = None if args.no_record else args.record

    # --quiet mode: record only, no display
    if args.quiet:
        auto = True

    if args.quiet:
        # Record-only: skip full render, just collect and save
        data = run_ccusage("session", extra)
        sessions = data.get("sessions", [])
        all_records = []
        for sess in sessions:
            proj_raw = sess.get("projectPath", "")
            date_str = sess.get("firstActivity", "")[:10]
            for mb in sess.get("modelBreakdowns", []):
                model = mb["modelName"]
                result = find_price(pricing, model)
                rec = {
                    "date": date_str,
                    "projectPath": proj_raw,
                    "project": norm_path(proj_raw),
                    "sessionId": sess.get("sessionId", ""),
                    "model": model,
                    "inputTokens": mb.get("inputTokens", 0),
                    "outputTokens": mb.get("outputTokens", 0),
                    "cacheReadTokens": mb.get("cacheReadTokens", 0),
                    "totalTokens": (mb.get("inputTokens", 0) + mb.get("outputTokens", 0)
                                    + mb.get("cacheReadTokens", 0)),
                    "cost": mb.get("cost", 0),
                }
                if result:
                    _, info = result
                    inp_p = info.get("input_cost_per_token")
                    out_p = info.get("output_cost_per_token")
                    cache_p = info.get("cache_read_input_token_cost")
                    rec["calculatedCost"] = round(
                        mb.get("inputTokens", 0) * (inp_p or 0)
                        + mb.get("outputTokens", 0) * (out_p or 0)
                        + mb.get("cacheReadTokens", 0) * (cache_p or 0), 6)
                    rec["unitInput"] = round((inp_p or 0) * 1_000_000, 6)
                    rec["unitOutput"] = round((out_p or 0) * 1_000_000, 6)
                    rec["unitCacheRead"] = round((cache_p or 0) * 1_000_000, 6)
                all_records.append(rec)
        written = sum(1 for rec in all_records if append_bill(rec))
        skipped = len(all_records) - written
        total_cost = sum(r["cost"] for r in all_records)
        print(f"[bill] {written} new + {skipped} skipped, total {fmt_money(total_cost)}", file=sys.stderr)
        return

    cmd_bill(pricing, "session", extra, auto_record=auto)


if __name__ == "__main__":
    main()
