from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from qlib.data import D

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, REPORTS_DIR
from .labels import format_display_symbol
from .metrics import calc_performance_metrics, format_metrics
from .rotation import init_qlib, prepare_rotation_dataset
from .vectorbt_adapter import is_vectorbt_available, run_long_only_signal_backtest as run_vectorbt_backtest


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    label: str


STRATEGY_REGISTRY: dict[str, StrategyDefinition] = {
    "kdj": StrategyDefinition(key="kdj", label="KDJ"),
    "bollinger": StrategyDefinition(key="bollinger", label="布林线"),
    "ma_cross": StrategyDefinition(key="ma_cross", label="双均线"),
    "macd": StrategyDefinition(key="macd", label="MACD"),
    "rsi": StrategyDefinition(key="rsi", label="RSI"),
    "dca": StrategyDefinition(key="dca", label="定投"),
}

BUY_HOLD_LABEL = "买入持有"
BACKTEST_ENGINES = ("auto", "pandas", "vectorbt")
VECTORBT_STRATEGIES = {"kdj", "bollinger", "ma_cross", "macd", "rsi"}


def build_qlib_symbol(symbol: str, market: str) -> str:
    return f"{market.upper()}_{symbol.upper()}"


def list_supported_strategies() -> list[str]:
    return list(STRATEGY_REGISTRY.keys())


def resolve_backtest_engine(strategy: str, requested_engine: str = "auto") -> str:
    engine = str(requested_engine or "auto").strip().lower()
    if engine not in BACKTEST_ENGINES:
        raise ValueError(f"不支持的回测引擎：{requested_engine}")
    if strategy == "dca":
        return "pandas"
    if engine == "pandas":
        return "pandas"
    if engine == "vectorbt":
        if not is_vectorbt_available():
            raise RuntimeError("当前环境未安装 vectorbt，请先安装后再使用 --engine vectorbt。")
        return "vectorbt"
    if strategy in VECTORBT_STRATEGIES and is_vectorbt_available():
        return "vectorbt"
    return "pandas"


