import argparse
import json
from pathlib import Path

from .analysis import collect_metrics, collect_metrics_from_db, render_metrics_table
from .consistency import check_qlib_consistency, format_consistency_report
from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, REPORTS_DIR
from .database import MarketDataDB
from .decision import (
    default_decision_json_output,
    default_decision_output,
    generate_decision_report,
    save_decision_report,
)
from .etf_lookup import save_cn_etf_catalog, search_cn_etf_catalog
from .experiments import list_experiments, record_experiment, show_experiment
from .factor_portfolio import backtest_factor_portfolio, summarize_portfolio
from .factor_research import analyze_factor, combine_factors
from .exporters import export_dataset_for_qlib
from .pipeline import (
    backfill_history,
    batch_ensure_history,
    detect_suspensions,
    ensure_history_coverage,
    ensure_history_for_targets,
    refresh_qlib,
    repair_factors,
    replace_index_proxy_universe,
    seed_default_universe,
    seed_index_constituents,
    seed_trading_calendar,
    update_daily,
    update_dividends,
    update_financials,
    update_stock_meta,
)
from .qlib_support import build_qlib_bin
from .qlib_tools import format_health_table, qlib_data_health, qlib_feature_preview
from .queries import list_instruments
from .rotation import (
    DEFAULT_UNIVERSE,
    build_rotation_report,
    init_qlib,
    load_close_panel,
    prepare_rotation_dataset,
    run_rotation_strategy,
    save_rotation_report,
    summarize_rotation,
)
from .stock_lookup import save_cn_stock_catalog, search_cn_stock_catalog
from .serialization import dataframe_dict, dataframe_records, write_json
from .signals import default_signal_json_output, default_signal_output, generate_signal_snapshot, save_signal_snapshot
from .technical_strategies import (
    BACKTEST_ENGINES,
    STRATEGY_REGISTRY,
    build_strategy_search_report,
    compare_strategies,
    build_strategy_report,
    extract_trades,
    list_supported_strategies,
    load_qlib_ohlcv,
    rank_strategies,
    run_strategy_backtest,
    save_strategy_report,
    save_strategy_report as save_strategy_search_report,
    summarize_best_strategy,
    summarize_strategy_backtest,
    summarize_strategy_comparison,
)
from .wencai import DEFAULT_COOKIE_ENV, query_wencai, save_wencai_result, standardize_wencai_etf_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QuantResearch 本地量化研究工作台")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db")
    init_db_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    seed_parser = subparsers.add_parser("seed-instruments")
    seed_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    seed_parser.add_argument("--csv-path")
    seed_parser.add_argument("--use-defaults", action="store_true")

    list_parser = subparsers.add_parser("list-instruments")
    list_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    list_parser.add_argument("--market")
    list_parser.add_argument("--asset-type")

    backfill_parser = subparsers.add_parser("backfill-history")
    backfill_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    backfill_parser.add_argument("--start", default="2000-01-01")
    backfill_parser.add_argument("--end")
    backfill_parser.add_argument("--symbol")
    backfill_parser.add_argument("--market")
    backfill_parser.add_argument("--asset-type")

    ensure_parser = subparsers.add_parser("ensure-history")
    ensure_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ensure_parser.add_argument("--symbol")
    ensure_parser.add_argument("--market")
    ensure_parser.add_argument("--asset-type")
    ensure_parser.add_argument("--target-years", type=int, default=20)
    ensure_parser.add_argument("--end")
    ensure_parser.add_argument("--refresh-recent-days", type=int, default=14)

    replace_index_parser = subparsers.add_parser("replace-index-proxies")
    replace_index_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    replace_index_parser.add_argument("--target-years", type=int, default=20)
    replace_index_parser.add_argument("--end")
    replace_index_parser.add_argument("--refresh-recent-days", type=int, default=14)

    update_parser = subparsers.add_parser("update-daily")
    update_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    update_parser.add_argument("--window-days", type=int, default=14)
    update_parser.add_argument("--symbol")
    update_parser.add_argument("--market")
    update_parser.add_argument("--asset-type")

    weekly_parser = subparsers.add_parser("rebuild-weekly")
    weekly_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    repair_parser = subparsers.add_parser("repair-factors")
    repair_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    repair_parser.add_argument("--target-years", type=int, default=20)
    repair_parser.add_argument("--end")
    repair_parser.add_argument("--refresh-recent-days", type=int, default=14)

    seed_const_parser = subparsers.add_parser("seed-index-constituents")
    seed_const_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    seed_const_parser.add_argument("--index", required=True, help="指数代码，如 000300（沪深300）、000905（中证500）")

    batch_parser = subparsers.add_parser("batch-ensure-history")
    batch_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    batch_parser.add_argument("--index", required=True, help="指数代码")
    batch_parser.add_argument("--target-years", type=int, default=20)
    batch_parser.add_argument("--end")
    batch_parser.add_argument("--refresh-recent-days", type=int, default=14)

    meta_parser = subparsers.add_parser("update-stock-meta")
    meta_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    fin_parser = subparsers.add_parser("update-financials")
    fin_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    div_parser = subparsers.add_parser("update-dividends")
    div_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    cal_parser = subparsers.add_parser("seed-trading-calendar")
    cal_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    susp_parser = subparsers.add_parser("detect-suspensions")
    susp_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    susp_parser.add_argument("--min-gap", type=int, default=3)

    pos_add_parser = subparsers.add_parser("position-add")
    pos_add_parser.add_argument("--symbol", required=True)
    pos_add_parser.add_argument("--market", default="CN")
    pos_add_parser.add_argument("--entry-date", required=True)
    pos_add_parser.add_argument("--entry-price", type=float, required=True)
    pos_add_parser.add_argument("--quantity", type=float, required=True)
    pos_add_parser.add_argument("--current-value", type=float, default=0)
    pos_add_parser.add_argument("--notes", default="")
    pos_add_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    pos_list_parser = subparsers.add_parser("position-list")
    pos_list_parser.add_argument("--status", choices=("OPEN", "CLOSED", "ALL"), default="OPEN")
    pos_list_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    pos_close_parser = subparsers.add_parser("position-close")
    pos_close_parser.add_argument("--position-id", type=int, required=True)
    pos_close_parser.add_argument("--exit-date", required=True)
    pos_close_parser.add_argument("--exit-price", type=float, default=0)
    pos_close_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))

    export_parser = subparsers.add_parser("export-qlib-csv")
    export_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    export_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    export_parser.add_argument("--start")
    export_parser.add_argument("--end")

    qlib_parser = subparsers.add_parser("build-qlib-bin")
    qlib_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    qlib_parser.add_argument("--qlib-repo")
    qlib_parser.add_argument("--output-dir")

    refresh_parser = subparsers.add_parser("refresh-qlib")
    refresh_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    refresh_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    refresh_parser.add_argument("--start")
    refresh_parser.add_argument("--end")
    refresh_parser.add_argument("--qlib-repo")
    refresh_parser.add_argument("--output-dir")
    refresh_parser.add_argument("--incremental", action="store_true",
                                help="增量更新模式（仅追加新数据，不清除已有数据集）")

    performance_parser = subparsers.add_parser("performance")
    performance_parser.add_argument("--source", choices=("remote", "db"), default="db")
    performance_parser.add_argument("--market", required=True)
    performance_parser.add_argument("--asset-type", default="ETF")
    performance_parser.add_argument("--symbols", nargs="+", required=True)
    performance_parser.add_argument("--start", required=True)
    performance_parser.add_argument("--end", required=True)
    performance_parser.add_argument("--adjusted", action="store_true")
    performance_parser.add_argument("--hide-names", action="store_true")

    kdj_parser = subparsers.add_parser("kdj-backtest")
    kdj_parser.add_argument("--source", choices=("remote", "db"), default="db")
    kdj_parser.add_argument("--symbol", required=True)
    kdj_parser.add_argument("--market", required=True)
    kdj_parser.add_argument("--asset-type", default="ETF")
    kdj_parser.add_argument("--start", required=True)
    kdj_parser.add_argument("--end", required=True)
    kdj_parser.add_argument("--n", type=int, default=9)
    kdj_parser.add_argument("--fee-rate", type=float, default=0.0005)
    kdj_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    kdj_parser.add_argument("--signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    kdj_parser.add_argument("--oversold", type=float, default=20.0)
    kdj_parser.add_argument("--overbought", type=float, default=80.0)
    kdj_parser.add_argument("--hide-names", action="store_true")
    kdj_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    kdj_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    kdj_parser.add_argument("--qlib-repo")
    kdj_parser.add_argument("--output-dir")
    kdj_parser.add_argument("--target-years", type=int, default=20)
    kdj_parser.add_argument("--refresh-recent-days", type=int, default=14)
    kdj_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    boll_parser = subparsers.add_parser("bollinger-backtest")
    boll_parser.add_argument("--symbol", required=True)
    boll_parser.add_argument("--market", required=True)
    boll_parser.add_argument("--asset-type", default="ETF")
    boll_parser.add_argument("--start", required=True)
    boll_parser.add_argument("--end", required=True)
    boll_parser.add_argument("--window", type=int, default=20)
    boll_parser.add_argument("--std-multiplier", type=float, default=2.0)
    boll_parser.add_argument("--fee-rate", type=float, default=0.0005)
    boll_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    boll_parser.add_argument("--signal-mode", choices=("reversion", "breakout"), default="reversion")
    boll_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    boll_parser.add_argument("--hide-names", action="store_true")
    boll_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    boll_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    boll_parser.add_argument("--qlib-repo")
    boll_parser.add_argument("--output-dir")
    boll_parser.add_argument("--target-years", type=int, default=20)
    boll_parser.add_argument("--refresh-recent-days", type=int, default=14)
    boll_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    strategy_backtest_parser = subparsers.add_parser("strategy-backtest")
    strategy_backtest_parser.add_argument("--strategy", choices=tuple(STRATEGY_REGISTRY.keys()), required=True)
    strategy_backtest_parser.add_argument("--symbol", required=True)
    strategy_backtest_parser.add_argument("--market", required=True)
    strategy_backtest_parser.add_argument("--asset-type", default="ETF")
    strategy_backtest_parser.add_argument("--start", required=True)
    strategy_backtest_parser.add_argument("--end", required=True)
    strategy_backtest_parser.add_argument("--fee-rate", type=float, default=0.0005)
    strategy_backtest_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    strategy_backtest_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    strategy_backtest_parser.add_argument("--hide-names", action="store_true")
    strategy_backtest_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    strategy_backtest_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    strategy_backtest_parser.add_argument("--qlib-repo")
    strategy_backtest_parser.add_argument("--output-dir")
    strategy_backtest_parser.add_argument("--target-years", type=int, default=20)
    strategy_backtest_parser.add_argument("--refresh-recent-days", type=int, default=14)
    strategy_backtest_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    strategy_backtest_parser.add_argument("--force-refresh-qlib", action="store_true")
    strategy_backtest_parser.add_argument("--kdj-n", type=int, default=9)
    strategy_backtest_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    strategy_backtest_parser.add_argument("--oversold", type=float, default=20.0)
    strategy_backtest_parser.add_argument("--overbought", type=float, default=80.0)
    strategy_backtest_parser.add_argument("--boll-window", type=int, default=20)
    strategy_backtest_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    strategy_backtest_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    strategy_backtest_parser.add_argument("--ma-short-window", type=int, default=10)
    strategy_backtest_parser.add_argument("--ma-long-window", type=int, default=30)
    strategy_backtest_parser.add_argument("--macd-fast-period", type=int, default=12)
    strategy_backtest_parser.add_argument("--macd-slow-period", type=int, default=26)
    strategy_backtest_parser.add_argument("--macd-signal-period", type=int, default=9)
    strategy_backtest_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    strategy_backtest_parser.add_argument("--rsi-period", type=int, default=14)
    strategy_backtest_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    strategy_backtest_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    strategy_backtest_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    strategy_backtest_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    strategy_backtest_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    strategy_backtest_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    strategy_backtest_parser.add_argument("--dca-monthly-day", type=int, default=1)

    strategy_compare_parser = subparsers.add_parser("strategy-compare")
    strategy_compare_parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_REGISTRY.keys()), required=True)
    strategy_compare_parser.add_argument("--symbol", required=True)
    strategy_compare_parser.add_argument("--market", required=True)
    strategy_compare_parser.add_argument("--asset-type", default="ETF")
    strategy_compare_parser.add_argument("--start", required=True)
    strategy_compare_parser.add_argument("--end", required=True)
    strategy_compare_parser.add_argument("--fee-rate", type=float, default=0.0005)
    strategy_compare_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    strategy_compare_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    strategy_compare_parser.add_argument("--hide-names", action="store_true")
    strategy_compare_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    strategy_compare_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    strategy_compare_parser.add_argument("--qlib-repo")
    strategy_compare_parser.add_argument("--output-dir")
    strategy_compare_parser.add_argument("--target-years", type=int, default=20)
    strategy_compare_parser.add_argument("--refresh-recent-days", type=int, default=14)
    strategy_compare_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    strategy_compare_parser.add_argument("--kdj-n", type=int, default=9)
    strategy_compare_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    strategy_compare_parser.add_argument("--oversold", type=float, default=20.0)
    strategy_compare_parser.add_argument("--overbought", type=float, default=80.0)
    strategy_compare_parser.add_argument("--boll-window", type=int, default=20)
    strategy_compare_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    strategy_compare_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    strategy_compare_parser.add_argument("--ma-short-window", type=int, default=10)
    strategy_compare_parser.add_argument("--ma-long-window", type=int, default=30)
    strategy_compare_parser.add_argument("--macd-fast-period", type=int, default=12)
    strategy_compare_parser.add_argument("--macd-slow-period", type=int, default=26)
    strategy_compare_parser.add_argument("--macd-signal-period", type=int, default=9)
    strategy_compare_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    strategy_compare_parser.add_argument("--rsi-period", type=int, default=14)
    strategy_compare_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    strategy_compare_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    strategy_compare_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    strategy_compare_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    strategy_compare_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    strategy_compare_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    strategy_compare_parser.add_argument("--dca-monthly-day", type=int, default=1)

    strategy_report_parser = subparsers.add_parser("strategy-report")
    strategy_report_parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_REGISTRY.keys()), required=True)
    strategy_report_parser.add_argument("--symbol", required=True)
    strategy_report_parser.add_argument("--market", required=True)
    strategy_report_parser.add_argument("--asset-type", default="ETF")
    strategy_report_parser.add_argument("--start", required=True)
    strategy_report_parser.add_argument("--end", required=True)
    strategy_report_parser.add_argument("--fee-rate", type=float, default=0.0005)
    strategy_report_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    strategy_report_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    strategy_report_parser.add_argument("--hide-names", action="store_true")
    strategy_report_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    strategy_report_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    strategy_report_parser.add_argument("--qlib-repo")
    strategy_report_parser.add_argument("--output-dir")
    strategy_report_parser.add_argument("--target-years", type=int, default=20)
    strategy_report_parser.add_argument("--refresh-recent-days", type=int, default=14)
    strategy_report_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    strategy_report_parser.add_argument("--output", default=str(REPORTS_DIR / "strategy_report.md"))
    strategy_report_parser.add_argument("--json-output")
    strategy_report_parser.add_argument("--kdj-n", type=int, default=9)
    strategy_report_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    strategy_report_parser.add_argument("--oversold", type=float, default=20.0)
    strategy_report_parser.add_argument("--overbought", type=float, default=80.0)
    strategy_report_parser.add_argument("--boll-window", type=int, default=20)
    strategy_report_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    strategy_report_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    strategy_report_parser.add_argument("--ma-short-window", type=int, default=10)
    strategy_report_parser.add_argument("--ma-long-window", type=int, default=30)
    strategy_report_parser.add_argument("--macd-fast-period", type=int, default=12)
    strategy_report_parser.add_argument("--macd-slow-period", type=int, default=26)
    strategy_report_parser.add_argument("--macd-signal-period", type=int, default=9)
    strategy_report_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    strategy_report_parser.add_argument("--rsi-period", type=int, default=14)
    strategy_report_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    strategy_report_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    strategy_report_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    strategy_report_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    strategy_report_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    strategy_report_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    strategy_report_parser.add_argument("--dca-monthly-day", type=int, default=1)

    strategy_search_parser = subparsers.add_parser("strategy-search")
    strategy_search_parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_REGISTRY.keys()))
    strategy_search_parser.add_argument("--symbol", required=True)
    strategy_search_parser.add_argument("--market", required=True)
    strategy_search_parser.add_argument("--asset-type", default="ETF")
    strategy_search_parser.add_argument("--start", required=True)
    strategy_search_parser.add_argument("--end", required=True)
    strategy_search_parser.add_argument("--fee-rate", type=float, default=0.0005)
    strategy_search_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    strategy_search_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    strategy_search_parser.add_argument("--objective", choices=("composite", "sharpe_ratio", "annual_return", "max_drawdown"), default="composite")
    strategy_search_parser.add_argument("--hide-names", action="store_true")
    strategy_search_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    strategy_search_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    strategy_search_parser.add_argument("--qlib-repo")
    strategy_search_parser.add_argument("--output-dir")
    strategy_search_parser.add_argument("--target-years", type=int, default=20)
    strategy_search_parser.add_argument("--refresh-recent-days", type=int, default=14)
    strategy_search_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    strategy_search_parser.add_argument("--output")
    strategy_search_parser.add_argument("--json-output")
    strategy_search_parser.add_argument("--kdj-n", type=int, default=9)
    strategy_search_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    strategy_search_parser.add_argument("--oversold", type=float, default=20.0)
    strategy_search_parser.add_argument("--overbought", type=float, default=80.0)
    strategy_search_parser.add_argument("--boll-window", type=int, default=20)
    strategy_search_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    strategy_search_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    strategy_search_parser.add_argument("--ma-short-window", type=int, default=10)
    strategy_search_parser.add_argument("--ma-long-window", type=int, default=30)
    strategy_search_parser.add_argument("--macd-fast-period", type=int, default=12)
    strategy_search_parser.add_argument("--macd-slow-period", type=int, default=26)
    strategy_search_parser.add_argument("--macd-signal-period", type=int, default=9)
    strategy_search_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    strategy_search_parser.add_argument("--rsi-period", type=int, default=14)
    strategy_search_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    strategy_search_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    strategy_search_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    strategy_search_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    strategy_search_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    strategy_search_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    strategy_search_parser.add_argument("--dca-monthly-day", type=int, default=1)

    qlib_health_parser = subparsers.add_parser("qlib-health")
    qlib_health_parser.add_argument("--universe", nargs="+", default=DEFAULT_UNIVERSE)
    qlib_health_parser.add_argument("--start", default="2024-01-01")
    qlib_health_parser.add_argument("--end", default="2026-05-01")
    qlib_health_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    qlib_health_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    qlib_health_parser.add_argument("--qlib-repo")
    qlib_health_parser.add_argument("--output-dir")
    qlib_health_parser.add_argument("--target-years", type=int, default=20)
    qlib_health_parser.add_argument("--refresh-recent-days", type=int, default=14)
    qlib_health_parser.add_argument("--large-move-threshold", type=float, default=0.15)
    qlib_health_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    qlib_health_parser.add_argument("--json-output")

    qlib_consistency_parser = subparsers.add_parser("qlib-consistency")
    qlib_consistency_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    qlib_consistency_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    qlib_consistency_parser.add_argument("--qlib-dir")
    qlib_consistency_parser.add_argument("--json-output")

    qlib_features_parser = subparsers.add_parser("qlib-features")
    qlib_features_parser.add_argument("--universe", nargs="+", default=DEFAULT_UNIVERSE)
    qlib_features_parser.add_argument("--start", default="2024-01-01")
    qlib_features_parser.add_argument("--end", default="2026-05-01")
    qlib_features_parser.add_argument("--expr", action="append", default=[])
    qlib_features_parser.add_argument("--rows", type=int, default=20)
    qlib_features_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    qlib_features_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    qlib_features_parser.add_argument("--qlib-repo")
    qlib_features_parser.add_argument("--output-dir")
    qlib_features_parser.add_argument("--target-years", type=int, default=20)
    qlib_features_parser.add_argument("--refresh-recent-days", type=int, default=14)
    qlib_features_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    signal_parser = subparsers.add_parser("signal-snapshot")
    signal_parser.add_argument("--symbol", required=True)
    signal_parser.add_argument("--market", required=True)
    signal_parser.add_argument("--asset-type", default="INDEX")
    signal_parser.add_argument("--as-of", required=True)
    signal_parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_REGISTRY.keys()), default=["kdj", "bollinger", "ma_cross", "macd", "rsi"])
    signal_parser.add_argument("--output")
    signal_parser.add_argument("--json-output")
    signal_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    signal_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    signal_parser.add_argument("--qlib-repo")
    signal_parser.add_argument("--output-dir")
    signal_parser.add_argument("--target-years", type=int, default=20)
    signal_parser.add_argument("--refresh-recent-days", type=int, default=14)
    signal_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    signal_parser.add_argument("--force-refresh-qlib", action="store_true")
    signal_parser.add_argument("--lookback-days", type=int, default=500)
    signal_parser.add_argument("--hide-names", action="store_true")
    signal_parser.add_argument("--fee-rate", type=float, default=0.0005)
    signal_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    signal_parser.add_argument("--kdj-n", type=int, default=9)
    signal_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    signal_parser.add_argument("--oversold", type=float, default=20.0)
    signal_parser.add_argument("--overbought", type=float, default=80.0)
    signal_parser.add_argument("--boll-window", type=int, default=20)
    signal_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    signal_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    signal_parser.add_argument("--ma-short-window", type=int, default=10)
    signal_parser.add_argument("--ma-long-window", type=int, default=30)
    signal_parser.add_argument("--macd-fast-period", type=int, default=12)
    signal_parser.add_argument("--macd-slow-period", type=int, default=26)
    signal_parser.add_argument("--macd-signal-period", type=int, default=9)
    signal_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    signal_parser.add_argument("--rsi-period", type=int, default=14)
    signal_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    signal_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    signal_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    signal_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    signal_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    signal_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    signal_parser.add_argument("--dca-monthly-day", type=int, default=1)

    decision_parser = subparsers.add_parser("decision-report")
    decision_parser.add_argument("--symbol", required=True)
    decision_parser.add_argument("--market", required=True)
    decision_parser.add_argument("--asset-type", default="INDEX")
    decision_parser.add_argument("--as-of", required=True)
    decision_parser.add_argument("--strategies", nargs="+", choices=tuple(STRATEGY_REGISTRY.keys()), default=["kdj", "bollinger", "ma_cross", "macd", "rsi", "dca"])
    decision_parser.add_argument("--output")
    decision_parser.add_argument("--json-output")
    decision_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    decision_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    decision_parser.add_argument("--qlib-repo")
    decision_parser.add_argument("--output-dir")
    decision_parser.add_argument("--target-years", type=int, default=20)
    decision_parser.add_argument("--refresh-recent-days", type=int, default=14)
    decision_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    decision_parser.add_argument("--history-years", type=int, default=2)
    decision_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    decision_parser.add_argument("--hide-names", action="store_true")
    decision_parser.add_argument("--fee-rate", type=float, default=0.0005)
    decision_parser.add_argument("--engine", choices=BACKTEST_ENGINES, default="auto")
    decision_parser.add_argument("--kdj-n", type=int, default=9)
    decision_parser.add_argument("--kdj-signal-mode", choices=("cross", "extreme_cross"), default="extreme_cross")
    decision_parser.add_argument("--oversold", type=float, default=20.0)
    decision_parser.add_argument("--overbought", type=float, default=80.0)
    decision_parser.add_argument("--boll-window", type=int, default=20)
    decision_parser.add_argument("--boll-std-multiplier", type=float, default=2.0)
    decision_parser.add_argument("--boll-signal-mode", choices=("reversion", "breakout"), default="reversion")
    decision_parser.add_argument("--ma-short-window", type=int, default=10)
    decision_parser.add_argument("--ma-long-window", type=int, default=30)
    decision_parser.add_argument("--macd-fast-period", type=int, default=12)
    decision_parser.add_argument("--macd-slow-period", type=int, default=26)
    decision_parser.add_argument("--macd-signal-period", type=int, default=9)
    decision_parser.add_argument("--macd-signal-mode", choices=("cross", "zero_confirm"), default="cross")
    decision_parser.add_argument("--rsi-period", type=int, default=14)
    decision_parser.add_argument("--rsi-oversold", type=float, default=30.0)
    decision_parser.add_argument("--rsi-overbought", type=float, default=70.0)
    decision_parser.add_argument("--rsi-signal-mode", choices=("reversion", "midline"), default="reversion")
    decision_parser.add_argument("--dca-amount-per-buy", type=float, default=1000.0)
    decision_parser.add_argument("--dca-frequency", choices=("daily", "weekly", "monthly", "quarterly"), default="monthly")
    decision_parser.add_argument("--dca-weekly-day", type=int, choices=range(0, 5), default=0)
    decision_parser.add_argument("--dca-monthly-day", type=int, default=1)

    experiment_list_parser = subparsers.add_parser("experiment-list")
    experiment_list_parser.add_argument("--kind")
    experiment_list_parser.add_argument("--limit", type=int, default=20)
    experiment_list_parser.add_argument("--json-output")

    experiment_show_parser = subparsers.add_parser("experiment-show")
    experiment_show_parser.add_argument("--experiment-id", required=True)
    experiment_show_parser.add_argument("--json-output")

    rotation_parser = subparsers.add_parser("rotation-demo")
    rotation_parser.add_argument("--start", default="2024-01-01")
    rotation_parser.add_argument("--end", default="2026-05-01")
    rotation_parser.add_argument("--lookback", type=int, default=20)
    rotation_parser.add_argument("--top-k", type=int, default=1)
    rotation_parser.add_argument("--rebalance", choices=("monthly", "weekly"), default="monthly")
    rotation_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    rotation_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    rotation_parser.add_argument("--require-positive-momentum", action="store_true")
    rotation_parser.add_argument("--universe", nargs="+", default=DEFAULT_UNIVERSE)
    rotation_parser.add_argument("--hide-names", action="store_true")
    rotation_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    rotation_parser.add_argument("--qlib-repo")
    rotation_parser.add_argument("--output-dir")
    rotation_parser.add_argument("--target-years", type=int, default=20)
    rotation_parser.add_argument("--refresh-recent-days", type=int, default=14)
    rotation_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    rotation_report_parser = subparsers.add_parser("rotation-report")
    rotation_report_parser.add_argument("--start", default="2024-01-01")
    rotation_report_parser.add_argument("--end", default="2026-05-01")
    rotation_report_parser.add_argument("--lookback", type=int, default=20)
    rotation_report_parser.add_argument("--top-k", type=int, default=1)
    rotation_report_parser.add_argument("--rebalance", choices=("monthly", "weekly"), default="monthly")
    rotation_report_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    rotation_report_parser.add_argument("--risk-free-rate", type=float, default=0.0)
    rotation_report_parser.add_argument("--require-positive-momentum", action="store_true")
    rotation_report_parser.add_argument("--universe", nargs="+", default=DEFAULT_UNIVERSE)
    rotation_report_parser.add_argument("--hide-names", action="store_true")
    rotation_report_parser.add_argument("--output", default=str(REPORTS_DIR / "rotation_report.md"))
    rotation_report_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    rotation_report_parser.add_argument("--qlib-repo")
    rotation_report_parser.add_argument("--output-dir")
    rotation_report_parser.add_argument("--target-years", type=int, default=20)
    rotation_report_parser.add_argument("--refresh-recent-days", type=int, default=14)
    rotation_report_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    factor_bt_parser = subparsers.add_parser("factor-backtest")
    factor_bt_parser.add_argument("--factor-name", required=True, help="因子名称")
    factor_bt_parser.add_argument("--expression", required=True, help="qlib 因子表达式")
    factor_bt_parser.add_argument("--universe-source", default="index", choices=("index", "list"),
                                  help="标的池来源：index=指数成分股，list=手动列表")
    factor_bt_parser.add_argument("--index-symbol", default="000300", help="指数代码")
    factor_bt_parser.add_argument("--index-market", default="CN", help="指数市场")
    factor_bt_parser.add_argument("--universe-list", nargs="+", default=[], help="手动标的列表")
    factor_bt_parser.add_argument("--start", default="2024-01-01")
    factor_bt_parser.add_argument("--end", default="2026-04-30")
    factor_bt_parser.add_argument("--top-n", type=int, default=30, help="持仓数量")
    factor_bt_parser.add_argument("--direction", choices=("long", "short", "long_short"), default="long")
    factor_bt_parser.add_argument("--rebalance", choices=("weekly", "monthly"), default="weekly")
    factor_bt_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    factor_bt_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    factor_bt_parser.add_argument("--qlib-repo")
    factor_bt_parser.add_argument("--output-dir")
    factor_bt_parser.add_argument("--target-years", type=int, default=20)
    factor_bt_parser.add_argument("--refresh-recent-days", type=int, default=14)
    factor_bt_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    factor_bt_parser.add_argument("--force-refresh-qlib", action="store_true")

    factor_analyze_parser = subparsers.add_parser("factor-analyze")
    factor_analyze_parser.add_argument("--factor-name", required=True, help="因子名称")
    factor_analyze_parser.add_argument("--expression", required=True, help="qlib 因子表达式")
    factor_analyze_parser.add_argument("--universe-source", default="index", choices=("index", "list"))
    factor_analyze_parser.add_argument("--index-symbol", default="000300")
    factor_analyze_parser.add_argument("--index-market", default="CN")
    factor_analyze_parser.add_argument("--universe-list", nargs="+", default=[])
    factor_analyze_parser.add_argument("--start", default="2024-01-01")
    factor_analyze_parser.add_argument("--end", default="2026-04-30")
    factor_analyze_parser.add_argument("--quantiles", type=int, default=5)
    factor_analyze_parser.add_argument("--forward-days", type=int, default=5)
    factor_analyze_parser.add_argument("--rebalance", choices=("daily", "weekly", "monthly"), default="weekly")
    factor_analyze_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    factor_analyze_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    factor_analyze_parser.add_argument("--qlib-repo")
    factor_analyze_parser.add_argument("--output-dir")
    factor_analyze_parser.add_argument("--target-years", type=int, default=20)
    factor_analyze_parser.add_argument("--refresh-recent-days", type=int, default=14)
    factor_analyze_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")
    factor_analyze_parser.add_argument("--force-refresh-qlib", action="store_true")

    factor_combine_parser = subparsers.add_parser("factor-combine")
    factor_combine_parser.add_argument("--factor-name", required=True, help="合成因子名称")
    factor_combine_parser.add_argument("--expressions", nargs="+", required=True,
                                        help="子因子表达式列表")
    factor_combine_parser.add_argument("--labels", nargs="+", required=True,
                                        help="子因子名称列表（与expressions一一对应）")
    factor_combine_parser.add_argument("--method", choices=("equal", "icir"), default="equal")
    factor_combine_parser.add_argument("--universe-source", default="index", choices=("index", "list"))
    factor_combine_parser.add_argument("--index-symbol", default="000300")
    factor_combine_parser.add_argument("--index-market", default="CN")
    factor_combine_parser.add_argument("--universe-list", nargs="+", default=[])
    factor_combine_parser.add_argument("--start", default="2024-01-01")
    factor_combine_parser.add_argument("--end", default="2026-04-30")
    factor_combine_parser.add_argument("--quantiles", type=int, default=5)
    factor_combine_parser.add_argument("--forward-days", type=int, default=5)
    factor_combine_parser.add_argument("--rebalance", choices=("weekly", "monthly"), default="weekly")
    factor_combine_parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    factor_combine_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    factor_combine_parser.add_argument("--qlib-repo")
    factor_combine_parser.add_argument("--output-dir")
    factor_combine_parser.add_argument("--target-years", type=int, default=20)
    factor_combine_parser.add_argument("--refresh-recent-days", type=int, default=14)
    factor_combine_parser.add_argument("--skip-auto-refresh-qlib", action="store_true")

    etf_lookup_parser = subparsers.add_parser("etf-lookup")
    etf_lookup_parser.add_argument("--query")
    etf_lookup_parser.add_argument("--refresh", action="store_true")
    etf_lookup_parser.add_argument("--limit", type=int, default=20)
    etf_lookup_parser.add_argument("--save")

    stock_lookup_parser = subparsers.add_parser("stock-lookup")
    stock_lookup_parser.add_argument("--query")
    stock_lookup_parser.add_argument("--refresh", action="store_true")
    stock_lookup_parser.add_argument("--limit", type=int, default=20)
    stock_lookup_parser.add_argument("--save")

    wencai_parser = subparsers.add_parser("wencai-query")
    wencai_parser.add_argument("--query", required=True)
    wencai_parser.add_argument("--cookie")
    wencai_parser.add_argument("--cookie-env", default=DEFAULT_COOKIE_ENV)
    wencai_parser.add_argument("--sort-key")
    wencai_parser.add_argument("--sort-order", choices=("asc", "desc"), default="desc")
    wencai_parser.add_argument("--perpage", type=int, default=100)
    wencai_parser.add_argument("--loop", default="false")
    wencai_parser.add_argument("--save")
    wencai_parser.add_argument("--standardize-etf", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        db = MarketDataDB(args.db_path)
        db.init_db()
        db.seed_default_sources()
        print(f"数据库已初始化：{args.db_path}")
        return

    if args.command == "seed-instruments":
        db = MarketDataDB(args.db_path)
        db.init_db()
        db.seed_default_sources()
        inserted = 0
        if args.use_defaults:
            inserted += seed_default_universe(args.db_path)
        if args.csv_path:
            inserted += db.seed_instruments_from_csv(args.csv_path)
        print(f"已导入 {inserted} 个标的")
        return

    if args.command == "list-instruments":
        frame = list_instruments(args.db_path, market=args.market, asset_type=args.asset_type)
        print(frame.to_string(index=False) if not frame.empty else "没有找到标的")
        return

    if args.command == "backfill-history":
        results = backfill_history(
            db_path=args.db_path,
            start=args.start,
            end=args.end,
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
        )
        print(_format_results(results))
        return

    if args.command == "ensure-history":
        if args.symbol:
            result = ensure_history_coverage(
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                db_path=args.db_path,
                target_years=args.target_years,
                end=args.end,
                refresh_recent_days=args.refresh_recent_days,
            )
            print(_format_results([result]))
        else:
            results = ensure_history_for_targets(
                db_path=args.db_path,
                market=args.market,
                asset_type=args.asset_type,
                target_years=args.target_years,
                end=args.end,
                refresh_recent_days=args.refresh_recent_days,
            )
            print(_format_results(results))
        return

    if args.command == "replace-index-proxies":
        results = replace_index_proxy_universe(
            db_path=args.db_path,
            target_years=args.target_years,
            end=args.end,
            refresh_recent_days=args.refresh_recent_days,
        )
        print(_format_results(results))
        return

    if args.command == "update-daily":
        results = update_daily(
            db_path=args.db_path,
            window_days=args.window_days,
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
        )
        print(_format_results(results))
        return

    if args.command == "rebuild-weekly":
        db = MarketDataDB(args.db_path)
        count = db.rebuild_weekly_bars()
        print(f"已重建 {count} 行周线数据")
        return

    if args.command == "repair-factors":
        results = repair_factors(
            db_path=args.db_path,
            target_years=args.target_years,
            end=args.end,
        )
        if not results:
            db = MarketDataDB(args.db_path)
            remaining = db.get_instruments_needing_factor_repair()
            if remaining:
                print(f"修复失败，仍有 {len(remaining)} 个标的未修复（可能是网络问题，请重试）:")
                for inst in remaining:
                    print(f"  ✗ {inst['symbol']} ({inst['market']}/{inst['asset_type']})")
            else:
                print("所有标的复权因子已修复 ✓")
            return
        for item in results:
            print(f"✓ {item.symbol} ({item.market}/{item.asset_type}) 复权因子已修复，更新 {item.row_count} 行")
        return

    if args.command == "seed-index-constituents":
        db = MarketDataDB(args.db_path)
        idx = db.get_instrument(args.index, "CN", "INDEX")
        if idx is None:
            print(f"错误：指数 {args.index} 不在 instruments 表中，请先 seed-instruments --use-defaults")
            return
        count = seed_index_constituents(index_symbol=args.index, db_path=args.db_path)
        print(f"已导入 {args.index} 指数成分股 {count} 只")
        return

    if args.command == "batch-ensure-history":
        db = MarketDataDB(args.db_path)
        idx = db.get_instrument(args.index, "CN", "INDEX")
        if idx is None:
            print(f"错误：指数 {args.index} 不在 instruments 表中，请先 seed-instruments --use-defaults 再 seed-index-constituents --index {args.index}")
            return
        cp = db.get_checkpoint(f"batch-{args.index}")
        total = cp["total_count"] if cp else 0
        done = cp["completed_count"] if cp else 0
        if cp and cp["status"] == "DONE":
            print(f"batch-{args.index}: 已全部完成 ({done}/{total})")
        else:
            if cp:
                print(f"batch-{args.index}: 断点续传，已完成 {done}/{total}，继续采集...")
            results = batch_ensure_history(
                index_symbol=args.index,
                db_path=args.db_path,
                target_years=args.target_years,
                end=args.end,
                refresh_recent_days=args.refresh_recent_days,
            )
            new_done = done + len(results)
            print(f"batch-{args.index}: 本轮新增 {len(results)} 只，累计 {new_done}/{total}")
            if new_done >= total:
                print(f"batch-{args.index}: 全部完成！可以运行 refresh-qlib 重建 qlib 数据")
        return

    if args.command == "update-stock-meta":
        update_stock_meta(db_path=args.db_path)
        return

    if args.command == "update-financials":
        update_financials(db_path=args.db_path)
        return

    if args.command == "update-dividends":
        update_dividends(db_path=args.db_path)
        return

    if args.command == "seed-trading-calendar":
        seed_trading_calendar(db_path=args.db_path)
        return

    if args.command == "detect-suspensions":
        print(f"检测停牌中（最小连续缺失 {args.min_gap} 天）...")
        detect_suspensions(db_path=args.db_path, min_gap=args.min_gap)
        return

    if args.command == "position-add":
        db = MarketDataDB(args.db_path)
        pid = db.add_position(
            symbol=args.symbol, market=args.market,
            entry_date=args.entry_date, entry_price=args.entry_price,
            quantity=args.quantity, current_value=args.current_value,
            notes=args.notes,
        )
        print(f"已添加持仓 #{pid}: {args.symbol} 成本{args.entry_price*args.quantity:.0f} 市值{args.current_value:.0f}")
        return

    if args.command == "position-list":
        db = MarketDataDB(args.db_path)
        positions = db.list_positions(status=args.status)
        if not positions:
            print("没有持仓记录")
            return
        print(f"{'ID':>3s} {'代码':8s} {'名称':14s} {'入场':10s} {'成本':>10s} {'市值':>10s} {'盈亏':>10s} {'盈亏%':>7s} {'占比':>6s}")
        print("-" * 86)
        total_cost = 0
        total_value = 0
        for p in positions:
            print(f"{p['position_id']:3d} {p['symbol']:8s} {(p['name'] or ''):14s} {p['entry_date']:10s} "
                  f"{p['cost']:10.0f} {p['current_value']:10.0f} {p['pnl']:+10.0f} {p['pnl_pct']:+7.2f}% {p['alloc_pct']:5.1f}%")
            total_cost += p['cost']
            total_value += p['current_value']
        total_pnl = total_value - total_cost
        print("-" * 86)
        print(f"{'':>3s} {'':8s} {'':14s} {'':10s} "
              f"{total_cost:10.0f} {total_value:10.0f} {total_pnl:+10.0f} {total_pnl/total_cost*100 if total_cost else 0:+7.2f}% {'100.0':>6s}%")
        return

    if args.command == "position-close":
        db = MarketDataDB(args.db_path)
        db.close_position(
            position_id=args.position_id,
            exit_date=args.exit_date,
            exit_price=args.exit_price,
        )
        print(f"持仓 #{args.position_id} 已平仓")
        return

    if args.command == "export-qlib-csv":
        paths = export_dataset_for_qlib(
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            start=args.start,
            end=args.end,
        )
        print(f"已导出 {len(paths)} 个 qlib CSV 文件")
        return

    if args.command == "build-qlib-bin":
        output = build_qlib_bin(
            dataset_name=args.dataset_name,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
        )
        print(f"qlib 数据已构建：{output}")
        return

    if args.command == "refresh-qlib":
        output = refresh_qlib(
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            start=args.start,
            end=args.end,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            force=not args.incremental,
        )
        print(f"qlib 数据已刷新：{output}")
        return

    if args.command == "performance":
        if args.source == "db":
            metrics = collect_metrics_from_db(
                symbols=args.symbols,
                market=args.market,
                asset_type=args.asset_type,
                start=args.start,
                end=args.end,
                adjusted=args.adjusted,
            )
        else:
            metrics = collect_metrics(
                symbols=args.symbols,
                market=args.market,
                asset_type=args.asset_type,
                start=args.start,
                end=args.end,
            )
        print(render_metrics_table(metrics, market=args.market, asset_type=args.asset_type, show_names=not args.hide_names))
        return

    if args.command == "kdj-backtest":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        result = run_strategy_backtest(
            "kdj",
            frame,
            kdj_n=args.n,
            fee_rate=args.fee_rate,
            kdj_signal_mode=args.signal_mode,
            oversold=args.oversold,
            overbought=args.overbought,
            backtest_engine=args.engine,
        )
        print(
            summarize_strategy_backtest(
                result,
                strategy="kdj",
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                risk_free_rate=0.0,
                show_names=not args.hide_names,
                strategy_text=(
                    f"数据源=qlib，周期={args.n}，信号模式={args.signal_mode}，"
                    f"超卖={args.oversold}，超买={args.overbought}"
                ),
            )
        )
        return

    if args.command == "bollinger-backtest":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        result = run_strategy_backtest(
            "bollinger",
            frame,
            boll_window=args.window,
            boll_std_multiplier=args.std_multiplier,
            boll_signal_mode=args.signal_mode,
            fee_rate=args.fee_rate,
            backtest_engine=args.engine,
        )
        print(
            summarize_strategy_backtest(
                result,
                strategy="bollinger",
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                risk_free_rate=args.risk_free_rate,
                show_names=not args.hide_names,
                strategy_text=(
                    f"数据源=qlib，窗口={args.window}，标准差倍数={args.std_multiplier}，"
                    f"信号模式={args.signal_mode}"
                ),
            )
        )
        return

    if args.command == "strategy-backtest":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
            force_refresh_qlib=args.force_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        result = run_strategy_backtest(args.strategy, frame, **_strategy_params_from_args(args))
        print(
            summarize_strategy_backtest(
                result,
                strategy=args.strategy,
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                risk_free_rate=args.risk_free_rate,
                show_names=not args.hide_names,
                strategy_text="数据源=qlib",
            )
        )
        return

    if args.command == "strategy-compare":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        nav_frame, metrics, _ = compare_strategies(
            frame,
            args.strategies,
            risk_free_rate=args.risk_free_rate,
            **_strategy_params_from_args(args),
        )
        print(
            summarize_strategy_comparison(
                nav_frame=nav_frame,
                metrics=metrics,
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                strategies=args.strategies,
                show_names=not args.hide_names,
            )
        )
        return

    if args.command == "strategy-report":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        params = _strategy_params_from_args(args)
        nav_frame, metrics, details = compare_strategies(
            frame,
            args.strategies,
            risk_free_rate=args.risk_free_rate,
            **params,
        )
        markdown = build_strategy_report(
            nav_frame=nav_frame,
            metrics=metrics,
            details=details,
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            strategies=args.strategies,
            params=params,
            show_names=not args.hide_names,
        )
        output = save_strategy_report(markdown, args.output)
        json_output = None
        payload = _strategy_report_payload(
            command="strategy-report",
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            strategies=args.strategies,
            dataset_name=args.dataset_name,
            params=params,
            metrics=metrics,
            nav_frame=nav_frame,
            details=details,
        )
        if args.json_output:
            json_output = write_json(payload, args.json_output)
            print(f"策略报告 JSON 已保存：{json_output}")
        record_experiment(
            kind="strategy-report",
            payload=payload,
            dataset_name=args.dataset_name,
            markdown_path=output,
            json_path=json_output,
        )
        print(f"策略报告已保存：{output}")
        return

    if args.command == "strategy-search":
        frame = load_qlib_ohlcv(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        if frame.empty:
            raise SystemExit("没有读取到该标的在指定区间内的 OHLCV 数据。")
        strategies = args.strategies or list_supported_strategies()
        params = _strategy_params_from_args(args)
        nav_frame, metrics, _ = compare_strategies(
            frame,
            strategies,
            risk_free_rate=args.risk_free_rate,
            **params,
        )
        ranking = rank_strategies(metrics, strategies, objective=args.objective)
        print(
            summarize_best_strategy(
                nav_frame=nav_frame,
                metrics=metrics,
                ranking=ranking,
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                objective=args.objective,
                show_names=not args.hide_names,
            )
        )
        if args.output:
            markdown = build_strategy_search_report(
                nav_frame=nav_frame,
                metrics=metrics,
                ranking=ranking,
                symbol=args.symbol,
                market=args.market,
                asset_type=args.asset_type,
                start=args.start,
                end=args.end,
                objective=args.objective,
                strategies=strategies,
                params=params,
                show_names=not args.hide_names,
            )
            output = save_strategy_search_report(markdown, args.output)
            print(f"\n最优策略搜索报告已保存：{output}")
        else:
            output = None
        payload = _strategy_search_payload(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            start=args.start,
            end=args.end,
            strategies=strategies,
            dataset_name=args.dataset_name,
            params=params,
            objective=args.objective,
            ranking=ranking,
            metrics=metrics,
            nav_frame=nav_frame,
        )
        json_output = write_json(payload, args.json_output) if args.json_output else None
        if json_output:
            print(f"最优策略搜索 JSON 已保存：{json_output}")
        record_experiment(
            kind="strategy-search",
            payload=payload,
            dataset_name=args.dataset_name,
            markdown_path=output,
            json_path=json_output,
        )
        return

    if args.command == "qlib-health":
        frame = qlib_data_health(
            universe=args.universe,
            start=args.start,
            end=args.end,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            auto_prepare=not args.skip_auto_refresh_qlib,
            large_move_threshold=args.large_move_threshold,
        )
        print(format_health_table(frame))
        if args.json_output:
            output = write_json(
                {
                    "command": "qlib-health",
                    "dataset_name": args.dataset_name,
                    "start": args.start,
                    "end": args.end,
                    "universe": args.universe,
                    "records": dataframe_records(frame),
                },
                args.json_output,
            )
            print(f"qlib 健康检查 JSON 已保存：{output}")
        return

    if args.command == "qlib-consistency":
        result = check_qlib_consistency(
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_dir=args.qlib_dir,
        )
        print(format_consistency_report(result))
        if args.json_output:
            output = write_json(result, args.json_output)
            print(f"qlib 一致性检查 JSON 已保存：{output}")
        return

    if args.command == "qlib-features":
        frame = qlib_feature_preview(
            universe=args.universe,
            start=args.start,
            end=args.end,
            expressions=_parse_expressions(args.expr),
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            auto_prepare=not args.skip_auto_refresh_qlib,
            rows=args.rows,
        )
        print(frame.to_string(index=False) if not frame.empty else "没有读取到 qlib 特征数据。")
        return

    if args.command == "signal-snapshot":
        params = _strategy_params_from_args(args)
        snapshot = generate_signal_snapshot(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            as_of=args.as_of,
            strategies=args.strategies,
            params=params,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
            force_refresh_qlib=args.force_refresh_qlib,
            lookback_days=args.lookback_days,
        )
        output = args.output or str(default_signal_output(args.symbol, args.as_of))
        json_output = args.json_output or str(default_signal_json_output(args.symbol, args.as_of))
        markdown_path, json_path, _ = save_signal_snapshot(
            snapshot,
            output=output,
            json_output=json_output,
            show_names=not args.hide_names,
        )
        print(f"信号快照已保存：{markdown_path}")
        print(f"信号快照 JSON 已保存：{json_path}")
        return

    if args.command == "decision-report":
        params = _strategy_params_from_args(args)
        report = generate_decision_report(
            symbol=args.symbol,
            market=args.market,
            asset_type=args.asset_type,
            as_of=args.as_of,
            strategies=args.strategies,
            params=params,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            auto_prepare=not args.skip_auto_refresh_qlib,
            history_years=args.history_years,
            risk_free_rate=args.risk_free_rate,
        )
        output = args.output or str(default_decision_output(args.symbol, args.as_of))
        json_output = args.json_output or str(default_decision_json_output(args.symbol, args.as_of))
        markdown_path, json_path, _ = save_decision_report(
            report,
            output=output,
            json_output=json_output,
            show_names=not args.hide_names,
        )
        print(f"决策报告已保存：{markdown_path}")
        print(f"决策报告 JSON 已保存：{json_path}")
        return

    if args.command == "experiment-list":
        records = list_experiments(kind=args.kind, limit=args.limit)
        payload = {"records": records, "limit": args.limit, "kind": args.kind}
        if args.json_output:
            output = write_json(payload, args.json_output)
            print(f"实验列表 JSON 已保存：{output}")
        print(_format_experiment_list(records))
        return

    if args.command == "experiment-show":
        record = show_experiment(args.experiment_id)
        if record is None:
            raise SystemExit(f"没有找到实验记录：{args.experiment_id}")
        if args.json_output:
            output = write_json(record, args.json_output)
            print(f"实验记录 JSON 已保存：{output}")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return

    if args.command == "rotation-demo":
        if not args.skip_auto_refresh_qlib:
            prepare_rotation_dataset(
                args.universe,
                dataset_name=args.dataset_name,
                db_path=args.db_path,
                target_years=args.target_years,
                end=args.end,
                refresh_recent_days=args.refresh_recent_days,
                qlib_repo=args.qlib_repo,
                output_dir=args.output_dir,
            )
        init_qlib(args.dataset_name)
        close_panel = load_close_panel(args.universe, args.start, args.end)
        strategy_nav, benchmark_nav, _, picks = run_rotation_strategy(
            close_panel=close_panel,
            lookback=args.lookback,
            top_k=args.top_k,
            rebalance=args.rebalance,
            require_positive_momentum=args.require_positive_momentum,
        )
        print(summarize_rotation(strategy_nav, benchmark_nav, picks, args.risk_free_rate, show_names=not args.hide_names))
        return

    if args.command == "rotation-report":
        if not args.skip_auto_refresh_qlib:
            prepare_rotation_dataset(
                args.universe,
                dataset_name=args.dataset_name,
                db_path=args.db_path,
                target_years=args.target_years,
                end=args.end,
                refresh_recent_days=args.refresh_recent_days,
                qlib_repo=args.qlib_repo,
                output_dir=args.output_dir,
            )
        init_qlib(args.dataset_name)
        close_panel = load_close_panel(args.universe, args.start, args.end)
        strategy_nav, benchmark_nav, _, picks = run_rotation_strategy(
            close_panel=close_panel,
            lookback=args.lookback,
            top_k=args.top_k,
            rebalance=args.rebalance,
            require_positive_momentum=args.require_positive_momentum,
        )
        markdown = build_rotation_report(
            strategy_nav=strategy_nav,
            benchmark_nav=benchmark_nav,
            picks=picks,
            start=args.start,
            end=args.end,
            lookback=args.lookback,
            top_k=args.top_k,
            rebalance=args.rebalance,
            require_positive_momentum=args.require_positive_momentum,
            universe=args.universe,
            risk_free_rate=args.risk_free_rate,
            show_names=not args.hide_names,
        )
        output = save_rotation_report(markdown, args.output)
        print(f"轮动报告已保存：{output}")
        return

    if args.command == "factor-backtest":
        universe = _resolve_factor_universe(args)
        result = backtest_factor_portfolio(
            universe=universe,
            start=args.start,
            end=args.end,
            factor_name=args.factor_name,
            expression=args.expression,
            top_n=args.top_n,
            direction=args.direction,
            rebalance=args.rebalance,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        print(summarize_portfolio(result))
        return

    if args.command == "factor-analyze":
        universe = _resolve_factor_universe(args)
        result = analyze_factor(
            universe=universe,
            start=args.start,
            end=args.end,
            factor_name=args.factor_name,
            expression=args.expression,
            quantiles=args.quantiles,
            forward_days=args.forward_days,
            rebalance=args.rebalance,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            auto_prepare=not args.skip_auto_refresh_qlib,
            force_refresh_qlib=args.force_refresh_qlib,
        )
        s = result.summary
        print(f"因子: {s['factor_name']}")
        print(f"表达式: {s['expression']}")
        print(f"观测期数: {s['date_count']} | 平均样本: {s['mean_sample_size']:.0f}")
        print(f"IC={s['mean_ic']:.4f} | RankIC={s['mean_rank_ic']:.4f} | IR={s['ic_ir']:.2f}")
        print(f"多空累计收益: {s['long_short_cum_return']:.2%}")
        print()
        print("=== 分层收益 (最近5期) ===")
        print(result.quantile_returns.tail(5).to_string())
        return

    if args.command == "factor-combine":
        if len(args.expressions) != len(args.labels):
            raise SystemExit("--expressions 和 --labels 数量必须一致")
        universe = _resolve_factor_universe(args)
        factors = [{"name": lbl, "expression": expr}
                   for lbl, expr in zip(args.labels, args.expressions)]
        result = combine_factors(
            universe=universe,
            start=args.start,
            end=args.end,
            factors=factors,
            method=args.method,
            quantiles=args.quantiles,
            forward_days=args.forward_days,
            rebalance=args.rebalance,
            dataset_name=args.dataset_name,
            db_path=args.db_path,
            target_years=args.target_years,
            refresh_recent_days=args.refresh_recent_days,
            qlib_repo=args.qlib_repo,
            output_dir=args.output_dir,
            auto_prepare=not args.skip_auto_refresh_qlib,
        )
        s = result.summary
        print(f"合成因子: {s['factor_name']}")
        print(f"方法: {args.method} | 观测期数: {s['date_count']}")
        print(f"IC={s['mean_ic']:.4f} | IR={s['ic_ir']:.2f} | 多空累计={s['long_short_cum_return']:.2%}")
        if result.sub_factor_weights:
            print("子因子权重:")
            for name, w in result.sub_factor_weights.items():
                print(f"  {name}: {w:.2%}")
        return

    if args.command == "etf-lookup":
        result = search_cn_etf_catalog(
            query=args.query,
            refresh=args.refresh,
            limit=args.limit,
        )
        if args.save:
            output = save_cn_etf_catalog(result, args.save)
            print(f"已保存 {len(result)} 行到 {output}")
        else:
            print(result.to_string(index=False) if not result.empty else "没有返回数据")
        return

    if args.command == "stock-lookup":
        result = search_cn_stock_catalog(
            query=args.query,
            refresh=args.refresh,
            limit=args.limit,
        )
        if args.save:
            output = save_cn_stock_catalog(result, args.save)
            print(f"已保存 {len(result)} 行到 {output}")
        else:
            print(result.to_string(index=False) if not result.empty else "没有返回数据")
        return

    if args.command == "wencai-query":
        loop = _parse_loop(args.loop)
        try:
            result = query_wencai(
                query=args.query,
                cookie=args.cookie,
                cookie_env=args.cookie_env,
                sort_key=args.sort_key,
                sort_order=args.sort_order,
                perpage=args.perpage,
                loop=loop,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if args.standardize_etf:
            result = standardize_wencai_etf_result(result, source_query=args.query)
        if args.save:
            output = save_wencai_result(result, args.save)
            print(f"已保存 {len(result)} 行到 {output}")
        else:
            print(result.to_string(index=False) if not result.empty else "没有返回数据")
        return


def _format_results(results) -> str:
    if not results:
        return "没有同步到新数据"
    lines = []
    for item in results:
        lines.append(f"{item.market}:{item.asset_type}:{item.symbol} -> {item.row_count} 行")
    return "\n".join(lines)


def _strategy_report_payload(
    *,
    command: str,
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    strategies: list[str],
    dataset_name: str,
    params: dict,
    metrics,
    nav_frame,
    details,
) -> dict:
    return {
        "command": command,
        "symbol": symbol.upper(),
        "market": market.upper(),
        "asset_type": asset_type.upper(),
        "start": start,
        "end": end,
        "dataset_name": dataset_name,
        "strategies": strategies,
        "params": params,
        "metrics": dataframe_dict(metrics),
        "nav_tail": dataframe_records(nav_frame.tail(20).reset_index()),
        "recent_trades": {
            strategy: dataframe_records(extract_trades(detail).tail(12)) for strategy, detail in details.items()
        },
    }


def _strategy_search_payload(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    strategies: list[str],
    dataset_name: str,
    params: dict,
    objective: str,
    ranking,
    metrics,
    nav_frame,
) -> dict:
    return {
        "command": "strategy-search",
        "symbol": symbol.upper(),
        "market": market.upper(),
        "asset_type": asset_type.upper(),
        "start": start,
        "end": end,
        "dataset_name": dataset_name,
        "strategies": strategies,
        "objective": objective,
        "params": params,
        "ranking": dataframe_records(ranking),
        "metrics": dataframe_dict(metrics),
        "nav_tail": dataframe_records(nav_frame.tail(20).reset_index()),
    }


def _format_experiment_list(records: list[dict]) -> str:
    if not records:
        return "没有实验记录。"
    lines = ["实验ID | 类型 | 时间 | 标的 | 报告"]
    for record in records:
        payload = record.get("payload") or {}
        symbol = payload.get("symbol") or "-"
        market = payload.get("market") or "-"
        asset_type = payload.get("asset_type") or "-"
        target = f"{symbol}/{market}/{asset_type}" if symbol != "-" else "-"
        lines.append(
            " | ".join(
                [
                    str(record.get("experiment_id")),
                    str(record.get("kind")),
                    str(record.get("created_at")),
                    target,
                    str(record.get("markdown_path") or "-"),
                ]
            )
        )
    return "\n".join(lines)


def _strategy_params_from_args(args) -> dict:
    return {
        "backtest_engine": getattr(args, "engine", "auto"),
        "fee_rate": args.fee_rate,
        "kdj_n": getattr(args, "kdj_n", getattr(args, "n", 9)),
        "kdj_signal_mode": getattr(args, "kdj_signal_mode", getattr(args, "signal_mode", "extreme_cross")),
        "oversold": getattr(args, "oversold", 20.0),
        "overbought": getattr(args, "overbought", 80.0),
        "boll_window": getattr(args, "boll_window", getattr(args, "window", 20)),
        "boll_std_multiplier": getattr(args, "boll_std_multiplier", getattr(args, "std_multiplier", 2.0)),
        "boll_signal_mode": getattr(args, "boll_signal_mode", getattr(args, "signal_mode", "reversion")),
        "ma_short_window": getattr(args, "ma_short_window", 10),
        "ma_long_window": getattr(args, "ma_long_window", 30),
        "macd_fast_period": getattr(args, "macd_fast_period", 12),
        "macd_slow_period": getattr(args, "macd_slow_period", 26),
        "macd_signal_period": getattr(args, "macd_signal_period", 9),
        "macd_signal_mode": getattr(args, "macd_signal_mode", "cross"),
        "rsi_period": getattr(args, "rsi_period", 14),
        "rsi_oversold": getattr(args, "rsi_oversold", 30.0),
        "rsi_overbought": getattr(args, "rsi_overbought", 70.0),
        "rsi_signal_mode": getattr(args, "rsi_signal_mode", "reversion"),
        "dca_amount_per_buy": getattr(args, "dca_amount_per_buy", 1000.0),
        "dca_frequency": getattr(args, "dca_frequency", "monthly"),
        "dca_weekly_day": getattr(args, "dca_weekly_day", 0),
        "dca_monthly_day": getattr(args, "dca_monthly_day", 1),
    }


def _parse_loop(value: str):
    lowered = str(value).strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return int(value)


def _parse_expressions(values: list[str]) -> dict[str, str] | None:
    if not values:
        return None
    expressions = {}
    for item in values:
        if "=" not in item:
            raise SystemExit("自定义表达式格式应为：名称=qlib表达式，例如：20日收益=$close / Ref($close, 20) - 1")
        name, expression = item.split("=", 1)
        name = name.strip()
        expression = expression.strip()
        if not name or not expression:
            raise SystemExit("自定义表达式的名称和 qlib 表达式都不能为空。")
        expressions[name] = expression
    return expressions


def _resolve_factor_universe(args) -> list[str]:
    """解析 factor-backtest 的标的池参数。"""
    if args.universe_source == "list":
        if not args.universe_list:
            raise SystemExit("--universe-source=list 时必须提供 --universe-list")
        return list(args.universe_list)

    from .database import MarketDataDB

    db = MarketDataDB(args.db_path)
    ids = db.get_constituent_ids(args.index_symbol, args.index_market)
    if not ids:
        raise SystemExit(f"指数 {args.index_symbol}/{args.index_market} 无成分股，请先运行 seed-index-constituents")
    with db.connect() as conn:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT symbol, market, asset_type FROM instruments WHERE instrument_id IN ({placeholders})",
            ids,
        ).fetchall()
    return [f"{r['market']}_{r['symbol']}" for r in rows]


if __name__ == "__main__":
    main()
