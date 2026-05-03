import pandas as pd


TRADING_DAYS = 252

METRIC_LABELS_CN = {
    "annual_return": "年化收益",
    "annual_volatility": "年化波动",
    "sharpe_ratio": "夏普比率",
    "max_drawdown": "最大回撤",
}


def calc_returns(close: pd.Series) -> pd.Series:
    close = close.dropna()
    if close.empty:
        raise ValueError("close 序列为空，无法计算收益率")
    return close.pct_change()


def calc_cum_return(close: pd.Series) -> pd.Series:
    close = close.dropna()
    if close.empty:
        raise ValueError("close 序列为空，无法计算累计收益")
    return close / close.iloc[0] - 1


def calc_max_drawdown(close: pd.Series):
    close = close.dropna()
    if close.empty:
        raise ValueError("close 序列为空，无法计算最大回撤")
    net_value = close / close.iloc[0]
    running_max = net_value.cummax()
    drawdown = net_value / running_max - 1
    return drawdown.min(), drawdown


def calc_annual_return(close: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    close = close.dropna()
    if close.empty:
        raise ValueError("close 序列为空，无法计算年化收益")
    total_return = close.iloc[-1] / close.iloc[0] - 1
    years = len(close) / periods_per_year
    return (1 + total_return) ** (1 / years) - 1


def calc_annual_volatility(close: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    returns = calc_returns(close).dropna()
    if returns.empty:
        raise ValueError("收益率序列为空，无法计算年化波动率")
    return returns.std() * periods_per_year**0.5


def calc_sharpe_ratio(close: pd.Series, risk_free_rate: float = 0, periods_per_year: int = TRADING_DAYS) -> float:
    returns = calc_returns(close).dropna()
    if returns.empty:
        raise ValueError("收益率序列为空，无法计算夏普比率")
    excess_returns = returns - risk_free_rate / periods_per_year
    return excess_returns.mean() / excess_returns.std() * periods_per_year**0.5


def calc_performance_metrics(
    close: pd.Series, risk_free_rate: float = 0, periods_per_year: int = TRADING_DAYS
) -> dict[str, float]:
    max_drawdown, _ = calc_max_drawdown(close)
    return {
        "annual_return": calc_annual_return(close, periods_per_year),
        "annual_volatility": calc_annual_volatility(close, periods_per_year),
        "sharpe_ratio": calc_sharpe_ratio(close, risk_free_rate, periods_per_year),
        "max_drawdown": max_drawdown,
    }


def format_metrics(metrics: pd.DataFrame, chinese: bool = True) -> pd.DataFrame:
    display = metrics.copy().astype(object)
    for row in ("annual_return", "annual_volatility", "max_drawdown"):
        if row in display.index:
            display.loc[row] = display.loc[row].map(lambda value: f"{value:.2%}")
    if "sharpe_ratio" in display.index:
        display.loc["sharpe_ratio"] = display.loc["sharpe_ratio"].map(lambda value: f"{value:.2f}")
    if chinese:
        display = display.rename(index=METRIC_LABELS_CN)
    return display
