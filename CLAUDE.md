# CLAUDE.md — QuantResearch 项目使用说明

## 项目是什么

QuantResearch 是一个本地量化研究工作台。它有三层：
- **qlib** — 本地数据存储和因子表达式引擎
- **vectorbt** — 技术策略回测引擎
- **QuantResearch** — CLI、报告、因子研究、实验记录

## 环境

- Python 3.12+
- 所有命令以 `python main.py <command>` 形式运行
- 工作目录必须是项目根目录

## 数据管线（从零构建）

用户告诉你要研究什么标的，你按这个顺序跑：

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

**批量构建指数成分股数据（推荐）：**
```bash
python main.py seed-index-constituents --index 000300
python main.py batch-ensure-history --index 000300
python main.py refresh-qlib
```

## 研究分析

### 技术策略回测
```bash
# 单策略
python main.py strategy-backtest --strategy kdj --symbol 002415 --market CN --asset-type STOCK --start 2024-01-01 --end 2026-04-30

# 多策略对比
python main.py strategy-compare --symbol 000300 --market CN --asset-type INDEX --start 2024-01-01 --end 2026-04-30

# 最优策略搜索
python main.py strategy-search --symbol 000300 --market CN --asset-type INDEX --start 2024-01-01 --end 2026-04-30
```

### 因子研究
```bash
# 单因子分析（IC / RankIC / 分层 / 多空）
python main.py factor-analyze --factor-name "20日波动" --expression "Std(\$close,20)/\$close" --start 2024-01-01 --end 2026-04-30

# 因子合成
python main.py factor-combine --factor-name "合成因子" --labels "波动" "动量" "量比" --expressions "Std(\$close,20)/\$close" "\$close/Ref(\$close,20)-1" "Mean(\$volume,5)/Mean(\$volume,20)" --method equal

# 因子组合回测（按因子选股模拟）
python main.py factor-backtest --factor-name "低波动" --expression "Std(\$close,20)/\$close" --direction short --top-n 30
```

### 决策与信号
```bash
# 信号快照
python main.py signal-snapshot --symbol 000300 --market CN --asset-type INDEX --as-of 2026-04-30

# 决策报告
python main.py decision-report --symbol 000300 --market CN --asset-type INDEX --as-of 2026-04-30
```

### 数据诊断
```bash
python main.py qlib-health --start 2024-01-01 --end 2026-04-30
python main.py qlib-consistency
python main.py qlib-features --start 2026-01-01 --end 2026-04-30 --rows 10
```

## 关键参数约定

- **market**: CN / US / HK
- **asset-type**: INDEX / STOCK / ETF / FUND
- **symbol**: 代码，如 000300（沪深300）、HSTECH（恒生科技）、002415（海康威视）
- **qlib 表达式示例**:
  - `$close` — 收盘价
  - `Std($close, 20)` — 20 日标准差
  - `$close / Ref($close, 20) - 1` — 20 日收益率
  - `Mean($volume, 5) / Mean($volume, 20)` — 5 日量比
  - `Sum($open, 5)` — 5 日开盘价之和

## 用户请求 → 命令映射

当用户说"我想沪深 300 指数做 KDJ 回测"，你该跑：
```bash
python main.py strategy-backtest --strategy kdj --symbol 000300 --market CN --asset-type INDEX
```

当用户说"分析一下 20 日波动率因子在沪深 300 上的表现"：
```bash
python main.py factor-analyze --factor-name "20日波动" --expression "Std(\$close,20)/\$close"
```

当用户说"帮我构建沪深 300 成分股的数据"：
```bash
python main.py seed-index-constituents --index 000300
python main.py batch-ensure-history --index 000300
python main.py refresh-qlib
```

## 重要说明

- 数据库文件 `data/market_data.sqlite3` 不会被 git 跟踪
- 首次使用需要从零构建数据管线
- qlib .bin 数据集构建需要已安装 qlib 且能找到 `dump_bin.py`
- mootdx（通达信）是 akshare 的备用数据源，仅在 akshare 失败时启用
- 所有研究产出保存在 `reports/` 目录
