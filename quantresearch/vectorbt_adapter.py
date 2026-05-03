from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np
import pandas as pd


def is_vectorbt_available() -> bool:
    return importlib.util.find_spec("vectorbt") is not None


def ensure_vectorbt() -> Any:
    if not is_vectorbt_available():
        raise RuntimeError(
            "当前环境未安装 vectorbt。"
            "请先安装 vectorbt，或者把回测引擎切回 pandas。"
        )
    import vectorbt as vbt

    return vbt


def run_long_only_signal_backtest(
    frame: pd.DataFrame,
    *,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    fee_rate: float,
    initial_capital: float = 1.0,
) -> pd.DataFrame:
    vbt = ensure_vectorbt()

    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce").ffill().bfill()
    df["ret"] = df["close"].pct_change(fill_method=None).fillna(0.0)

    raw_buy = pd.Series(buy_signal, index=df.index, dtype=bool).fillna(False)
    raw_sell = pd.Series(sell_signal, index=df.index, dtype=bool).fillna(False)
    entries = raw_buy.shift(1, fill_value=False)
    exits = raw_sell.shift(1, fill_value=False)

    portfolio = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        size=np.inf,
        init_cash=float(initial_capital),
        fees=float(fee_rate),
        direction="longonly",
        freq="1D",
    )

    total_value = _to_series(portfolio.value(), df.index)
    cash = _to_series(portfolio.cash(), df.index)
    shares = _to_series(portfolio.assets(), df.index)
    holding_value = _to_series(portfolio.asset_value(), df.index)

    df["signal"] = 0
    df.loc[raw_buy, "signal"] = 1
    df.loc[raw_sell, "signal"] = -1
    denominator = total_value.replace(0, pd.NA)
    df["position"] = (holding_value / denominator).fillna(0.0)
    df["trade"] = df["position"].diff().abs().fillna(df["position"].abs())
    df["strategy_nav"] = (total_value / float(initial_capital)).fillna(1.0)
    df["buy_hold_nav"] = (1 + df["ret"]).cumprod()
    df["strategy_ret"] = df["strategy_nav"].pct_change(fill_method=None).fillna(0.0)
    df["total_value"] = total_value
    df["holding_value"] = holding_value
    df["cash"] = cash
    df["shares"] = shares.fillna(0.0)
    df.attrs["backtest_engine"] = "vectorbt"
    return df


def _to_series(value: Any, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        series = value.copy()
        series.index = index
        return pd.to_numeric(series, errors="coerce")
    if isinstance(value, pd.DataFrame):
        if value.shape[1] != 1:
            raise ValueError("vectorbt 返回了多列结果，当前仅支持单标的单策略回测。")
        series = value.iloc[:, 0].copy()
        series.index = index
        return pd.to_numeric(series, errors="coerce")
    return pd.Series(value, index=index, dtype="float64")