def load_qlib_ohlcv(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
) -> pd.DataFrame:
    instrument = build_qlib_symbol(symbol, market)
    if auto_prepare:
        prepare_rotation_dataset(
            [instrument],
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
    frame = D.features(
        [instrument],
        ["$open", "$high", "$low", "$close", "$volume", "$factor"],
        start_time=start,
        end_time=end,
    )
    if frame.empty:
        return pd.DataFrame(
            columns=["trade_date", "open", "high", "low", "close", "volume", "factor", "adj_close"]
        )
    data = frame.reset_index().rename(
        columns={
            "datetime": "trade_date",
            "$open": "open",
            "$high": "high",
            "$low": "low",
            "$close": "close",
            "$volume": "volume",
            "$factor": "factor",
        }
    )
    data["trade_date"] = pd.to_datetime(data["trade_date"]).dt.strftime("%Y-%m-%d")
    data = data.dropna(subset=["close"]).copy()
    for column in ("open", "high", "low"):
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(data["close"])
    data["volume"] = pd.to_numeric(data["volume"], errors="coerce").fillna(0.0)
    data["factor"] = pd.to_numeric(data["factor"], errors="coerce").fillna(1.0)
    data["adj_close"] = data["close"] * data["factor"].fillna(1.0)
    return data[["trade_date", "open", "high", "low", "close", "volume", "factor", "adj_close"]].copy()


def calculate_kdj(
    frame: pd.DataFrame,
    n: int = 9,
    k_smooth: float = 1 / 3,
    d_smooth: float = 1 / 3,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    low_n = df["low"].rolling(n, min_periods=n).min()
    high_n = df["high"].rolling(n, min_periods=n).max()
    denominator = (high_n - low_n).replace(0, pd.NA)
    df["rsv"] = ((df["close"] - low_n) / denominator * 100).fillna(50.0)

    k_values = []
    d_values = []
    prev_k = 50.0
    prev_d = 50.0
    for rsv in df["rsv"]:
        k = (1 - k_smooth) * prev_k + k_smooth * float(rsv)
        d = (1 - d_smooth) * prev_d + d_smooth * k
        k_values.append(k)
        d_values.append(d)
        prev_k = k
        prev_d = d
    df["k"] = k_values
    df["d"] = d_values
    df["j"] = 3 * df["k"] - 2 * df["d"]
    return df


def calculate_bollinger_bands(
    frame: pd.DataFrame,
    window: int = 20,
    std_multiplier: float = 2.0,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    rolling = df["close"].rolling(window=window, min_periods=window)
    df["middle_band"] = rolling.mean()
    df["band_std"] = rolling.std(ddof=0)
    df["upper_band"] = df["middle_band"] + std_multiplier * df["band_std"]
    df["lower_band"] = df["middle_band"] - std_multiplier * df["band_std"]
    return df


def calculate_moving_average_signals(
    frame: pd.DataFrame,
    short_window: int = 10,
    long_window: int = 30,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["ma_short"] = df["close"].rolling(window=short_window, min_periods=short_window).mean()
    df["ma_long"] = df["close"].rolling(window=long_window, min_periods=long_window).mean()
    return df


def calculate_macd(
    frame: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()
    df["macd_line"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd_line"].ewm(span=signal_period, adjust=False).mean()
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]
    return df


def calculate_rsi(
    frame: pd.DataFrame,
    period: int = 14,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50.0)
    return df


def build_dca_invest_signal(
    frame: pd.DataFrame,
    *,
    frequency: str = "monthly",
    weekly_day: int = 0,
    monthly_day: int = 1,
) -> pd.Series:
    dates = pd.to_datetime(frame["trade_date"])
    signal = pd.Series(False, index=frame.index, dtype=bool)

    if frequency == "daily":
        return pd.Series(True, index=frame.index, dtype=bool)

    if frequency == "weekly":
        groups = dates.dt.strftime("%G-%V")
        weekday = int(weekly_day)
        for _, index in pd.Series(frame.index, index=frame.index).groupby(groups):
            rows = frame.loc[index.values]
            row_dates = dates.loc[index.values]
            candidates = rows.loc[row_dates.dt.weekday >= weekday]
            selected_idx = candidates.index[0] if not candidates.empty else rows.index[-1]
            signal.loc[selected_idx] = True
        return signal

    if frequency == "monthly":
        groups = dates.dt.to_period("M")
    elif frequency == "quarterly":
        groups = dates.dt.to_period("Q")
    else:
        raise ValueError(f"不支持的定投频率：{frequency}")

    target_day = int(monthly_day)
    for _, index in pd.Series(frame.index, index=frame.index).groupby(groups):
        rows = frame.loc[index.values]
        row_dates = dates.loc[index.values]
        candidates = rows.loc[row_dates.dt.day >= target_day]
        selected_idx = candidates.index[0] if not candidates.empty else rows.index[-1]
        signal.loc[selected_idx] = True
    return signal


def estimate_dca_total_budget(
    frame: pd.DataFrame,
    *,
    amount_per_buy: float = 1000.0,
    frequency: str = "monthly",
    weekly_day: int = 0,
    monthly_day: int = 1,
) -> float:
    invest_signal = build_dca_invest_signal(
        frame,
        frequency=frequency,
        weekly_day=weekly_day,
        monthly_day=monthly_day,
    )
    return float(invest_signal.sum()) * float(amount_per_buy)


def run_kdj_backtest(
    frame: pd.DataFrame,
    *,
    n: int = 9,
    fee_rate: float = 0.0005,
    signal_mode: str = "extreme_cross",
    oversold: float = 20,
    overbought: float = 80,
    initial_capital: float = 1.0,
    engine: str = "auto",
) -> pd.DataFrame:
    df = calculate_kdj(frame, n=n)
    prev_k = df["k"].shift(1)
    prev_d = df["d"].shift(1)

    golden_cross = (prev_k <= prev_d) & (df["k"] > df["d"])
    death_cross = (prev_k >= prev_d) & (df["k"] < df["d"])

    if signal_mode == "cross":
        buy_signal = golden_cross
        sell_signal = death_cross
    else:
        buy_signal = golden_cross & (df["k"] <= oversold) & (df["d"] <= oversold)
        sell_signal = death_cross & (df["k"] >= overbought) & (df["d"] >= overbought)

    return _apply_long_only_signals(
        df,
        buy_signal=buy_signal.fillna(False),
        sell_signal=sell_signal.fillna(False),
        fee_rate=fee_rate,
        initial_capital=initial_capital,
        engine=engine,
        strategy_key="kdj",
    )


def run_bollinger_backtest(
    frame: pd.DataFrame,
    *,
    window: int = 20,
    std_multiplier: float = 2.0,
    fee_rate: float = 0.0005,
    signal_mode: str = "reversion",
    initial_capital: float = 1.0,
    engine: str = "auto",
) -> pd.DataFrame:
    df = calculate_bollinger_bands(frame, window=window, std_multiplier=std_multiplier)
    prev_close = df["close"].shift(1)
    prev_middle = df["middle_band"].shift(1)
    prev_upper = df["upper_band"].shift(1)
    prev_lower = df["lower_band"].shift(1)

    if signal_mode == "breakout":
        buy_signal = (prev_close <= prev_upper) & (df["close"] > df["upper_band"])
        sell_signal = (prev_close >= prev_middle) & (df["close"] < df["middle_band"])
    else:
        buy_signal = (prev_close < prev_lower) & (df["close"] >= df["lower_band"])
        sell_signal = (prev_close <= prev_middle) & (df["close"] > df["middle_band"])

    return _apply_long_only_signals(
        df,
        buy_signal=buy_signal.fillna(False),
        sell_signal=sell_signal.fillna(False),
        fee_rate=fee_rate,
        initial_capital=initial_capital,
        engine=engine,
        strategy_key="bollinger",
    )


def run_ma_cross_backtest(
    frame: pd.DataFrame,
    *,
    short_window: int = 10,
    long_window: int = 30,
    fee_rate: float = 0.0005,
    initial_capital: float = 1.0,
    engine: str = "auto",
) -> pd.DataFrame:
    df = calculate_moving_average_signals(frame, short_window=short_window, long_window=long_window)
    prev_short = df["ma_short"].shift(1)
    prev_long = df["ma_long"].shift(1)
    buy_signal = (prev_short <= prev_long) & (df["ma_short"] > df["ma_long"])
    sell_signal = (prev_short >= prev_long) & (df["ma_short"] < df["ma_long"])
    return _apply_long_only_signals(
        df,
        buy_signal=buy_signal.fillna(False),
        sell_signal=sell_signal.fillna(False),
        fee_rate=fee_rate,
        initial_capital=initial_capital,
        engine=engine,
        strategy_key="ma_cross",
    )


def run_macd_backtest(
    frame: pd.DataFrame,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    fee_rate: float = 0.0005,
    signal_mode: str = "cross",
    initial_capital: float = 1.0,
    engine: str = "auto",
) -> pd.DataFrame:
    df = calculate_macd(
        frame,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )
    prev_macd = df["macd_line"].shift(1)
    prev_signal = df["macd_signal"].shift(1)
    bullish_cross = (prev_macd <= prev_signal) & (df["macd_line"] > df["macd_signal"])
    bearish_cross = (prev_macd >= prev_signal) & (df["macd_line"] < df["macd_signal"])
    if signal_mode == "zero_confirm":
        buy_signal = bullish_cross & (df["macd_line"] > 0)
        sell_signal = bearish_cross & (df["macd_line"] < 0)
    else:
        buy_signal = bullish_cross
        sell_signal = bearish_cross
    return _apply_long_only_signals(
        df,
        buy_signal=buy_signal.fillna(False),
        sell_signal=sell_signal.fillna(False),
        fee_rate=fee_rate,
        initial_capital=initial_capital,
        engine=engine,
        strategy_key="macd",
    )


def run_rsi_backtest(
    frame: pd.DataFrame,
    *,
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    fee_rate: float = 0.0005,
    signal_mode: str = "reversion",
    initial_capital: float = 1.0,
    engine: str = "auto",
) -> pd.DataFrame:
    df = calculate_rsi(frame, period=period)
    prev_rsi = df["rsi"].shift(1)
    if signal_mode == "midline":
        buy_signal = (prev_rsi <= 50.0) & (df["rsi"] > 50.0)
        sell_signal = (prev_rsi >= 50.0) & (df["rsi"] < 50.0)
    else:
        buy_signal = (prev_rsi < oversold) & (df["rsi"] >= oversold)
        sell_signal = (prev_rsi > overbought) & (df["rsi"] <= overbought)
    return _apply_long_only_signals(
        df,
        buy_signal=buy_signal.fillna(False),
        sell_signal=sell_signal.fillna(False),
        fee_rate=fee_rate,
        initial_capital=initial_capital,
        engine=engine,
        strategy_key="rsi",
    )


def run_dca_backtest(
    frame: pd.DataFrame,
    *,
    amount_per_buy: float = 1000.0,
    frequency: str = "monthly",
    weekly_day: int = 0,
    monthly_day: int = 1,
    fee_rate: float = 0.0005,
) -> pd.DataFrame:
    df = frame.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce").ffill().bfill()
    df["ret"] = df["close"].pct_change(fill_method=None).fillna(0.0)

    invest_signal = build_dca_invest_signal(
        df,
        frequency=frequency,
        weekly_day=weekly_day,
        monthly_day=monthly_day,
    )
    total_budget = estimate_dca_total_budget(
        df,
        amount_per_buy=amount_per_buy,
        frequency=frequency,
        weekly_day=weekly_day,
        monthly_day=monthly_day,
    )
    remaining_cash = total_budget
    shares = 0.0
    total_cost = 0.0
    cumulative_invested = 0.0

    signals = []
    actual_invested = []
    invested_amounts = []
    cash_values = []
    share_values = []
    holding_values = []
    total_values = []
    position_weights = []
    avg_costs = []

    for should_invest, close_price in zip(invest_signal, df["close"]):
        invested = 0.0
        if should_invest and remaining_cash > 0 and pd.notna(close_price) and float(close_price) > 0:
            gross_amount = min(float(amount_per_buy), remaining_cash)
            net_amount = gross_amount * (1 - fee_rate)
            bought_shares = net_amount / float(close_price) if close_price else 0.0
            shares += bought_shares
            remaining_cash -= gross_amount
            cumulative_invested += gross_amount
            total_cost += gross_amount
            invested = gross_amount
            signals.append(1)
        else:
            signals.append(0)

        holding_value = shares * float(close_price)
        total_value = remaining_cash + holding_value
        avg_cost = total_cost / shares if shares > 0 else 0.0

        actual_invested.append(invested)
        invested_amounts.append(cumulative_invested)
        cash_values.append(remaining_cash)
        share_values.append(shares)
        holding_values.append(holding_value)
        total_values.append(total_value)
        position_weights.append(holding_value / total_value if total_value > 0 else 0.0)
        avg_costs.append(avg_cost)

    df["signal"] = signals
    df["invest_amount"] = actual_invested
    df["cumulative_invested"] = invested_amounts
    df["cash"] = cash_values
    df["shares"] = share_values
    df["holding_value"] = holding_values
    df["total_value"] = total_values
    df["avg_cost"] = avg_costs
    df["position"] = position_weights
    denominator = pd.Series(total_budget, index=df.index).replace(0, pd.NA)
    df["strategy_nav"] = (df["total_value"] / denominator).fillna(1.0)
    df["buy_hold_nav"] = (1 + df["ret"]).cumprod()
    df["trade"] = (df["invest_amount"] > 0).astype(float)
    df["strategy_ret"] = df["strategy_nav"].pct_change(fill_method=None).fillna(0.0)
    return df


def run_strategy_backtest(strategy: str, frame: pd.DataFrame, **params: Any) -> pd.DataFrame:
    engine = params.get("backtest_engine", "auto")
    if strategy == "kdj":
        return run_kdj_backtest(
            frame,
            n=params.get("kdj_n", 9),
            fee_rate=params.get("fee_rate", 0.0005),
            signal_mode=params.get("kdj_signal_mode", "extreme_cross"),
            oversold=params.get("oversold", 20.0),
            overbought=params.get("overbought", 80.0),
            initial_capital=params.get("initial_capital", 1.0),
            engine=engine,
        )
    if strategy == "bollinger":
        return run_bollinger_backtest(
            frame,
            window=params.get("boll_window", 20),
            std_multiplier=params.get("boll_std_multiplier", 2.0),
            fee_rate=params.get("fee_rate", 0.0005),
            signal_mode=params.get("boll_signal_mode", "reversion"),
            initial_capital=params.get("initial_capital", 1.0),
            engine=engine,
        )
    if strategy == "ma_cross":
        return run_ma_cross_backtest(
            frame,
            short_window=params.get("ma_short_window", 10),
            long_window=params.get("ma_long_window", 30),
            fee_rate=params.get("fee_rate", 0.0005),
            initial_capital=params.get("initial_capital", 1.0),
            engine=engine,
        )
    if strategy == "macd":
        return run_macd_backtest(
            frame,
            fast_period=params.get("macd_fast_period", 12),
            slow_period=params.get("macd_slow_period", 26),
            signal_period=params.get("macd_signal_period", 9),
            fee_rate=params.get("fee_rate", 0.0005),
            signal_mode=params.get("macd_signal_mode", "cross"),
            initial_capital=params.get("initial_capital", 1.0),
            engine=engine,
        )
    if strategy == "rsi":
        return run_rsi_backtest(
            frame,
            period=params.get("rsi_period", 14),
            oversold=params.get("rsi_oversold", 30.0),
            overbought=params.get("rsi_overbought", 70.0),
            fee_rate=params.get("fee_rate", 0.0005),
            signal_mode=params.get("rsi_signal_mode", "reversion"),
            initial_capital=params.get("initial_capital", 1.0),
            engine=engine,
        )
    if strategy == "dca":
        return run_dca_backtest(
            frame,
            amount_per_buy=params.get("dca_amount_per_buy", 1000.0),
            frequency=params.get("dca_frequency", "monthly"),
            weekly_day=params.get("dca_weekly_day", 0),
            monthly_day=params.get("dca_monthly_day", 1),
            fee_rate=params.get("fee_rate", 0.0005),
        )
    raise ValueError(f"不支持的策略：{strategy}")


def compare_strategies(
    frame: pd.DataFrame,
    strategies: list[str],
    *,
    risk_free_rate: float = 0.0,
    **params: Any,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    comparison_capital = params.get("initial_capital")
    if comparison_capital is None and "dca" in strategies:
        comparison_capital = estimate_dca_total_budget(
            frame,
            amount_per_buy=params.get("dca_amount_per_buy", 1000.0),
            frequency=params.get("dca_frequency", "monthly"),
            weekly_day=params.get("dca_weekly_day", 0),
            monthly_day=params.get("dca_monthly_day", 1),
        )
    comparison_capital = float(comparison_capital) if comparison_capital is not None else 1.0

    navs = {}
    details = {}
    for strategy in strategies:
        backtest = run_strategy_backtest(strategy, frame, initial_capital=comparison_capital, **params)
        label = STRATEGY_REGISTRY[strategy].label
        navs[label] = backtest["strategy_nav"]
        details[strategy] = backtest
    navs[BUY_HOLD_LABEL] = (1 + frame["close"].pct_change(fill_method=None).fillna(0.0)).cumprod()
    nav_frame = pd.DataFrame(navs)
    metrics = pd.DataFrame(
        {column: calc_performance_metrics(nav_frame[column], risk_free_rate=risk_free_rate) for column in nav_frame.columns}
    )
    return nav_frame, metrics, details


def summarize_strategy_backtest(
    backtest_df: pd.DataFrame,
    *,
    strategy: str,
    symbol: str,
    market: str,
    asset_type: str,
    risk_free_rate: float = 0.0,
    show_names: bool = True,
    strategy_text: str = "",
) -> str:
    display_symbol = format_display_symbol(symbol, market, asset_type=asset_type) if show_names else symbol.upper()
    strategy_label = STRATEGY_REGISTRY[strategy].label
    engine_label = (backtest_df.attrs.get("backtest_engine") or "pandas").upper()
    nav_frame = pd.DataFrame(
        {
            f"{strategy_label}策略": backtest_df["strategy_nav"],
            f"{display_symbol}买入持有": backtest_df["buy_hold_nav"],
        }
    )
    metrics = pd.DataFrame(
        {column: calc_performance_metrics(series, risk_free_rate=risk_free_rate) for column, series in nav_frame.items()}
    )
    latest_columns = ["trade_date", "close", "position", "strategy_nav", "buy_hold_nav"]
    for column in (
        "cash",
        "shares",
        "holding_value",
        "total_value",
        "avg_cost",
        "cumulative_invested",
        "k",
        "d",
        "j",
        "middle_band",
        "upper_band",
        "lower_band",
        "ma_short",
        "ma_long",
        "macd_line",
        "macd_signal",
        "macd_hist",
        "rsi",
    ):
        if column in backtest_df.columns:
            latest_columns.append(column)
    latest = backtest_df[latest_columns].tail(10)
    latest = _localize_backtest_columns(latest)
    trades = extract_trades(backtest_df)

    parts = [f"=== {strategy_label}回测：{display_symbol} ===", f"回测引擎={engine_label}"]
    if strategy_text:
        parts.extend([strategy_text, ""])
    parts.extend(
        [
            format_metrics(metrics).to_string(),
            "",
            "=== 最近数据 ===",
            latest.to_string(index=False),
        ]
    )
    if not trades.empty:
        parts.extend(["", "=== 最近交易 ===", trades.tail(12).to_string(index=False)])
    if {"cash", "shares", "holding_value", "total_value"}.issubset(backtest_df.columns):
        latest_row = _localize_backtest_columns(backtest_df.tail(1)).iloc[0]
        parts.extend(
            [
                "",
                "=== 最终仓位 ===",
                f"剩余现金：{latest_row['现金']:.2f}",
                f"持仓份额：{latest_row['持仓份额']:.6f}",
                f"持仓市值：{latest_row['持仓市值']:.2f}",
                f"总资产：{latest_row['总资产']:.2f}",
            ]
        )
    return "\n".join(parts)


def summarize_strategy_comparison(
    *,
    nav_frame: pd.DataFrame,
    metrics: pd.DataFrame,
    symbol: str,
    market: str,
    asset_type: str,
    strategies: list[str],
    show_names: bool = True,
) -> str:
    display_symbol = format_display_symbol(symbol, market, asset_type=asset_type) if show_names else symbol.upper()
    strategy_labels = ", ".join(STRATEGY_REGISTRY[item].label for item in strategies)
    parts = [
        f"=== 策略对比：{display_symbol} ===",
        f"策略={strategy_labels}",
        "",
        format_metrics(metrics).to_string(),
        "",
        "=== 最近净值 ===",
        nav_frame.tail(10).to_string(),
    ]
    return "\n".join(parts)


def build_strategy_report(
    *,
    nav_frame: pd.DataFrame,
    metrics: pd.DataFrame,
    details: dict[str, pd.DataFrame],
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    strategies: list[str],
    params: dict[str, Any],
    show_names: bool = True,
) -> str:
    display_symbol = format_display_symbol(symbol, market, asset_type=asset_type) if show_names else symbol.upper()
    strategy_text = "、".join(STRATEGY_REGISTRY[item].label for item in strategies)
    lines = [
        "# 技术策略对比报告",
        "",
        "## 摘要",
        "",
        f"- 标的：{display_symbol}",
        f"- 回测区间：`{start}` 至 `{end}`",
        f"- 数据来源：`qlib` 本地数据集",
        f"- 回测引擎：`{_detect_report_engine(details)}`",
        f"- 对比策略：{strategy_text}、买入持有",
        f"- 交易成本：`{params.get('fee_rate', 0.0005):.4%}`",
        "",
        "## 参数",
        "",
        _format_strategy_params(params),
        "",
        "## 绩效对比",
        "",
        format_metrics(metrics).to_markdown(),
        "",
        "## 最近净值",
        "",
        nav_frame.tail(10).to_markdown(),
    ]
    for strategy in strategies:
        trades = extract_trades(details[strategy])
        if trades.empty:
            continue
        lines.extend(
            [
                "",
                f"## 最近交易：{STRATEGY_REGISTRY[strategy].label}",
                "",
                trades.tail(12).to_markdown(index=False),
            ]
        )
    for strategy in strategies:
        detail = details[strategy]
        if {"cash", "shares", "holding_value", "total_value"}.issubset(detail.columns):
            latest_row = _localize_backtest_columns(detail.tail(1)).iloc[0]
            lines.extend(
                [
                    "",
                    f"## 最终仓位：{STRATEGY_REGISTRY[strategy].label}",
                    "",
                    f"- 剩余现金：`{latest_row['现金']:.2f}`",
                    f"- 持仓份额：`{latest_row['持仓份额']:.6f}`",
                    f"- 持仓市值：`{latest_row['持仓市值']:.2f}`",
                    f"- 总资产：`{latest_row['总资产']:.2f}`",
                ]
            )
    lines.extend(
        [
            "",
            "## 说明",
            "",
        "- 本报告中的行情字段通过 qlib `D.features` 从本地 `.bin` 数据集读取。",
        "- Qlib 负责统一读取本地 OHLCV 和因子数据；回测层支持 pandas / vectorbt 双引擎。",
        "- KDJ、布林线、双均线、MACD、RSI 等信号都在 qlib 返回的 OHLCV 序列上统一计算，并放入同一套多策略对比框架。",
            "- 当对比列表包含 `定投` 时，其余策略的初始本金会自动按同一区间内定投总投入金额对齐，方便做公平比较。",
            "- 交易表默认只展示真实成交；非定投策略采用前一交易日发出信号、下一交易日执行的展示方式，并显示成交后仓位。",
            "- 买入持有作为基准，不扣交易成本；策略净值会根据仓位变化扣除配置的交易成本。",
        ]
    )
    return "\n".join(lines)


def rank_strategies(
    metrics: pd.DataFrame,
    strategies: list[str],
    objective: str = "composite",
) -> pd.DataFrame:
    labels = [STRATEGY_REGISTRY[item].label for item in strategies]
    subset = metrics.loc[:, labels].copy()
    if subset.empty:
        return pd.DataFrame()

    annual_return = pd.to_numeric(subset.loc["annual_return"], errors="coerce")
    annual_volatility = pd.to_numeric(subset.loc["annual_volatility"], errors="coerce")
    sharpe_ratio = pd.to_numeric(subset.loc["sharpe_ratio"], errors="coerce")
    max_drawdown = pd.to_numeric(subset.loc["max_drawdown"], errors="coerce")

    score_frame = pd.DataFrame(index=labels)
    score_frame["年化收益排名"] = annual_return.rank(ascending=False, method="min", na_option="bottom")
    score_frame["夏普排名"] = sharpe_ratio.rank(ascending=False, method="min", na_option="bottom")
    score_frame["回撤排名"] = max_drawdown.rank(ascending=False, method="min", na_option="bottom")
    score_frame["波动排名"] = annual_volatility.rank(ascending=True, method="min", na_option="bottom")

    if objective == "annual_return":
        score_frame["综合评分"] = annual_return
    elif objective == "sharpe_ratio":
        score_frame["综合评分"] = sharpe_ratio
    elif objective == "max_drawdown":
        score_frame["综合评分"] = max_drawdown
    else:
        size = len(score_frame.index)
        return_points = size - score_frame["年化收益排名"] + 1
        sharpe_points = size - score_frame["夏普排名"] + 1
        drawdown_points = size - score_frame["回撤排名"] + 1
        vol_points = size - score_frame["波动排名"] + 1
        score_frame["综合评分"] = (
            0.35 * return_points
            + 0.35 * sharpe_points
            + 0.2 * drawdown_points
            + 0.1 * vol_points
        )

    score_frame["策略"] = score_frame.index
    score_frame["年化收益"] = annual_return.values
    score_frame["夏普比率"] = sharpe_ratio.values
    score_frame["最大回撤"] = max_drawdown.values
    score_frame["年化波动"] = annual_volatility.values
    score_frame = score_frame.sort_values(
        by="综合评分",
        ascending=False if objective != "max_drawdown" else False,
        na_position="last",
    )
    return score_frame


def summarize_best_strategy(
    *,
    nav_frame: pd.DataFrame,
    metrics: pd.DataFrame,
    ranking: pd.DataFrame,
    symbol: str,
    market: str,
    asset_type: str,
    objective: str,
    show_names: bool = True,
) -> str:
    display_symbol = format_display_symbol(symbol, market, asset_type=asset_type) if show_names else symbol.upper()
    if ranking.empty:
        return f"没有可用于评估的策略：{display_symbol}"
    best = ranking.iloc[0]
    parts = [
        f"=== 最优策略搜索：{display_symbol} ===",
        f"目标={_objective_label(objective)}",
        "",
        "=== 策略排名 ===",
        _format_ranking_table(ranking),
        "",
        "=== 最优结论 ===",
        (
            f"当前最优策略是 {best['策略']}，年化收益 {best['年化收益']:.2%}，"
            f"夏普比率 {best['夏普比率']:.2f}，最大回撤 {best['最大回撤']:.2%}。"
        ),
        "",
        "=== 最近净值 ===",
        nav_frame.tail(10).to_string(),
    ]
    return "\n".join(parts)


def build_strategy_search_report(
    *,
    nav_frame: pd.DataFrame,
    metrics: pd.DataFrame,
    ranking: pd.DataFrame,
    symbol: str,
    market: str,
    asset_type: str,
    start: str,
    end: str,
    objective: str,
    strategies: list[str],
    params: dict[str, Any],
    show_names: bool = True,
) -> str:
    display_symbol = format_display_symbol(symbol, market, asset_type=asset_type) if show_names else symbol.upper()
    strategy_text = "、".join(STRATEGY_REGISTRY[item].label for item in strategies)
    best_text = ranking.iloc[0]["策略"] if not ranking.empty else "无"
    lines = [
        "# 最优策略搜索报告",
        "",
        "## 摘要",
        "",
        f"- 标的：{display_symbol}",
        f"- 回测区间：`{start}` 至 `{end}`",
        f"- 候选策略：{strategy_text}",
        f"- 回测引擎：`{params.get('backtest_engine', 'auto')}`",
        f"- 评估目标：`{_objective_label(objective)}`",
        f"- 最优策略：`{best_text}`",
        "",
        "## 排名",
        "",
        _format_ranking_table(ranking, markdown=True),
        "",
        "## 绩效对比",
        "",
        format_metrics(metrics).to_markdown(),
        "",
        "## 最近净值",
        "",
        nav_frame.tail(10).to_markdown(),
        "",
        "## 参数",
        "",
        _format_strategy_params(params),
        "",
        "## 说明",
        "",
        "- 所有候选策略使用同一份 qlib OHLCV 数据。",
        "- `买入持有` 作为基准展示，但不参与最优策略排名。",
        "- 综合评分默认同时考虑收益、夏普、回撤和波动，用于给出更稳妥的整体结论。",
    ]
    return "\n".join(lines)


def save_strategy_report(markdown: str, output_path: Path | str) -> Path:
    path = Path(output_path)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def extract_trades(backtest_df: pd.DataFrame) -> pd.DataFrame:
    keep_columns = ["trade_date", "close", "position"]
    keep_columns.extend(
        [
            column
            for column in (
                "invest_amount",
                "cumulative_invested",
                "cash",
                "shares",
                "holding_value",
                "total_value",
                "avg_cost",
                "k",
                "d",
                "j",
                "middle_band",
                "upper_band",
                "lower_band",
                "ma_short",
                "ma_long",
                "macd_line",
                "macd_signal",
                "macd_hist",
                "rsi",
            )
            if column in backtest_df.columns
        ]
    )
    df = backtest_df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])

    if "invest_amount" in df.columns:
        trades = df.loc[df["invest_amount"] > 0, keep_columns].copy()
        if trades.empty:
            return trades
        trades["action"] = "买入"
        trades["execution_note"] = "当日成交"
        trades["executed_position"] = trades["position"]
        extra_columns = [column for column in keep_columns if column not in {"trade_date", "close", "position"}]
        output = trades[["trade_date", "action", "close", "executed_position", "execution_note", *extra_columns]].copy()
    else:
        executed_change = df["position"].diff().fillna(df["position"])
        trades = df.loc[executed_change != 0, keep_columns].copy()
        if trades.empty:
            return trades
        trades["action"] = executed_change.loc[trades.index].map(lambda value: "买入" if value > 0 else "卖出")
        trades["signal_date"] = df["trade_date"].shift(1).loc[trades.index]
        trades["execution_note"] = "前一交易日信号，次日执行"
        trades["executed_position"] = trades["position"]
        extra_columns = [column for column in keep_columns if column not in {"trade_date", "close", "position"}]
        output = trades[
            ["signal_date", "trade_date", "action", "close", "executed_position", "execution_note", *extra_columns]
        ].copy()

    if "signal_date" in output.columns:
        output["signal_date"] = pd.to_datetime(output["signal_date"]).dt.strftime("%Y-%m-%d")
    output["trade_date"] = pd.to_datetime(output["trade_date"]).dt.strftime("%Y-%m-%d")
    return _localize_backtest_columns(output)


def _format_strategy_params(params: dict[str, Any]) -> str:
    rows = [
        ("回测引擎", params.get("backtest_engine", "auto")),
        ("KDJ周期", params.get("kdj_n", 9)),
        ("KDJ信号模式", params.get("kdj_signal_mode", "extreme_cross")),
        ("KDJ超卖阈值", params.get("oversold", 20.0)),
        ("KDJ超买阈值", params.get("overbought", 80.0)),
        ("布林线窗口", params.get("boll_window", 20)),
        ("布林线标准差倍数", params.get("boll_std_multiplier", 2.0)),
        ("布林线信号模式", params.get("boll_signal_mode", "reversion")),
        ("短均线窗口", params.get("ma_short_window", 10)),
        ("长均线窗口", params.get("ma_long_window", 30)),
        ("MACD快线周期", params.get("macd_fast_period", 12)),
        ("MACD慢线周期", params.get("macd_slow_period", 26)),
        ("MACD信号周期", params.get("macd_signal_period", 9)),
        ("MACD信号模式", params.get("macd_signal_mode", "cross")),
        ("RSI周期", params.get("rsi_period", 14)),
        ("RSI超卖阈值", params.get("rsi_oversold", 30.0)),
        ("RSI超买阈值", params.get("rsi_overbought", 70.0)),
        ("RSI信号模式", params.get("rsi_signal_mode", "reversion")),
        ("定投单次金额", params.get("dca_amount_per_buy", 1000.0)),
        ("定投频率", params.get("dca_frequency", "monthly")),
        ("定投周几", params.get("dca_weekly_day", 0)),
        ("定投每月日期", params.get("dca_monthly_day", 1)),
    ]
    table = pd.DataFrame(rows, columns=["参数", "值"])
    return table.to_markdown(index=False)


def _objective_label(objective: str) -> str:
    mapping = {
        "composite": "综合评分",
        "sharpe_ratio": "夏普优先",
        "annual_return": "年化收益优先",
        "max_drawdown": "回撤优先",
    }
    return mapping.get(objective, objective)


def _format_ranking_table(frame: pd.DataFrame, markdown: bool = False) -> str:
    if frame.empty:
        return "没有排名数据。"
    display = frame.copy()
    for column in ("年化收益", "最大回撤", "年化波动"):
        display[column] = display[column].map(lambda value: f"{value:.2%}")
    display["夏普比率"] = display["夏普比率"].map(lambda value: f"{value:.2f}")
    display["综合评分"] = display["综合评分"].map(lambda value: f"{value:.4f}" if isinstance(value, float) else str(value))
    ordered = display[
        ["策略", "综合评分", "年化收益", "夏普比率", "最大回撤", "年化波动", "年化收益排名", "夏普排名", "回撤排名", "波动排名"]
    ]
    return ordered.to_markdown(index=False) if markdown else ordered.to_string(index=False)


def _localize_backtest_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.copy()
    if "trade_date" in renamed.columns:
        renamed["trade_date"] = pd.to_datetime(renamed["trade_date"]).dt.strftime("%Y-%m-%d")
    return renamed.rename(
        columns={
            "trade_date": "日期",
            "signal_date": "信号日期",
            "action": "操作",
            "close": "收盘价",
            "position": "仓位",
            "executed_position": "成交后仓位",
            "execution_note": "执行说明",
            "strategy_nav": "策略净值",
            "buy_hold_nav": "买入持有净值",
            "invest_amount": "本次投入",
            "cumulative_invested": "累计投入",
            "cash": "现金",
            "shares": "持仓份额",
            "holding_value": "持仓市值",
            "total_value": "总资产",
            "avg_cost": "平均成本",
            "k": "K",
            "d": "D",
            "j": "J",
            "middle_band": "中轨",
            "upper_band": "上轨",
            "lower_band": "下轨",
            "ma_short": "短均线",
            "ma_long": "长均线",
            "macd_line": "MACD线",
            "macd_signal": "信号线",
            "macd_hist": "MACD柱",
            "rsi": "RSI",
        }
    )


def _apply_long_only_signals(
    frame: pd.DataFrame,
    *,
    buy_signal: pd.Series,
    sell_signal: pd.Series,
    fee_rate: float,
    initial_capital: float = 1.0,
    engine: str = "auto",
    strategy_key: str = "generic",
) -> pd.DataFrame:
    resolved_engine = resolve_backtest_engine(strategy_key, engine)
    if resolved_engine == "vectorbt":
        return run_vectorbt_backtest(
            frame,
            buy_signal=buy_signal,
            sell_signal=sell_signal,
            fee_rate=fee_rate,
            initial_capital=initial_capital,
        )

    df = frame.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce").ffill().bfill()
    df["ret"] = df["close"].pct_change(fill_method=None).fillna(0.0)
    position = []
    current_position = 0.0
    for buy, sell in zip(buy_signal, sell_signal):
        if buy:
            current_position = 1.0
        elif sell:
            current_position = 0.0
        position.append(current_position)
    df["signal"] = 0
    df.loc[buy_signal, "signal"] = 1
    df.loc[sell_signal, "signal"] = -1
    df["position"] = pd.Series(position, index=df.index).shift(1).fillna(0.0)
    df["trade"] = df["position"].diff().abs().fillna(df["position"].abs())
    df["strategy_ret"] = df["position"] * df["ret"] - df["trade"] * fee_rate
    df["strategy_nav"] = (1 + df["strategy_ret"]).cumprod()
    df["buy_hold_nav"] = (1 + df["ret"]).cumprod()
    df["total_value"] = df["strategy_nav"] * float(initial_capital)
    df["holding_value"] = df["total_value"] * df["position"]
    df["cash"] = df["total_value"] - df["holding_value"]
    valid_close = df["close"].replace(0, pd.NA)
    df["shares"] = (df["holding_value"] / valid_close).fillna(0.0)
    df.attrs["backtest_engine"] = "pandas"
    return df


def _detect_report_engine(details: dict[str, pd.DataFrame]) -> str:
    engines = sorted({(detail.attrs.get("backtest_engine") or "pandas") for detail in details.values() if detail is not None})
    if not engines:
        return "pandas"
    return "/".join(engines)
