---
name: token-bill
description: >
  Generate a token usage bill that combines ccusage consumption data with
  real-time LiteLLM unit pricing. For each model used, it shows token counts,
  unit prices, calculates the expected cost (tokens × price), and reconciles
  against ccusage's reported cost. Records can be saved to a persistent bill
  ledger. Use this skill whenever the user asks for a "bill", "账单", wants to
  see their spending with unit-price breakdowns, needs to reconcile usage costs,
  or asks to "generate a bill" / "record my usage". Also trigger on phrases like
  "今天花了多少", "token账单", "用量账单", "cost report", "spending report",
  or when the user wants to save usage records for expense tracking.
---

# Token Bill — Usage × Pricing Reconciliation

Combines [ccusage](https://www.npmjs.com/package/ccusage) token data with
[LiteLLM](https://github.com/BerriAI/litellm) unit pricing to produce
reconciled cost records.

Every record shows: model name, tokens consumed (in/out/cache), unit prices
from LiteLLM, calculated cost, and ccusage's own cost figure — with a
verification checkmark when they match.

## Quick Start

```bash
# Today's bill (interactive — asks to save afterward)
python3 scripts/generate_bill.py

# Multi-day
python3 scripts/generate_bill.py --days 7

# Per-session
python3 scripts/generate_bill.py --session

# Auto-save (no prompt)
python3 scripts/generate_bill.py --record

# View / stats
python3 scripts/generate_bill.py --view
python3 scripts/generate_bill.py --stats
python3 scripts/generate_bill.py --stats --days 30
```

## How it works

1. **Fetch usage**: runs `npx ccusage claude daily --json` (or `session`) to get
   token counts per model from Claude Code transcripts.
2. **Look up prices**: loads unit pricing from the LiteLLM database
   (`model_prices_and_context_window.json`), auto-refreshed every 24 hours.
3. **Calculate**: `tokens × unit_price` for input, output, and cache-read
   tokens independently.
4. **Reconcile**: compares the calculated total against ccusage's reported cost.
   A ✓ means they match; a Δ means a discrepancy.
5. **Save**: appends a structured JSON record to `data/bill.jsonl`.

## Output format

```
╔══════════════════════════════════════════════════════════╗
║              Token Bill — Usage × Pricing               ║
╠══════════════════════════════════════════════════════════╣
║  today                                                  ║
║  ccusage total: $0.2020                                 ║
╚══════════════════════════════════════════════════════════╝

  ┌─ deepseek-v4-pro
  │  Unit prices:  in   $0.435  out    $0.87  cache $0.003625
  │
  │  Input:       176K  ×   $0.435/1M  = $0.0765
  │  Output:       88K  ×    $0.87/1M  = $0.0764
  │  Cache:      13.5M  × $0.003625/1M = $0.0490
  │  ─────────────────────────────────────────────
  │  Calculated: $0.2020    ccusage: $0.2020    ✓
  │  Cache rate: 98.7%
  └──────────────────────────────────────────────────

  ═══ Calculated: $0.2020  |  ccusage: $0.2020  ═══
  ✓ All models reconciled

  Save to bill? (Y/n): y
  ✓ 1 record(s) saved to bill.jsonl
```

## Bill ledger

Records are stored at `data/bill.jsonl` — one JSON line per entry:

```json
{
  "timestamp": "2026-07-13T07:20:15Z",
  "date": "2026-07-13",
  "model": "deepseek-v4-pro",
  "inputTokens": 176000,
  "outputTokens": 88000,
  "cacheReadTokens": 13500000,
  "totalTokens": 13774000,
  "cost": 0.2020,
  "calculatedCost": 0.2020,
  "unitInput": 0.435,
  "unitOutput": 0.87,
  "unitCacheRead": 0.003625
}
```

View history: `python3 scripts/generate_bill.py --view`
Filter by project: `python3 scripts/generate_bill.py --view --project claude`
Statistics: `python3 scripts/generate_bill.py --stats`
Project stats: `python3 scripts/generate_bill.py --stats --project claude`

## Commands

| Command | What it does |
|---|---|
| `python3 scripts/generate_bill.py` | Today's bill, grouped by project (interactive save) |
| `python3 scripts/generate_bill.py --quiet` | Record only, no display (cron/background friendly) |
| `python3 scripts/generate_bill.py --record` | Full bill + auto-save (no prompt) |
| `python3 scripts/generate_bill.py --days 30` | Monthly bill |
| `python3 scripts/generate_bill.py --view` | View bill ledger, grouped by project |
| `python3 scripts/generate_bill.py --view --project X` | View bill for a specific project |
| `python3 scripts/generate_bill.py --stats` | Project + model + daily stats |
| `python3 scripts/generate_bill.py --stats --project X` | Stats for a specific project |

JSONL dedup: records are keyed by (sessionId, model, date). Running the same
command twice won't create duplicate entries — the second run is a no-op.

## Edge cases

- **No usage data**: ccusage returns empty arrays. Tell the user this is normal
  if they haven't used Claude Code today, or if transcripts were cleared.
- **Pricing not found**: if a model isn't in LiteLLM, the bill still shows
  ccusage's cost but can't verify it. Flag it with ⚠.
- **Mismatch**: if calculated ≠ ccusage, show Δ. This usually means the
  LiteLLM pricing data is stale — run with `--update` (coming soon) or wait
  for the 24h auto-refresh.
- **First run**: fetches the LiteLLM pricing database (~1.4MB) from GitHub.
  Subsequent runs use the local cache.
