# Token Bill

A [Claude Code](https://claude.ai/code) skill that generates token usage bills — combining [ccusage](https://www.npmjs.com/package/ccusage) consumption data with real-time [LiteLLM](https://github.com/BerriAI/litellm) unit pricing to produce reconciled cost records, grouped by project.

## Quick Start

```bash
# Install
claude skills install token_bill.skill

# Or: clone and link
git clone https://github.com/YOUR_USERNAME/token_bill.git
ln -s $(pwd)/token_bill ~/.claude/skills/token_bill
```

Then in Claude Code:

```
> generate my bill for today
> show me this month's spending by project
> bill stats for the last 30 days
```

Or run directly:

```bash
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py --days 30
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py --stats
```

## What it does

For every Claude Code session, it:

1. **Fetches usage** — token counts per model from ccusage
2. **Looks up prices** — real-time unit pricing from LiteLLM (2962+ models)
3. **Calculates cost** — `tokens × unit_price` for input, output, and cache
4. **Reconciles** — verifies the calculated total against ccusage's reported cost
5. **Groups by project** — costs are organized by working directory

## Example Output

```
╔══════════════════════════════════════════════════════════════════╗
║              Token Bill — By Project                            ║
╠══════════════════════════════════════════════════════════════════╣
║  Projects: 2                                                    ║
║  Total cost: $1.84                                              ║
╚══════════════════════════════════════════════════════════════════╝

  ▸ ~/claude
    Cost: $0.23 (12.5%)  |  Tokens: 17.3M  |  Sessions: 3

    ┌─ deepseek-v4-pro  (in $0.435  out $0.87  cache $0.003625)
    │      184K in      105K out     17.0M cache  → $0.2333  ✓
    └────────────────────────────────────────────────────────

  ▸ ~/work/api-server
    Cost: $1.61 (87.5%)  |  Tokens: 8.2M  |  Sessions: 12

    ┌─ claude-sonnet-5  (in $2.00  out $10.00  cache $0.20)
    │      520K in      98K out      7.6M cache  → $1.6050  ✓
    └────────────────────────────────────────────────────────

  ═══ Total: $1.8383  |  Calculated: $1.8383  ═══
  ✓ All projects reconciled
```

## Features

- **By project** — costs grouped by working directory (default)
- **Multi-day** — `--days 30` for monthly views
- **Bill ledger** — persistent `bill.jsonl` with full audit trail
- **Statistics** — `--stats` shows project + model + daily breakdowns
- **Reconciliation** — every cost is independently verified against unit prices
- **Auto-refresh** — LiteLLM pricing cache auto-updates every 24 hours

## Dependencies

- Python 3.9+
- Node.js (for `npx ccusage`)
- No Python packages beyond stdlib

## How it works

```
npx ccusage  ──→  token counts + model names + project paths
LiteLLM JSON ──→  unit prices ($/token)
─────────────────────────────────────────────────────────
tokens × prices = reconciled cost → bill.jsonl
```

Pricing data is fetched from [LiteLLM's model_prices_and_context_window.json](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) and cached locally for 24 hours.

## Related

- [ccusage](https://www.npmjs.com/package/ccusage) — Claude Code usage tracker
- [llm-pricing](https://github.com) — standalone LLM pricing lookup skill
- [LiteLLM](https://github.com/BerriAI/litellm) — the pricing data source
