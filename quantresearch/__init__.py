"""QuantResearch —— 本地量化研究工作台。

三层架构：数据层 (collectors/database/pipeline) →
         研究层 (qlib_tools/factor_research/technical_strategies) →
         报告层 (signals/decision/experiments)
"""

from .database import MarketDataDB
from .etf_lookup import search_cn_etf_catalog
from .exporters import export_dataset_for_qlib, export_symbol_for_qlib
from .qlib_support import build_qlib_bin
from .queries import get_close_series, get_price_history, list_instruments
from .rotation import DEFAULT_UNIVERSE, run_rotation_strategy
from .wencai import query_wencai, resolve_wencai_cookie

__all__ = [
    "DEFAULT_UNIVERSE",
    "MarketDataDB",
    "build_qlib_bin",
    "export_dataset_for_qlib",
    "export_symbol_for_qlib",
    "get_close_series",
    "get_price_history",
    "list_instruments",
    "search_cn_etf_catalog",
    "run_rotation_strategy",
    "query_wencai",
    "resolve_wencai_cookie",
]
