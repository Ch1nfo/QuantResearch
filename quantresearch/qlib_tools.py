from __future__ import annotations

from pathlib import Path

import pandas as pd
from qlib.data import D

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH
from .labels import format_qlib_instrument
from .rotation import DEFAULT_UNIVERSE, init_qlib, prepare_rotation_dataset


DEFAULT_FEATURE_EXPRESSIONS = {
    "收盘价": "$close",
    "20日收益": "$close / Ref($close, 20) - 1",
    "20日均线": "Mean($close, 20)",
    "20日波动": "Std($close, 20)",
    "20日成交量均值": "Mean($volume, 20)",
}


def prepare_qlib_universe(
    universe: list[str],
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    end: str | None = None,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
) -> None:
    if auto_prepare:
        prepare_rotation_dataset(
            universe,
            dataset_name=dataset_name,
            db_path=db_path,
            target_years=target_years,
            end=end,
            refresh_recent_days=refresh_recent_days,
            qlib_repo=qlib_repo,
            output_dir=output_dir,
            force_refresh_qlib=force_refresh_qlib,
        )
    init_qlib(dataset_name)


def qlib_data_health(
    universe: list[str] | None = None,
    *,
    start: str,
    end: str,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
    large_move_threshold: float = 0.15,
) -> pd.DataFrame:
    instruments = universe or DEFAULT_UNIVERSE
    prepare_qlib_universe(
        instruments,
        dataset_name=dataset_name,
        db_path=db_path,
        end=end,
        target_years=target_years,
        refresh_recent_days=refresh_recent_days,
        qlib_repo=qlib_repo,
        output_dir=output_dir,
        auto_prepare=auto_prepare,
        force_refresh_qlib=force_refresh_qlib,
    )
    frame = D.features(
        instruments,
        ["$open", "$high", "$low", "$close", "$volume", "$factor"],
        start_time=start,
        end_time=end,
    )
    if frame.empty:
        return pd.DataFrame()
    data = frame.reset_index()
    data["datetime"] = pd.to_datetime(data["datetime"])
    rows = []
    for instrument, group in data.groupby("instrument"):
        group = group.sort_values("datetime").dropna(subset=["$close"]).copy()
        for column in ("$open", "$high", "$low"):
            group[column] = group[column].fillna(group["$close"])
        group["$volume"] = group["$volume"].fillna(0.0)
        group["$factor"] = group["$factor"].fillna(1.0)
        if group.empty:
            continue
        close = group["$close"]
        returns = close.pct_change(fill_method=None).abs()
        rows.append(
            {
                "标的": format_qlib_instrument(instrument),
                "代码": instrument,
                "开始日期": group["datetime"].min().strftime("%Y-%m-%d"),
                "结束日期": group["datetime"].max().strftime("%Y-%m-%d"),
                "行数": len(group),
                "缺失值数量": int(group.isna().sum().sum()),
                "缺失率": group.isna().sum().sum() / max(group.size, 1),
                "大幅波动天数": int((returns > large_move_threshold).sum()),
            }
        )
    return pd.DataFrame(rows)


def qlib_feature_preview(
    universe: list[str] | None = None,
    *,
    start: str,
    end: str,
    expressions: dict[str, str] | None = None,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
    rows: int = 20,
) -> pd.DataFrame:
    instruments = universe or DEFAULT_UNIVERSE
    expr_map = expressions or DEFAULT_FEATURE_EXPRESSIONS
    prepare_qlib_universe(
        instruments,
        dataset_name=dataset_name,
        db_path=db_path,
        end=end,
        target_years=target_years,
        refresh_recent_days=refresh_recent_days,
        qlib_repo=qlib_repo,
        output_dir=output_dir,
        auto_prepare=auto_prepare,
        force_refresh_qlib=force_refresh_qlib,
    )
    frame = D.features(instruments, list(expr_map.values()), start_time=start, end_time=end)
    if frame.empty:
        return pd.DataFrame()
    renamed = frame.rename(columns={value: key for key, value in expr_map.items()}).reset_index()
    renamed["标的"] = renamed["instrument"].map(format_qlib_instrument)
    renamed["日期"] = pd.to_datetime(renamed["datetime"]).dt.strftime("%Y-%m-%d")
    renamed = renamed.sort_values(["datetime", "instrument"])
    ordered_columns = ["日期", "标的", *expr_map.keys()]
    return renamed[ordered_columns].tail(rows)


def format_health_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "没有读取到 qlib 数据。"
    display = frame.copy()
    display["缺失率"] = display["缺失率"].map(lambda value: f"{value:.2%}")
    return display.to_string(index=False)
