# QuantResearch

### 面向 Claude Code 的个人量化研究工作台

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Built with qlib](https://img.shields.io/badge/built%20with-qlib-orange.svg)](https://github.com/microsoft/qlib)
[![Backtest](https://img.shields.io/badge/backtest-vectorbt-9cf.svg)](https://github.com/polakowo/vectorbt)
[![Workflow](https://img.shields.io/badge/workflow-Claude%20Code-black.svg)](#)

[English](README.md) | 中文

---

QuantResearch 是一个基于 **qlib**（数据 & 因子）、**vectorbt**（回测引擎）和统一 CLI 的本地量化研究工作台。它设计为**配合 Claude Code 使用**——打开项目，告诉 Claude 你想研究什么，Claude 执行命令。

## 能做什么

- 维护 A 股 / 港股 / 美股的指数、ETF、股票本地行情数据
- 技术策略回测（KDJ、布林线、MACD、RSI、双均线、定投）
- 横截面因子分析（IC、RankIC、分层收益、多空收益）
- 因子合成（等权 / ICIR 加权）
- 因子组合回测（按因子排序选股）
- 中文决策报告、信号快照
- 所有产出保存为 Markdown + JSON

## 不能做什么

- 不做前端页面
- 不自动交易
- 不接券商接口
- 不做"大而全的平台"

## 快速开始

```bash
# 前置：Python 3.12+
pip install -r requirements.txt

# 初始化数据库
python main.py init-db

# 注册示例标的
python main.py seed-instruments --csv-path data/instruments.sample.csv

# 为沪深 300 拉取数据
python main.py ensure-history --symbol 000300 --market CN --asset-type INDEX

# 构建 qlib 数据集
python main.py refresh-qlib

# 跑一个策略回测
python main.py strategy-backtest --strategy kdj --symbol 000300 --market CN --asset-type INDEX --start 2024-01-01 --end 2026-04-30

# 分析一个因子
python main.py factor-analyze --factor-name "20日波动" --expression "Std(\$close,20)/\$close"

# 查看所有命令
python main.py --help
```

## 环境预期

- 推荐环境：Python 3.12+，使用你自己的虚拟环境或 conda 环境
- 依赖安装方式：`pip install -r requirements.txt`
- `dump_bin.py`（qlib 的 CSV→.bin 转换脚本）已内置在 `vendor/qlib/scripts/dump_bin.py`，无需额外克隆 qlib 仓库。其依赖 `fire`、`tqdm`、`loguru`、`qlib.utils` 均已包含在 requirements.txt 中
- `data/instruments.sample.csv` 只是起步样例，真实研究仍需要你自己维护标的池和历史数据

### qlib 数据集智能刷新

`refresh_qlib()` 会自动判断是否需要重建 qlib `.bin` 数据集：
- **数据已覆盖** → 跳过重建（< 0.1 秒）
- **数据存在但有缺口** → 增量更新（仅追加新日期，通过 `dump_update`）
- **数据集不存在** → 全量构建（通过 `dump_all`）
- 在分析命令中加 `--force-refresh-qlib` 可强制全量重建
- 加 `--skip-auto-refresh-qlib` 可跳过数据准备，直接用已有数据
- `refresh-qlib` 命令默认强制重建，加 `--incremental` 切换为跳过/增量模式

## 配合 Claude Code 使用

1. 用 Claude Code 打开这个项目
2. 说：*"帮我构建沪深 300 成分股数据"* → Claude 自动跑数据管线
3. 说：*"分析 20 日波动率因子"* → Claude 跑因子分析
4. 说：*"对比海康威视上 KDJ 和 MACD 的表现"* → Claude 跑策略对比

Claude 会读取 `CLAUDE.md` 了解所有可用命令和工作流。

## 架构

```
数据源 (akshare / yfinance / mootdx)
        ↓
    SQLite (market_data.sqlite3)
        ↓
  CSV / Parquet 导出
        ↓
   qlib .bin 数据集
        ↓
   ┌─ 技术策略回测 (pandas / vectorbt)
   ├─ 因子分析 (IC / RankIC / 分层)
   ├─ 因子合成 (等权 / ICIR 加权)
   └─ 因子组合回测
        ↓
   报告 (Markdown + JSON)
```

## 开源协议

MIT
