from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from qlib.data import D

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH
from .qlib_tools import prepare_qlib_universe


@dataclass(frozen=True)
class FactorAnalysisResult:
    factor_name: str
    expression: str
    quantiles: int
    forward_days: int
    rebalance: str
    preview: pd.DataFrame
    summary: dict[str, float | int | str | None]
    ic_series: pd.DataFrame
    quantile_returns: pd.DataFrame
    long_short_returns: pd.DataFrame
    distribution: pd.DataFrame
    # ---- 合成因子扩展字段 ----
    sub_factor_weights: dict[str, float] | None = None
    sub_factor_results: list[FactorAnalysisResult] | None = None


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    expression: str


# ---------------------------------------------------------------------------
# 单因子分析
# ---------------------------------------------------------------------------

def analyze_factor(
    *,
    universe: list[str],
    start: str,
    end: str,
    factor_name: str,
    expression: str,
    quantiles: int = 5,
    forward_days: int = 5,
    rebalance: str = "weekly",
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
    preview_rows: int = 20,
) -> FactorAnalysisResult:
    _validate_params(universe, factor_name, expression, quantiles, forward_days, rebalance)

    prepare_qlib_universe(
        universe,
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

    frame = D.features(universe, [expression, "$close"], start_time=start, end_time=end)
    if frame.empty:
        raise ValueError("没有读取到指定标的池在区间内的因子数据。")

    factor_data = _prepare_factor_data(frame, factor_name=factor_name, expression=expression,
                                       forward_days=forward_days, rebalance=rebalance)

    return _run_factor_analysis(
        factor_data=factor_data,
        factor_name=factor_name,
        expression=expression,
        quantiles=quantiles,
        forward_days=forward_days,
        rebalance=rebalance,
        preview_rows=preview_rows,
    )


# ---------------------------------------------------------------------------
# 因子合成
# ---------------------------------------------------------------------------

COMBINE_METHODS = ("equal", "icir")


def combine_factors(
    *,
    universe: list[str],
    start: str,
    end: str,
    factors: list[dict[str, str]],
    method: str = "equal",
    icir_train_start: str | None = None,
    icir_train_end: str | None = None,
    quantiles: int = 5,
    forward_days: int = 5,
    rebalance: str = "weekly",
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
    preview_rows: int = 20,
) -> FactorAnalysisResult:
    """将多个因子合成为一个复合因子并做完整分析。

    method:
      - "equal": 等权平均（默认）
      - "icir":  按训练期 ICIR 加权（仅保留 ICIR>0 的因子）

    icir_train_start / icir_train_end:
      训练期的起止日期。默认取 start~end 的前 1/3 作为训练期。
      训练期用于计算各子因子的 ICIR 作为权重，其余为评估期。
    """
    if method not in COMBINE_METHODS:
        raise ValueError(f"不支持的合成方法: {method}，可选: {COMBINE_METHODS}")
    if len(factors) < 2:
        raise ValueError("至少需要 2 个因子才能合成。")

    # 解析因子定义
    factor_defs = [FactorDefinition(name=f["name"], expression=f["expression"]) for f in factors]
    factor_names = [f.name for f in factor_defs]
    composite_name = f"合成({','.join(factor_names)})"
    # qlib 表达式用分号分隔，取加权和
    composite_expr = " + ".join(f"({f.expression})" for f in factor_defs)

    _validate_params(universe, composite_name, composite_expr, quantiles, forward_days, rebalance)

    prepare_qlib_universe(
        universe,
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

    # 一次性拉取所有因子 + close
    expressions = [f.expression for f in factor_defs] + ["$close"]
    frame = D.features(universe, expressions, start_time=start, end_time=end)
    if frame.empty:
        raise ValueError("没有读取到因子数据。")

    # 整理为宽表: columns = trade_date, instrument, close, factor1, factor2, ...
    panel = _build_factor_panel(frame, factor_defs, forward_days=forward_days, rebalance=rebalance)
    if panel.empty:
        raise ValueError("因子面板整理后为空，无法继续分析。")

    # 确定训练期
    if method == "icir":
        train_start = icir_train_start or start
        train_end = icir_train_end or _midpoint_date(start, end)
    else:
        train_start = train_end = None

    # 计算权重
    weights = _compute_factor_weights(panel, factor_names, method=method,
                                      train_start=train_start, train_end=train_end)

    # 截面 z-score 归一化
    normalized = _cross_sectional_zscore(panel, factor_names)

    # 合成
    composite_values = pd.Series(0.0, index=normalized.index)
    weight_detail: dict[str, float] = {}
    for name in factor_names:
        w = weights.get(name, 0.0)
        if w > 0:
            composite_values += normalized[name].fillna(0.0) * w
            weight_detail[name] = w

    factor_data = pd.DataFrame({
        "trade_date": panel["trade_date"],
        "instrument": panel["instrument"],
        "factor_value": composite_values.values,
        "forward_return": panel["forward_return"],
    })

    # 先跑子因子分析
    sub_results: list[FactorAnalysisResult] | None = None
    try:
        sub_results = [
            analyze_factor(
                universe=universe, start=start, end=end,
                factor_name=fd.name, expression=fd.expression,
                quantiles=quantiles, forward_days=forward_days,
                rebalance=rebalance, dataset_name=dataset_name,
                db_path=db_path, target_years=target_years,
                refresh_recent_days=refresh_recent_days,
                qlib_repo=qlib_repo, output_dir=output_dir,
                auto_prepare=False, force_refresh_qlib=False,
                preview_rows=preview_rows,
            )
            for fd in factor_defs
        ]
    except Exception:
        sub_results = None

    # 合成因子分析
    result = _run_factor_analysis(
        factor_data=factor_data,
        factor_name=composite_name,
        expression=composite_expr,
        quantiles=quantiles,
        forward_days=forward_days,
        rebalance=rebalance,
        preview_rows=preview_rows,
    )
    return FactorAnalysisResult(
        factor_name=result.factor_name,
        expression=result.expression,
        quantiles=result.quantiles,
        forward_days=result.forward_days,
        rebalance=result.rebalance,
        preview=result.preview,
        summary=result.summary,
        ic_series=result.ic_series,
        quantile_returns=result.quantile_returns,
        long_short_returns=result.long_short_returns,
        distribution=result.distribution,
        sub_factor_weights=weight_detail,
        sub_factor_results=sub_results,
    )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _validate_params(universe, factor_name, expression, quantiles, forward_days, rebalance):
    if not universe:
        raise ValueError("universe 不能为空。")
    if not factor_name.strip():
        raise ValueError("因子名称不能为空。")
    if not expression.strip():
        raise ValueError("qlib 表达式不能为空。")
    if quantiles < 2:
        raise ValueError("分层数至少为 2。")
    if forward_days < 1:
        raise ValueError("预测窗口至少为 1 日。")
    if rebalance not in {"daily", "weekly", "monthly"}:
        raise ValueError("调仓频率仅支持 daily / weekly / monthly。")


def _prepare_factor_data(
    frame: pd.DataFrame,
    *,
    factor_name: str,
    expression: str,
    forward_days: int,
    rebalance: str,
) -> pd.DataFrame:
    factor_data = (
        frame.reset_index()
        .rename(columns={
            "datetime": "trade_date",
            "instrument": "instrument",
            expression: "factor_value",
            "$close": "close",
        })
        .copy()
    )
    factor_data["trade_date"] = pd.to_datetime(factor_data["trade_date"])
    factor_data["factor_value"] = pd.to_numeric(factor_data["factor_value"], errors="coerce")
    factor_data["close"] = pd.to_numeric(factor_data["close"], errors="coerce")
    factor_data = factor_data.dropna(subset=["factor_value", "close"]).sort_values(["instrument", "trade_date"])
    if factor_data.empty:
        raise ValueError("因子表达式返回空值，无法继续分析。")

    factor_data["forward_return"] = (
        factor_data.groupby("instrument")["close"].shift(-forward_days) / factor_data["close"] - 1.0
    )
    factor_data = factor_data.dropna(subset=["forward_return"]).copy()
    factor_data = _apply_rebalance_filter(factor_data, rebalance)
    if factor_data.empty:
        raise ValueError("可用于评估的样本为空，请调整区间、标的池或预测窗口。")
    return factor_data


def _build_factor_panel(
    frame: pd.DataFrame,
    factor_defs: list[FactorDefinition],
    forward_days: int,
    rebalance: str,
) -> pd.DataFrame:
    """将 qlib 返回的因子数据整理为宽面板。"""
    df = frame.reset_index().rename(columns={
        "datetime": "trade_date",
        "instrument": "instrument",
        "$close": "close",
    })
    # 表达式列名映射
    for fd in factor_defs:
        if fd.expression in df.columns:
            df = df.rename(columns={fd.expression: fd.name})

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for name in [f.name for f in factor_defs]:
        if name in df.columns:
            df[name] = pd.to_numeric(df[name], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    factor_names = [f.name for f in factor_defs]
    keep_cols = ["trade_date", "instrument", "close"] + factor_names
    df = df.dropna(subset=factor_names + ["close"])[keep_cols].copy()
    df = df.sort_values(["instrument", "trade_date"])

    df["forward_return"] = (
        df.groupby("instrument")["close"].shift(-forward_days) / df["close"] - 1.0
    )
    df = df.dropna(subset=["forward_return"]).copy()
    df = _apply_rebalance_filter(df, rebalance)
    return df


def _cross_sectional_zscore(panel: pd.DataFrame, factor_names: list[str]) -> pd.DataFrame:
    """截面 z-score 归一化。每日期/每因子减去均值除以标准差。"""
    result = panel[["trade_date", "instrument"]].copy()
    for name in factor_names:
        if name not in panel.columns:
            result[name] = 0.0
            continue
        grouped = panel.groupby("trade_date")[name]
        mean_val = grouped.transform("mean")
        std_val = grouped.transform("std").replace(0, pd.NA)
        result[name] = ((panel[name] - mean_val) / std_val).fillna(0.0)
    return result


def _compute_factor_weights(
    panel: pd.DataFrame,
    factor_names: list[str],
    method: str,
    train_start: str | None,
    train_end: str | None,
) -> dict[str, float]:
    if method == "equal":
        w = 1.0 / len(factor_names)
        return {name: w for name in factor_names}

    # ICIR 加权
    if train_start is None or train_end is None:
        raise ValueError("ICIR 加权需要指定训练期。")
    train = panel[
        (panel["trade_date"] >= pd.Timestamp(train_start)) &
        (panel["trade_date"] <= pd.Timestamp(train_end))
    ]
    if train.empty:
        raise ValueError(f"训练期 {train_start}~{train_end} 无数据。")

    icirs: dict[str, float] = {}
    for name in factor_names:
        ics = []
        for _, group in train.groupby("trade_date"):
            valid = group[[name, "forward_return"]].dropna()
            if len(valid) < 10:
                continue
            ic = valid[name].corr(valid["forward_return"], method="pearson")
            if pd.notna(ic):
                ics.append(float(ic))
        if len(ics) < 5:
            icirs[name] = 0.0
            continue
        mean_ic = np.mean(ics)
        std_ic = np.std(ics, ddof=0)
        # 按周度实际样本数折算年化
        icirs[name] = mean_ic / std_ic * sqrt(52.0) if std_ic > 0 else 0.0

    # 仅保留正 ICIR
    positive = {k: max(v, 0.0) for k, v in icirs.items()}
    total = sum(positive.values())
    if total <= 0:
        # 全部为负则退化为等权
        w = 1.0 / len(factor_names)
        return {name: w for name in factor_names}
    return {k: v / total for k, v in positive.items()}


def _midpoint_date(start: str, end: str) -> str:
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    mid = s + (e - s) / 3  # 前 1/3
    return mid.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 公共分析管线（单因子和合成因子共用）
# ---------------------------------------------------------------------------

def _run_factor_analysis(
    *,
    factor_data: pd.DataFrame,
    factor_name: str,
    expression: str,
    quantiles: int,
    forward_days: int,
    rebalance: str,
    preview_rows: int,
) -> FactorAnalysisResult:
    preview = factor_data[["trade_date", "instrument", "factor_value", "forward_return"]].copy()
    preview["trade_date"] = preview["trade_date"].dt.strftime("%Y-%m-%d")
    preview = preview.rename(
        columns={
            "trade_date": "日期",
            "instrument": "标的",
            "factor_value": factor_name,
            "forward_return": f"{forward_days}日收益",
        }
    ).tail(preview_rows)

    ic_rows: list[dict] = []
    quantile_rows: list[dict] = []
    distribution_rows: list[dict] = []
    sample_sizes: list[int] = []

    for trade_date, group in factor_data.groupby("trade_date"):
        sample = group[["instrument", "factor_value", "forward_return"]].dropna().copy()
        if len(sample) < quantiles:
            continue

        sample_sizes.append(len(sample))
        factor_series = sample["factor_value"]
        return_series = sample["forward_return"]
        ic_value = factor_series.corr(return_series, method="pearson")
        rank_ic_value = factor_series.corr(return_series, method="spearman")

        distribution_rows.append(
            {
                "日期": trade_date.strftime("%Y-%m-%d"),
                "样本数": len(sample),
                "均值": float(factor_series.mean()),
                "标准差": float(factor_series.std(ddof=0)),
                "最小值": float(factor_series.min()),
                "中位数": float(factor_series.median()),
                "最大值": float(factor_series.max()),
            }
        )

        ic_rows.append(
            {
                "日期": trade_date.strftime("%Y-%m-%d"),
                "IC": float(ic_value) if pd.notna(ic_value) else None,
                "RankIC": float(rank_ic_value) if pd.notna(rank_ic_value) else None,
                "样本数": len(sample),
            }
        )

        ranked = sample["factor_value"].rank(method="first")
        sample["quantile"] = pd.qcut(ranked, q=quantiles, labels=False) + 1
        grouped = sample.groupby("quantile")["forward_return"].mean()
        row: dict[str, Any] = {"日期": trade_date.strftime("%Y-%m-%d")}
        for q in range(1, quantiles + 1):
            row[f"Q{q}"] = float(grouped.get(q, 0.0))
        row["多空"] = float(row[f"Q{quantiles}"] - row["Q1"])
        quantile_rows.append(row)

    if not ic_rows or not quantile_rows:
        raise ValueError("样本不足以完成分层或 IC 统计，请扩大标的池或时间区间。")

    ic_series = pd.DataFrame(ic_rows)
    quantile_returns = pd.DataFrame(quantile_rows)
    long_short = quantile_returns[["日期", "多空"]].copy()
    long_short["累计多空"] = (1 + long_short["多空"].fillna(0.0)).cumprod()

    mean_ic = pd.to_numeric(ic_series["IC"], errors="coerce").dropna()
    mean_rank_ic = pd.to_numeric(ic_series["RankIC"], errors="coerce").dropna()
    long_short_series = pd.to_numeric(long_short["多空"], errors="coerce").dropna()
    ic_std = float(mean_ic.std(ddof=0)) if not mean_ic.empty else 0.0
    rank_ic_std = float(mean_rank_ic.std(ddof=0)) if not mean_rank_ic.empty else 0.0
    periods_per_year = {"daily": 252, "weekly": 52, "monthly": 12}[rebalance]

    summary: dict[str, Any] = {
        "factor_name": factor_name,
        "expression": expression,
        "quantiles": quantiles,
        "forward_days": forward_days,
        "rebalance": rebalance,
        "date_count": int(len(ic_series)),
        "mean_sample_size": float(sum(sample_sizes) / len(sample_sizes)) if sample_sizes else 0.0,
        "mean_ic": float(mean_ic.mean()) if not mean_ic.empty else None,
        "mean_rank_ic": float(mean_rank_ic.mean()) if not mean_rank_ic.empty else None,
        "ic_ir": float(mean_ic.mean() / ic_std * sqrt(periods_per_year)) if ic_std else None,
        "rank_ic_ir": float(mean_rank_ic.mean() / rank_ic_std * sqrt(periods_per_year)) if rank_ic_std else None,
        "long_short_mean": float(long_short_series.mean()) if not long_short_series.empty else None,
        "long_short_cum_return": float(long_short["累计多空"].iloc[-1] - 1.0) if not long_short.empty else None,
    }

    distribution = pd.DataFrame(distribution_rows)
    return FactorAnalysisResult(
        factor_name=factor_name,
        expression=expression,
        quantiles=quantiles,
        forward_days=forward_days,
        rebalance=rebalance,
        preview=preview,
        summary=summary,
        ic_series=ic_series,
        quantile_returns=quantile_returns,
        long_short_returns=long_short,
        distribution=distribution,
    )


def _apply_rebalance_filter(frame: pd.DataFrame, rebalance: str) -> pd.DataFrame:
    if rebalance == "daily":
        return frame.copy()

    if rebalance == "weekly":
        periods = frame["trade_date"].dt.to_period("W-FRI")
    else:
        periods = frame["trade_date"].dt.to_period("M")

    filtered = frame.copy()
    filtered["_period"] = periods
    filtered = (
        filtered.sort_values(["instrument", "trade_date"])
        .groupby(["instrument", "_period"], as_index=False, group_keys=False)
        .tail(1)
        .drop(columns="_period")
    )
    return filtered.sort_values(["trade_date", "instrument"]).reset_index(drop=True)
