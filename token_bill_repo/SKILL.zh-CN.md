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

# Token Bill — 用量 × 单价 对账系统

结合 [ccusage](https://www.npmjs.com/package/ccusage) 的 token 用量数据与
[LiteLLM](https://github.com/BerriAI/litellm) 的模型单价，生成带对账的成本记录。

每条记录展示：模型名、token 消耗（输入/输出/缓存）、LiteLLM 实时单价、
独立计算的费用、以及 ccusage 自身报告的成本 —— 两者一致时显示 ✓。

## 快速开始

```bash
# 今日账单（按项目归集，末尾询问是否保存）
python3 scripts/generate_bill.py

# 多天汇总
python3 scripts/generate_bill.py --days 7

# 按会话拆分
python3 scripts/generate_bill.py --session

# 自动保存（不询问）
python3 scripts/generate_bill.py --record

# 查看账单 / 统计
python3 scripts/generate_bill.py --view
python3 scripts/generate_bill.py --stats
python3 scripts/generate_bill.py --stats --days 30
```

## 工作原理

1. **获取用量**：执行 `npx ccusage claude daily --json`（或 `session`），从
   Claude Code 会话记录中提取每个模型的 token 数量。
2. **查询单价**：从 LiteLLM 数据库（`model_prices_and_context_window.json`）
   加载模型单价，每 24 小时自动刷新。
3. **计算费用**：`tokens × 单价` 分别计算输入、输出、缓存命中三类 token 的费用。
4. **对账**：将独立计算的总费用与 ccusage 报告的成本比对。✓ 表示一致；
   Δ 表示存在差异。
5. **保存**：将结构化 JSON 记录追加写入 `data/bill.jsonl`。

## 输出格式

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

## 账单 Ledger

记录存储在 `data/bill.jsonl` —— 每行一条 JSON：

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

查看历史：`python3 scripts/generate_bill.py --view`
统计汇总：`python3 scripts/generate_bill.py --stats`

## 边界情况

- **无用量数据**：ccusage 返回空数组。如果用户今天还没用过 Claude Code
  或会话记录被清除，这属于正常情况。
- **找不到单价**：如果某个模型不在 LiteLLM 数据库中，账单仍会显示
  ccusage 的成本但无法对账。以 ⚠ 标记。
- **对账不一致**：如果计算值 ≠ ccusage 报告值，显示 Δ。通常意味着
  LiteLLM 定价数据过时 —— 等待 24 小时自动刷新即可。
- **首次运行**：从 GitHub 下载 LiteLLM 定价数据库（约 1.4MB）。
  后续使用本地缓存。
