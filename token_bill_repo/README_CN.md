# Token Bill

一个 [Claude Code](https://claude.ai/code) skill，结合 [ccusage](https://www.npmjs.com/package/ccusage) 的用量数据和 [LiteLLM](https://github.com/BerriAI/litellm) 的实时单价，生成按项目归集的对账账单。

## 快速开始

```bash
# 安装
claude skills install token_bill.skill

# 或者克隆后链接
git clone https://github.com/你的用户名/token_bill.git
ln -s $(pwd)/token_bill ~/.claude/skills/token_bill
```

在 Claude Code 中直接说：

```
> 给我生成今天的账单
> 这个月各个项目花了多少钱
> 账单统计
```

或者命令行直接跑：

```bash
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py --days 30
python3 ~/.claude/skills/token_bill/scripts/generate_bill.py --stats
```

## 功能

对每一次 Claude Code 会话，它会：

1. **获取用量** — 从 ccusage 提取每个模型的 token 消耗
2. **查询单价** — 从 LiteLLM 实时获取模型单价（覆盖 2962+ 个模型）
3. **计算费用** — `tokens × 单价`，分别计算输入、输出、缓存
4. **对账** — 独立计算结果与 ccusage 报的费用对比，吻合打 ✓
5. **按项目归集** — 费用按工作目录分组，一目了然

## 输出示例

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

## 命令参考

| 命令 | 功能 |
|---|---|
| `python3 scripts/generate_bill.py` | 今日账单，按项目分组（交互式保存） |
| `python3 scripts/generate_bill.py --quiet` | 静默入账，不显示面板（适合 cron/后台） |
| `python3 scripts/generate_bill.py --record` | 展示完整账单 + 自动保存 |
| `python3 scripts/generate_bill.py --days 30` | 月度按项目归集 |
| `python3 scripts/generate_bill.py --view` | 查看账单历史，按项目分组 |
| `python3 scripts/generate_bill.py --view --project X` | 查看某个项目的账单 |
| `python3 scripts/generate_bill.py --stats` | 项目 + 模型 + 每日 三维统计 |
| `python3 scripts/generate_bill.py --stats --project X` | 某个项目的统计数据 |

## 账单文件

记录存储在 `data/bill.jsonl`——每行一条 JSON，追加写入、自动去重：

```json
{
  "timestamp": "2026-07-13T07:20:15Z",
  "date": "2026-07-13",
  "project": "~/claude",
  "model": "deepseek-v4-pro",
  "inputTokens": 184000,
  "outputTokens": 105000,
  "cacheReadTokens": 17000000,
  "totalTokens": 17289000,
  "cost": 0.2333,
  "calculatedCost": 0.2333,
  "unitInput": 0.435,
  "unitOutput": 0.87,
  "unitCacheRead": 0.003625
}
```

去重键为 `(sessionId, model, date)`，同一条对话跑两次不会产生重复记录。

## 按项目记账

token_bill 按 **Claude Code 的工作目录**追踪费用。在不同项目目录下打开 Claude Code，账单会自动分开：

```bash
cd ~/work/api-server && claude     # → 账单归到 ~/work/api-server
cd ~/work/frontend && claude       # → 账单归到 ~/work/frontend
```

无需额外配置。

## 依赖

- Python 3.9+
- Node.js（供 `npx ccusage` 使用）
- 无第三方 Python 包（仅标准库）

## 相关项目

- [ccusage](https://www.npmjs.com/package/ccusage) — Claude Code 用量追踪工具
- [LiteLLM](https://github.com/BerriAI/litellm) — 定价数据来源
