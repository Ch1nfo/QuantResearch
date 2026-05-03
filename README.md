# QuantResearch

### Personal Quant Research Workbench for Claude Code

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Built with qlib](https://img.shields.io/badge/built%20with-qlib-orange.svg)](https://github.com/microsoft/qlib)
[![Backtest](https://img.shields.io/badge/backtest-vectorbt-9cf.svg)](https://github.com/polakowo/vectorbt)
[![Workflow](https://img.shields.io/badge/workflow-Claude%20Code-black.svg)](#)

[中文文档](README_ZH.md) | English

---

QuantResearch is a local quantitative research workbench built around **qlib** (data & factors), **vectorbt** (backtesting engine), and a clean CLI. It is designed to be used **with Claude Code** — open the project, tell Claude what you want to research, and Claude executes the commands.

## What it does

- Maintain local market data for CN/US/HK indices, ETFs, and stocks
- Run technical strategy backtests (KDJ, Bollinger, MACD, RSI, MA Cross, DCA)
- Cross-sectional factor analysis (IC, RankIC, quantile returns, long-short)
- Factor combination (equal-weight or ICIR-weighted)
- Factor-based portfolio backtesting (stock selection simulation)
- Generate Chinese decision reports and signal snapshots
- All results saved as Markdown + JSON

## What it does NOT do

- No frontend UI
- No automated trading
- No broker APIs
- No "heavy platform" ambitions

## Quick Start

```bash
# Prerequisites: Python 3.12+
pip install -r requirements.txt

# Initialize
python main.py init-db

# Register sample instruments
python main.py seed-instruments --csv-path data/instruments.sample.csv

# Build data for CSI 300 index
python main.py ensure-history --symbol 000300 --market CN --asset-type INDEX

# Build qlib dataset
python main.py refresh-qlib

# Run a strategy backtest
python main.py strategy-backtest --strategy kdj --symbol 000300 --market CN --asset-type INDEX --start 2024-01-01 --end 2026-04-30

# Analyze a factor
python main.py factor-analyze --factor-name "20d Vol" --expression "Std(\$close,20)/\$close"

# See all commands
python main.py --help
```

## Setup Expectations

- Recommended environment: Python 3.12+ in your own virtual environment
- Install dependencies with `pip install -r requirements.txt`
- If qlib cannot expose `dump_bin.py` from the installed package, set `QLIB_REPO=/path/to/qlib` before running `refresh-qlib`
- `data/instruments.sample.csv` is only a starter sample; real research needs your own local universe and history

## Using with Claude Code

1. Open this project in Claude Code
2. Say: *"Build data for CSI 300 constituents"* — Claude runs the data pipeline
3. Say: *"Analyze the 20-day volatility factor"* — Claude runs factor analysis
4. Say: *"Compare KDJ vs MACD on Hikvision"* — Claude runs strategy comparison

Claude reads `CLAUDE.md` to understand available commands and workflows.

## Architecture

```
Data Sources (akshare / yfinance / mootdx)
        ↓
    SQLite (market_data.sqlite3)
        ↓
  CSV / Parquet export
        ↓
   qlib .bin dataset
        ↓
   ┌─ Technical strategy backtest (pandas / vectorbt)
   ├─ Factor analysis (IC / RankIC / quantile)
   ├─ Factor combination (equal / ICIR weighted)
   └─ Factor portfolio backtest
        ↓
   Reports (Markdown + JSON)
```

## License

MIT
