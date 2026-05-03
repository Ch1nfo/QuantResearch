from pathlib import Path

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, QLIB_DATA_DIR, REPORTS_DIR
from .database import MarketDataDB
from .labels import format_qlib_instrument, relabel_rotation_picks
from .metrics import calc_performance_metrics, format_metrics
from .pipeline import ensure_history_coverage, refresh_qlib


DEFAULT_UNIVERSE = ["CN_000510", "CN_000300", "HK_HSTECH", "US_NDX", "US_GSPC"]


def prepare_rotation_dataset(
    universe: list[str],
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    end: str | None = None,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    force_refresh_qlib: bool = False,
) -> Path:
    db = MarketDataDB(db_path)
    db.init_db()
    db.seed_default_sources()
    for instrument in universe:
        market, symbol = parse_qlib_instrument(instrument)
        asset_type = resolve_asset_type(symbol, market, db_path=db_path)
        ensure_history_coverage(
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            db_path=db_path,
            target_years=target_years,
            end=end,
            refresh_recent_days=refresh_recent_days,
        )
    return refresh_qlib(
        dataset_name=dataset_name,
        db_path=db_path,
        qlib_repo=qlib_repo,
        output_dir=output_dir,
        force=force_refresh_qlib,
    )


def init_qlib(dataset_name: str = DEFAULT_DATASET_NAME) -> Path:
    provider_uri = QLIB_DATA_DIR / dataset_name
    if not provider_uri.exists():
        raise FileNotFoundError(f"没有找到 qlib 数据集：{provider_uri}")
    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    return provider_uri


def parse_qlib_instrument(instrument: str) -> tuple[str, str]:
    if "_" not in instrument:
        raise ValueError(f"Invalid qlib instrument format: {instrument}")
    market, symbol = instrument.split("_", 1)
    return market.upper(), symbol.upper()


