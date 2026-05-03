import pandas as pd

from .collectors import collect_history
from .labels import relabel_metric_columns
from .metrics import calc_performance_metrics, format_metrics
from .queries import get_close_series


def collect_metrics(symbols: list[str], market: str, asset_type: str, start: str, end: str) -> pd.DataFrame:
    metric_items = {}
    for symbol in symbols:
        frame = collect_history(symbol=symbol, market=market, asset_type=asset_type, start=start, end=end)
        if frame.empty:
            continue
        metric_items[symbol] = calc_performance_metrics(frame["close"])
    return pd.DataFrame(metric_items)


def collect_metrics_from_db(
    symbols: list[str],
    market: str,
    asset_type: str,
    start: str,
    end: str,
    adjusted: bool = False,
    auto_fetch: bool = True,
    target_years: int = 20,
) -> pd.DataFrame:
    metric_items = {}
    for symbol in symbols:
        close = get_close_series(
            symbol,
            market,
            asset_type,
            start,
            end,
            adjusted=adjusted,
            auto_fetch=auto_fetch,
            target_years=target_years,
        )
        if close.empty:
            continue
        metric_items[symbol] = calc_performance_metrics(close)
    return pd.DataFrame(metric_items)


def render_metrics_table(
    metrics: pd.DataFrame, market: str | None = None, asset_type: str = "ETF", show_names: bool = True
) -> str:
    if metrics.empty:
        return "没有可计算的数据"
    if show_names and market:
        metrics = relabel_metric_columns(metrics, market=market, asset_type=asset_type)
    return format_metrics(metrics).to_string()
