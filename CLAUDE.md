# CLAUDE.md — QuantResearch 项目使用说明

## 项目是什么

QuantResearch 是一个本地量化研究工作台。它有三层：
- **qlib** — 本地数据存储和因子表达式引擎
- **vectorbt** — 技术策略回测引擎
- **QuantResearch** — CLI、报告、因子研究、实验记录

## 环境（必须先检查）

接手后的第一步：确认 Python 环境里装好了依赖。

```bash
# 检查核心依赖是否就绪
python -c "import akshare, qlib, vectorbt, pandas; print('ok')"
```

如果 `ModuleNotFoundError`，说明依赖没装。查一下 `requirements.txt`：

```bash
cat requirements.txt
```

然后**询问用户**：依赖缺失，是否需要按 `requirements.txt` 安装？用户可能已有 conda 环境或其他 Python 环境，让用户告诉你该用哪个。

**注意**：不要直接 `pip install`，等用户确认环境和安装方式。

### 运行命令

所有命令以 `python main.py <command>` 从项目根目录运行。如果有特定 conda 环境，用户会告诉你。

## 重要文件路径

| 文件/目录 | 用途 |
|-----------|------|
| `data/market_data.sqlite3` | SQLite 数据库（不被 git 跟踪） |
| `data/qlib_data/` | qlib .bin 数据集 |
| `data/exports/qlib_csv/` | qlib CSV 中间文件 |
| `vendor/qlib/scripts/dump_bin.py` | qlib bin 转换脚本（从微软 qlib 仓库提取，MIT 协议） |
| `reports/` | 所有研究产出目录 |

## 了解当前数据状态

不要假设数据已就绪。先诊断：

```bash
# 看有哪些标的
python main.py list-instruments

# 看标的数量和数据覆盖
python main.py list-instruments --market CN --asset-type STOCK | wc -l

# 检查 qlib 数据健康
python main.py qlib-health --start 2024-01-01 --end 2026-04-30

# 检查数据库
python -c "
import sqlite3
db = sqlite3.connect('data/market_data.sqlite3')
tables = db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
for t in tables:
    count = db.execute(f'SELECT COUNT(*) FROM {t[0]}').fetchone()[0]
    print(f'{t[0]}: {count}')
db.close()
"
```

## qlib 数据集刷新机制（重要）

`refresh_qlib()` 具有智能跳过逻辑，**不会每次重建**：

| 场景 | 行为 |
|------|------|
| 数据集已存在 + 日期已覆盖 | 跳过，直接返回 |
| 数据集已存在 + 日期不覆盖 | 增量更新（dump_update，只追加新日期） |
| 数据集不存在 | 全量构建（dump_all） |
| `force=True` | 强制全量重建 |

### 相关 CLI 参数

- `--force-refresh-qlib` — 强制全量重建（适用于 `strategy-backtest`、`factor-analyze`、`factor-backtest`、`signal-snapshot`）
- `--skip-auto-refresh-qlib` — 完全跳过 qlib 数据准备（仅用已有数据）
- `refresh-qlib --incremental` — 增量模式（数据集已覆盖则跳过，否则增量更新）

## 数据管线

### 从零构建

```bash
# 1. 初始化数据库（仅首次）
python main.py init-db

# 2. 注册标的（从 sample CSV 或手动）
python main.py seed-instruments --csv-path data/instruments.sample.csv

# 3. 拉取历史数据
python main.py ensure-history --symbol 000300 --market CN --asset-type INDEX

# 4. 构建 qlib 数据集
python main.py refresh-qlib
```

### 批量构建指数成分股数据（推荐）

```bash
python main.py seed-index-constituents --index 000300
python main.py batch-ensure-history --index 000300
python main.py refresh-qlib
```

### 日常更新

```bash
# 拉取最近 14 天数据（所有已注册标的）
python main.py update-daily

# 仅更新特定标的
python main.py update-daily --symbol 000300 --market CN --asset-type INDEX

# 拉取后增量刷新 qlib（自动只追加新日期）
python main.py refresh-qlib --incremental
```

## 研究分析

### 技术策略回测

可选策略: `kdj` / `bollinger` / `ma_cross` / `macd` / `rsi` / `dca`