def resolve_asset_type(symbol: str, market: str, db_path: Path | str = DEFAULT_DB_PATH) -> str:
    db = MarketDataDB(db_path)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT asset_type
            FROM instruments
            WHERE symbol = ? AND market = ?
            ORDER BY CASE asset_type
                WHEN 'INDEX' THEN 1
                WHEN 'ETF' THEN 2
                WHEN 'STOCK' THEN 3
                WHEN 'FUND' THEN 4
                ELSE 99
            END
            LIMIT 1
            """,
            (symbol.upper(), market.upper()),
        ).fetchone()
    return str(row["asset_type"]) if row else "INDEX"


def load_close_panel(universe: list[str], start: str, end: str) -> pd.DataFrame:
    frame = D.features(universe, ["$close"], start_time=start, end_time=end)
    panel = frame["$close"].unstack(level="instrument").sort_index()
    panel.index = pd.to_datetime(panel.index)
    return panel


def compute_rebalance_dates(close_panel: pd.DataFrame, rebalance: str) -> list[pd.Timestamp]:
    grouped = close_panel.groupby(pd.Grouper(freq="W-FRI" if rebalance == "weekly" else "ME"))
    dates = []
    for _, group in grouped:
        valid_rows = group.dropna(how="all")
        if not valid_rows.empty:
            dates.append(valid_rows.index[-1])
    return dates


def select_weights(
    close_panel: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp],
    lookback: int,
    top_k: int,
    require_positive_momentum: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = pd.DataFrame(0.0, index=close_panel.index, columns=close_panel.columns)
    picks = []

    for decision_date in rebalance_dates:
        date_loc = close_panel.index.get_loc(decision_date)
        if isinstance(date_loc, slice):
            date_loc = date_loc.stop - 1
        if date_loc < lookback or date_loc + 1 >= len(close_panel.index):
            continue

        history = close_panel.iloc[date_loc - lookback : date_loc + 1]
        momentum = (history.iloc[-1] / history.iloc[0] - 1).dropna()
        if momentum.empty:
            continue

        selected = momentum.sort_values(ascending=False).head(top_k)
        if require_positive_momentum:
            selected = selected[selected > 0]

        next_idx = date_loc + 1
        next_rebalance_pos = None
        for future_date in rebalance_dates:
            future_loc = close_panel.index.get_loc(future_date)
            if isinstance(future_loc, slice):
                future_loc = future_loc.stop - 1
            if future_loc > date_loc:
                next_rebalance_pos = future_loc + 1
                break
        end_idx = next_rebalance_pos if next_rebalance_pos is not None else len(close_panel.index)
        holding_slice = close_panel.index[next_idx:end_idx]
        if len(holding_slice) == 0:
            continue

        current_weights = pd.Series(0.0, index=close_panel.columns)
        if not selected.empty:
            current_weights.loc[selected.index] = 1.0 / len(selected)
        weights.loc[holding_slice, :] = current_weights.values
        picks.append(
            {
                "decision_date": decision_date.strftime("%Y-%m-%d"),
                "effective_date": close_panel.index[next_idx].strftime("%Y-%m-%d"),
                "selected": ",".join(selected.index.tolist()) if not selected.empty else "CASH",
                "scores": ", ".join(f"{k}:{v:.2%}" for k, v in selected.items())
                if not selected.empty
                else "no positive momentum",
            }
        )

    return weights, pd.DataFrame(picks)


def run_rotation_strategy(
    close_panel: pd.DataFrame,
    lookback: int,
    top_k: int,
    rebalance: str,
    require_positive_momentum: bool = False,
) -> tuple[pd.Series, pd.Series, pd.DataFrame, pd.DataFrame]:
    returns = close_panel.pct_change(fill_method=None).fillna(0.0)
    rebalance_dates = compute_rebalance_dates(close_panel, rebalance)
    weights, picks = select_weights(
        close_panel,
        rebalance_dates,
        lookback,
        top_k,
        require_positive_momentum=require_positive_momentum,
    )
    strategy_returns = (weights * returns).sum(axis=1)
    strategy_nav = (1 + strategy_returns).cumprod()
    benchmark_nav = (1 + returns.mean(axis=1)).cumprod()
    return strategy_nav, benchmark_nav, weights, picks


def summarize_rotation(
    strategy_nav: pd.Series, benchmark_nav: pd.Series, picks: pd.DataFrame, risk_free_rate: float, show_names: bool = True
) -> str:
    metrics = pd.DataFrame(
        {
            "动量轮动": calc_performance_metrics(strategy_nav, risk_free_rate=risk_free_rate),
            "等权基准": calc_performance_metrics(benchmark_nav, risk_free_rate=risk_free_rate),
        }
    )
    parts = [
        "=== 绩效指标 ===",
        format_metrics(metrics).to_string(),
        "",
        "=== 最近净值 ===",
        pd.DataFrame(
            {
                "动量轮动": strategy_nav.tail(5),
                "等权基准": benchmark_nav.tail(5),
            }
        ).to_string(),
    ]
    if not picks.empty:
        if show_names:
            picks = relabel_rotation_picks(picks)
        parts.extend(["", "=== 最近调仓 ===", picks.tail(10).to_string(index=False)])
    return "\n".join(parts)


def build_rotation_report(
    *,
    strategy_nav: pd.Series,
    benchmark_nav: pd.Series,
    picks: pd.DataFrame,
    start: str,
    end: str,
    lookback: int,
    top_k: int,
    rebalance: str,
    require_positive_momentum: bool,
    universe: list[str],
    risk_free_rate: float,
    show_names: bool = True,
) -> str:
    metrics = pd.DataFrame(
        {
            "动量轮动": calc_performance_metrics(strategy_nav, risk_free_rate=risk_free_rate),
            "等权基准": calc_performance_metrics(benchmark_nav, risk_free_rate=risk_free_rate),
        }
    )
    display_metrics = format_metrics(metrics)
    display_picks = relabel_rotation_picks(picks) if show_names and not picks.empty else picks
    universe_text = ", ".join(format_qlib_instrument(item) if show_names else item for item in universe)

    lines = [
        "# 指数动量轮动报告",
        "",
        "## 摘要",
        "",
        f"- 回测区间：`{start}` 至 `{end}`",
        f"- 资产池：{universe_text}",
        f"- 调仓频率：`{rebalance}`",
        f"- 动量窗口：`{lookback}` 个交易日",
        f"- 持仓数量：`{top_k}`",
        f"- 正动量过滤：`{'开启' if require_positive_momentum else '关闭'}`",
        "",
        "## 绩效指标",
        "",
        display_metrics.to_markdown(),
        "",
        "## 最近净值",
        "",
        pd.DataFrame(
            {
                "动量轮动": strategy_nav.tail(10),
                "等权基准": benchmark_nav.tail(10),
            }
        ).to_markdown(),
    ]
    if not display_picks.empty:
        lines.extend(
            [
                "",
                "## 最近调仓",
                "",
                display_picks.tail(12).to_markdown(index=False),
            ]
        )
    return "\n".join(lines)


def save_rotation_report(markdown: str, output_path: Path | str) -> Path:
    path = Path(output_path)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path
