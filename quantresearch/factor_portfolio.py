"""因子投资组合回测 —— 把单因子/合成因子的排序能力变成实际组合收益。

核心逻辑：每周/月按因子值排序，选头部 N 只等权持有，计算组合收益。
同时给出等权全市场基准作为对比。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from qlib.data import D

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH
from .qlib_tools import prepare_qlib_universe


@dataclass(frozen=True)
class FactorPortfolioResult:
    factor_name: str
    portfolio_returns: pd.DataFrame       # 每期组合收益
    benchmark_returns: pd.Series          # 每期基准收益
    holdings: list[list[str]]            # 每期持仓标的列表
    turnover_series: pd.Series           # 每期换手率
    metrics: dict[str, Any]              # 绩效指标汇总


def backtest_factor_portfolio(
    *,
    universe: list[str],
    start: str,
    end: str,
    factor_name: str,
    expression: str,
    top_n: int = 30,
    direction: str = "long",      # "long" | "short" | "long_short"
    rebalance: str = "weekly",
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    auto_prepare: bool = True,
) -> FactorPortfolioResult:
    """按因子值构建投资组合并回测。

    direction 说明:
      - "long":   做多头部 top_n 只（因子值最大的 N 只）
      - "short":  做多尾部 top_n 只（因子值最小的 N 只），适合负 IC 因子
      - "long_short": 多头 top_n + 空头 bottom_n（多空组合）

    rebalance: "daily" | "weekly" | "monthly"

    返回 FactorPortfolioResult，包含组合收益、基准收益、持仓历史、换手率、绩效指标。
    """
    if top_n < 1:
        raise ValueError("top_n 至少为 1。")
    if direction not in ("long", "short", "long_short"):
        raise ValueError("direction 仅支持 long / short / long_short。")

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
    )

    # 拉取因子值 + 收盘价
    frame = D.features(universe, [expression, "$close"], start_time=start, end_time=end)
    if frame.empty:
        raise ValueError("没有读取到因子数据。")

    data = _prepare_portfolio_data(frame, expression)
    if data.empty:
        raise ValueError("因子数据整理后为空。")

    # 按调仓频率分组
    periods = _build_rebalance_periods(data, rebalance)
    if not periods:
        raise ValueError("调仓期列表为空，请扩大时间区间。")

    # 逐期选股并计算收益
    portfolio_rets, bmk_rets, holdings, turnover = _run_portfolio(
        data=data,
        periods=periods,
        top_n=top_n,
        direction=direction,
    )

    # 绩效指标
    metrics = _compute_portfolio_metrics(portfolio_rets, bmk_rets)

    # 持仓格式化
    formatted_holdings = _format_holdings(holdings)

    return FactorPortfolioResult(
        factor_name=factor_name,
        portfolio_returns=portfolio_rets,
        benchmark_returns=bmk_rets,
        holdings=formatted_holdings,
        turnover_series=turnover,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _prepare_portfolio_data(frame: pd.DataFrame, expression: str) -> pd.DataFrame:
    data = frame.reset_index().rename(columns={
        "datetime": "trade_date",
        "instrument": "instrument",
        expression: "factor_value",
        "$close": "close",
    })
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data["factor_value"] = pd.to_numeric(data["factor_value"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["factor_value", "close"])
    data = data.sort_values(["instrument", "trade_date"]).reset_index(drop=True)
    if data.empty:
        return pd.DataFrame()
    # 日收益率（用于组合收益拼接）
    data["ret"] = data.groupby("instrument")["close"].pct_change(fill_method=None)
    return data.dropna(subset=["ret"])


def _build_rebalance_periods(data: pd.DataFrame, rebalance: str) -> list[pd.Timestamp]:
    all_dates = sorted(data["trade_date"].unique())
    if not all_dates:
        return []
    if rebalance == "daily":
        return all_dates
    if rebalance == "weekly":
        offset = pd.offsets.Week(weekday=4)  # 周五
    else:
        offset = pd.offsets.MonthEnd()

    # 取每个周期最后一个交易日
    date_series = pd.Series(all_dates)
    periods = date_series.groupby(
        pd.DatetimeIndex(all_dates).to_period("W-FRI" if rebalance == "weekly" else "M")
    ).last().tolist()
    return [pd.Timestamp(d) for d in periods]


def _run_portfolio(
    data: pd.DataFrame,
    periods: list[pd.Timestamp],
    top_n: int,
    direction: str,
) -> tuple[pd.DataFrame, pd.Series, list[dict], pd.Series]:
    """逐期选股、计算组合收益。"""
    port_rets: list[dict] = []
    bmk_rets: list[float] = []
    holdings_log: list[dict] = []
    turnovers: list[float] = []
    prev_holdings: set[str] = set()

    for i, rebalance_date in enumerate(periods):
        # 找到当前调仓日的因子快照
        snapshot = data[data["trade_date"] == rebalance_date].copy()
        if snapshot.empty:
            continue

        # 确定下一调仓日（用于计算持有期收益）
        next_idx = i + 1
        if next_idx >= len(periods):
            break
        next_date = periods[next_idx]

        # 持有期：当前调仓日（不含）到下一调仓日（含）
        period_data = data[
            (data["trade_date"] > rebalance_date) & (data["trade_date"] <= next_date)
        ]

        # ---- 选股 ----
        valid = snapshot.dropna(subset=["factor_value"])
        if len(valid) < top_n:
            continue

        n_select = min(top_n, len(valid))
        if direction == "short":
            selected = valid.nsmallest(n_select, "factor_value")
        else:
            # long 和 long_short 的多头部分都选最大的
            selected = valid.nlargest(n_select, "factor_value")

        selected_symbols = set(selected["instrument"].tolist())

        # ---- 组合收益：等权平均 ----
        period_port = period_data[period_data["instrument"].isin(selected_symbols)]
        if period_port.empty:
            continue
        # 每日先算股票平均收益，再日度复利
        daily_port = period_port.groupby("trade_date")["ret"].mean()
        for d, r in daily_port.items():
            port_rets.append({"trade_date": d, "ret": float(r)})

        # ---- 基准收益：全市场等权 ----
        daily_bmk = period_data.groupby("trade_date")["ret"].mean()
        for d, r in daily_bmk.items():
            bmk_rets.append(float(r))

        # ---- 持仓记录 ----
        holdings_log.append({
            "rebalance_date": rebalance_date.strftime("%Y-%m-%d"),
            "count": len(selected_symbols),
            "symbols": sorted(selected_symbols),
        })

        # ---- 换手率 ----
        if prev_holdings:
            changed = len(selected_symbols - prev_holdings) + len(prev_holdings - selected_symbols)
            turnover = changed / (2 * len(selected_symbols)) if selected_symbols else 0.0
        else:
            turnover = 1.0
        turnovers.append(float(turnover))
        prev_holdings = selected_symbols

    port_df = pd.DataFrame(port_rets)
    bmk_series = pd.Series(bmk_rets, name="benchmark")
    turnover_series = pd.Series(turnovers, name="turnover")
    return port_df, bmk_series, holdings_log, turnover_series


def _compute_portfolio_metrics(
    port_rets: pd.DataFrame,
    bmk_rets: pd.Series,
) -> dict[str, Any]:
    if port_rets.empty:
        return {"error": "无有效收益数据"}

    port = port_rets["ret"]
    # 对齐基准（可能长度不同）
    common_len = min(len(port), len(bmk_rets))
    port_aligned = port.iloc[:common_len]
    bmk_aligned = bmk_rets.iloc[:common_len]

    # 累计净值
    port_nav = (1 + port_aligned).cumprod()
    bmk_nav = (1 + bmk_aligned).cumprod()

    # 年化收益
    n_days = len(port_aligned)
    years = n_days / 252
    port_ann = float(port_nav.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    bmk_ann = float(bmk_nav.iloc[-1] ** (1 / years) - 1) if years > 0 else 0.0
    excess_ann = port_ann - bmk_ann

    # 年化波动
    port_vol = float(port_aligned.std() * np.sqrt(252))
    bmk_vol = float(bmk_aligned.std() * np.sqrt(252))

    # 夏普
    port_sharpe = float(port_ann / port_vol) if port_vol > 0 else 0.0
    bmk_sharpe = float(bmk_ann / bmk_vol) if bmk_vol > 0 else 0.0
    info_ratio = float(excess_ann / (port_aligned - bmk_aligned).std() * np.sqrt(252)) \
        if (port_aligned - bmk_aligned).std() > 0 else 0.0

    # 最大回撤
    port_dd = float((port_nav / port_nav.cummax() - 1).min())
    bmk_dd = float((bmk_nav / bmk_nav.cummax() - 1).min())

    # 胜率（日度超额 > 0 的比例）
    daily_excess = port_aligned.values - bmk_aligned.values
    win_rate = float((daily_excess > 0).mean())

    return {
        "start": str(port_aligned.index[0] if hasattr(port_aligned, 'index') else port_rets.index[0]),
        "end": str(port_aligned.index[-1] if hasattr(port_aligned, 'index') else port_rets.index[-1]),
        "n_days": n_days,
        "portfolio_annual_return": port_ann,
        "benchmark_annual_return": bmk_ann,
        "excess_annual_return": excess_ann,
        "portfolio_annual_volatility": port_vol,
        "benchmark_annual_volatility": bmk_vol,
        "portfolio_sharpe": port_sharpe,
        "benchmark_sharpe": bmk_sharpe,
        "information_ratio": info_ratio,
        "portfolio_max_drawdown": port_dd,
        "benchmark_max_drawdown": bmk_dd,
        "daily_win_rate": win_rate,
    }


def _format_holdings(holdings: list[dict]) -> list[list[str]]:
    return [h["symbols"] for h in holdings]


def summarize_portfolio(result: FactorPortfolioResult) -> str:
    """生成组合回测中文摘要。"""
    m = result.metrics
    if "error" in m:
        return f"回测失败：{m['error']}"

    lines = [
        f"=== 因子组合回测：{result.factor_name} ===",
        "",
        f"回测区间：{m.get('start', '?')} ~ {m.get('end', '?')}（{m.get('n_days', 0)} 个交易日）",
        "",
        "           组合      基准      超额",
        f"年化收益  {m['portfolio_annual_return']:>8.2%}  {m['benchmark_annual_return']:>8.2%}  {m['excess_annual_return']:>8.2%}",
        f"年化波动  {m['portfolio_annual_volatility']:>8.2%}  {m['benchmark_annual_volatility']:>8.2%}",
        f"夏普比率  {m['portfolio_sharpe']:>8.2f}  {m['benchmark_sharpe']:>8.2f}",
        f"最大回撤  {m['portfolio_max_drawdown']:>8.2%}  {m['benchmark_max_drawdown']:>8.2%}",
        f"信息比率  {m['information_ratio']:>8.2f}",
        f"日胜率    {m['daily_win_rate']:>8.2%}",
        "",
        f"平均换手率：{result.turnover_series.mean():.1%}",
    ]
    if result.holdings:
        recent = result.holdings[-1]
        lines.extend([
            "",
            f"最新持仓（{len(recent)} 只）：",
            ", ".join(recent[:10]) + ("..." if len(recent) > 10 else ""),
        ])
    return "\n".join(lines)