```bash
# 单策略回测
python main.py strategy-backtest \
  --strategy kdj --symbol 000300 --market CN --asset-type INDEX \
  --start 2024-01-01 --end 2026-04-30

# 多策略对比
python main.py strategy-compare \
  --strategies kdj bollinger ma_cross macd rsi \
  --symbol 000300 --market CN --asset-type INDEX \
  --start 2024-01-01 --end 2026-04-30

# 最优策略搜索（按综合评分排名）
python main.py strategy-search \
  --symbol 000300 --market CN --asset-type INDEX \
  --start 2024-01-01 --end 2026-04-30

# 指定回测引擎 (pandas / vectorbt / auto)
python main.py strategy-backtest \
  --strategy kdj --symbol 000300 --market CN --asset-type INDEX \
  --start 2024-01-01 --end 2026-04-30 --engine vectorbt
```

### 策略参数速查

| 策略 | 关键参数 | 默认值 |
|------|----------|--------|
| KDJ | `--kdj-n` `--oversold` `--overbought` `--kdj-signal-mode` | 9 / 20 / 80 / extreme_cross |
| 布林线 | `--boll-window` `--boll-std-multiplier` `--boll-signal-mode` | 20 / 2.0 / reversion |
| 双均线 | `--ma-short-window` `--ma-long-window` | 10 / 30 |
| MACD | `--macd-fast-period` `--macd-slow-period` `--macd-signal-period` | 12 / 26 / 9 |
| RSI | `--rsi-period` `--rsi-oversold` `--rsi-overbought` | 14 / 30 / 70 |
| 定投 | `--dca-amount-per-buy` `--dca-frequency` `--dca-monthly-day` | 1000 / monthly / 1 |

### 因子研究

```bash
# 单因子分析（IC / RankIC / 分层收益 / 多空累计）
python main.py factor-analyze \
  --factor-name "20日波动" \
  --expression "Std(\$close,20)/\$close" \
  --start 2024-01-01 --end 2026-04-30

# 指定标的池和调仓频率
python main.py factor-analyze \
  --factor-name "动量" \
  --expression "\$close/Ref(\$close,20)-1" \
  --universe-source index --index-symbol 000300 \
  --rebalance weekly --quantiles 5 --forward-days 5

# 因子合成（等权 / ICIR 加权）
python main.py factor-combine \
  --factor-name "合成因子" \
  --labels "波动" "动量" "量比" \
  --expressions "Std(\$close,20)/\$close" "\$close/Ref(\$close,20)-1" "Mean(\$volume,5)/Mean(\$volume,20)" \
  --method equal

# 因子组合回测（按因子值选股，模拟真实持仓）
python main.py factor-backtest \
  --factor-name "低波动" \
  --expression "Std(\$close,20)/\$close" \
  --direction short --top-n 30 \
  --start 2024-01-01 --end 2026-04-30
```

### 决策与信号

```bash
# 信号快照（多策略信号汇总 + 投票）
python main.py signal-snapshot \
  --symbol 000300 --market CN --asset-type INDEX --as-of 2026-04-30

# 决策报告（信号 + 回测 + 持仓分析的综合报告）
python main.py decision-report \
  --symbol 000300 --market CN --asset-type INDEX --as-of 2026-04-30
```

### 数据诊断

```bash
python main.py qlib-health --start 2024-01-01 --end 2026-04-30
python main.py qlib-consistency
python main.py qlib-features --start 2026-01-01 --end 2026-04-30 --rows 10
```

## 全部可用命令

```
init-db               初始化数据库
seed-instruments      注册标的（CSV 导入）
list-instruments      列出已注册标的
ensure-history        拉取单标的历史数据
batch-ensure-history  批量拉取指数成分股数据
seed-index-constituents  导入指数成分股列表
update-daily          更新最近 N 天日线
update-stock-meta     更新股票元信息
update-financials     更新财务数据
update-dividends      更新分红数据
backfill-history      回填历史数据
replace-index-proxies 替换指数代理数据
rebuild-weekly        重建周线
repair-factors        修复复权因子
seed-trading-calendar 导入交易日历
detect-suspensions    检测停牌
position-add/list/close  持仓管理
refresh-qlib          构建/刷新 qlib .bin 数据集
export-qlib-csv       导出 qlib CSV 文件
performance           绩效分析
strategy-backtest     单策略回测
strategy-compare      多策略对比
strategy-search       最优策略搜索
strategy-report       生成策略报告
factor-analyze        单因子分析
factor-combine        因子合成
factor-backtest       因子组合回测
signal-snapshot       策略信号快照
decision-report       综合决策报告
qlib-health           qlib 数据健康检查
qlib-consistency      qlib 数据一致性检查
qlib-features         qlib 因子数据预览
rotation-demo         轮动策略演示
rotation-report       轮动策略报告
experiment-list/show  实验记录管理
etf-lookup            ETF 查找
stock-lookup          股票查找
wencai-query          问财查询
```

## 关键参数约定

- **market**: CN / US / HK
- **asset-type**: INDEX / STOCK / ETF / FUND
- **symbol**: 代码，如 000300（沪深300）、HSTECH（恒生科技）、002415（海康威视）
- **qlib 表达式**:
  - `$close` — 收盘价
  - `Std($close, 20)` — 20 日标准差
  - `$close / Ref($close, 20) - 1` — 20 日收益率
  - `Mean($volume, 5) / Mean($volume, 20)` — 5 日量比
  - `Sum($open, 5)` — 5 日开盘价之和

## 用户请求 → 命令映射

| 用户说 | 对应命令 |
|--------|----------|
| 对沪深300做KDJ回测 | `strategy-backtest --strategy kdj --symbol 000300 --market CN --asset-type INDEX --start ... --end ...` |
| 分析20日波动率因子 | `factor-analyze --factor-name "20日波动" --expression "Std($close,20)/$close" --start ... --end ...` |
| 构建沪深300成分股数据 | `seed-index-constituents --index 000300` → `batch-ensure-history --index 000300` → `refresh-qlib` |
| 000300现在该买还是卖 | `signal-snapshot --symbol 000300 --market CN --asset-type INDEX --as-of ...` |
| 更新数据 | `update-daily` → `refresh-qlib --incremental` |
| 对比所有策略 | `strategy-compare --strategies kdj bollinger ma_cross macd rsi --symbol ...` |
| 找最优策略 | `strategy-search --symbol ...` |
| 低波动选股回测 | `factor-backtest --factor-name "低波动" --expression "Std($close,20)/$close" --direction short --top-n 30` |

## 常见问题排查

### ModuleNotFoundError
依赖没装。检查 `requirements.txt`，询问用户如何安装（用户可能有 conda 环境、venv 等）。

### RuntimeError: 没有找到 qlib 的 scripts/dump_bin.py
检查 `vendor/qlib/scripts/dump_bin.py` 是否存在。如果缺失，从 https://github.com/microsoft/qlib/blob/main/scripts/dump_bin.py 下载到该路径即可。此文件只依赖 `qlib.utils`（pyqlib 包自带）、`fire`、`tqdm`、`loguru`。

### 回测结果全为 0 或不交易
- 检查起止日期是否在数据范围内
- 区间太短可能没有触发交易信号，拉长区间试试
- 用 `--force-refresh-qlib` 强制重建 qlib 数据

### factor-analyze 很慢
因子分析对每个截面做 IC/分层计算，标的越多越慢。可以先确认 qlib 数据已构建，然后用 `--skip-auto-refresh-qlib` 跳过不必要的重建。

### 运行时出现大量 CSV 转换日志
说明触发了 qlib 数据集全量重建。如果数据已经是最新的，这是浪费。等待完成后后续命令会自动跳过。

## 重要说明

- 数据库文件 `data/market_data.sqlite3` 不会被 git 跟踪
- 首次使用需要从零构建数据管线
- `dump_bin.py` 来自微软 qlib 仓库（MIT 协议），放在 `vendor/qlib/scripts/`
- mootdx（通达信）是 akshare 的备用数据源，仅在 akshare 失败时启用
- 所有研究产出保存在 `reports/` 目录
- vectorbt 引擎可用时默认用于 KDJ/布林线/双均线/MACD/RSI 回测
