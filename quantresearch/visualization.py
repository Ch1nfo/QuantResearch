"""量化回测可视化 —— 基于 mplfinance 的 K 线图、买卖标记、净值对比。

依赖: mplfinance (pip install mplfinance)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import mplfinance as mpf
import numpy as np
import pandas as pd

from .labels import format_display_symbol

# 非交互式后端，适合脚本和 Agent 调用
matplotlib.use("Agg")

# 中文字体 —— 注册 macOS Arial Unicode 字体
import os as _os
from matplotlib import font_manager as _fm

_FONT_FILE = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
if _os.path.exists(_FONT_FILE):
    _fm.fontManager.addfont(_FONT_FILE)
    _FONT_NAME = _fm.FontProperties(fname=_FONT_FILE).get_name()
else:
    _FONT_NAME = "DejaVu Sans"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [_FONT_NAME, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "buy": "#00AA00",       # 绿色买入
    "sell": "#CC0000",      # 红色卖出
    "strategy": "#1f77b4",  # 策略净值蓝
    "benchmark": "#888888", # 基准灰
    "up": "#CC0000",        # A 股红涨
    "down": "#00AA00",      # A 股绿跌
    "volume_up": "#CC0000",
    "volume_down": "#009900",
}

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "charts"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 技术策略回测图：K 线 + 买卖标记 + 指标 + 净值
# ============================================================================

def plot_strategy_backtest(
    backtest_df: pd.DataFrame,
    *,
    symbol: str,
    market: str = "CN",
    strategy_label: str = "策略",
    save_path: Optional[Path | str] = None,
    show_indicators: bool = True,
    figsize: tuple[int, int] = (16, 10),
) -> Path:
    """绘制单策略回测图：K 线 + 买卖标记 + 技术指标 + 净值对比。

    backtest_df 必须包含列：
      trade_date, open, high, low, close, volume
      以及 signal (1=买, -1=卖), strategy_nav, buy_hold_nav

    返回保存路径。
    """
    df = _prepare_ohlcv(backtest_df)
    if df.empty:
        raise ValueError("回测数据为空，无法绘图。")

    display = format_display_symbol(symbol, market)

    # ---- 构建买卖标记 ----
    buy_signals = df["signal"] == 1
    sell_signals = df["signal"] == -1

    apds = []

    # ---- 成交量 ----
    volume_colors = [COLORS["volume_up"] if c >= o else COLORS["volume_down"]
                     for c, o in zip(df["close"], df["open"])]
    apds.append(mpf.make_addplot(df["volume"], type="bar", panel=1,
                                  color=volume_colors, ylabel="成交量"))

    # ---- 技术指标（如果有） ----
    indicator_panel = 2
    indicator_configs = [
        ("k", "K", COLORS["strategy"]),
        ("d", "D", "orange"),
        ("j", "J", "purple"),
        ("middle_band", "中轨", "orange"),
        ("upper_band", "上轨", COLORS["buy"]),
        ("lower_band", "下轨", COLORS["sell"]),
        ("ma_short", "短均", COLORS["strategy"]),
        ("ma_long", "长均", "orange"),
        ("macd_line", "DIF", COLORS["strategy"]),
        ("macd_signal", "DEA", "orange"),
        ("rsi", "RSI", COLORS["strategy"]),
    ]
    indicator_added = False
    for col, label, color in indicator_configs:
        if col in df.columns and df[col].dropna().any():
            clean_data = df[col].copy()
            if clean_data.isna().all():
                continue
            if not indicator_added:
                apds.append(mpf.make_addplot(
                    clean_data.fillna(0), panel=indicator_panel, color=color, ylabel=label, width=0.8))
            else:
                apds.append(mpf.make_addplot(
                    clean_data.fillna(0), panel=indicator_panel, color=color, width=0.8))
            indicator_added = True

    if indicator_added:
        indicator_panel += 1

    # ---- 净值对比 ----
    nav_panel = indicator_panel
    apds.append(mpf.make_addplot(
        df["strategy_nav"], panel=nav_panel, color=COLORS["strategy"],
        ylabel="净值", width=1.5))
    apds.append(mpf.make_addplot(
        df["buy_hold_nav"], panel=nav_panel, color=COLORS["benchmark"],
        width=1.0, linestyle="--"))

    # ---- macd 柱状图（如果有） ----
    has_macd = "macd_hist" in df.columns and df["macd_hist"].notna().any() and df["macd_hist"].dropna().any()
    if has_macd:
        macd_panel = nav_panel + 1
        macd_data = df["macd_hist"].fillna(0)
        macd_colors = [COLORS["volume_up"] if v >= 0 else COLORS["volume_down"]
                       for v in macd_data]
        apds.append(mpf.make_addplot(
            macd_data, type="bar", panel=macd_panel,
            color=macd_colors, ylabel="MACD柱"))
        panel_count = macd_panel + 1
    else:
        panel_count = nav_panel + 1
    mc = mpf.make_marketcolors(up=COLORS["up"], down=COLORS["down"],
                                edge="inherit", wick="inherit", volume="inherit")
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle="--",
                                rc={"font.family": "sans-serif",
                                    "font.sans-serif": [_FONT_NAME, "DejaVu Sans"],
                                    "axes.unicode_minus": False})

    fig, axes = mpf.plot(
        df, type="candle", style=style,
        addplot=apds,
        volume=False,  # 手动加在 panel 1
        figsize=figsize,
        title=f"{display} — {strategy_label}回测",
        ylabel="价格",
        returnfig=True,
        panel_ratios=_build_panel_ratios(panel_count),
        datetime_format="%Y-%m-%d",
        xrotation=30,
    )

    # ---- 手动图例 & B/S 标注 ----
    from matplotlib.lines import Line2D

    # 买卖点直接标 B / S 文字
    if buy_signals.any():
        buy_idx = df.index[buy_signals.values]
        for idx in buy_idx:
            pos = df.index.get_loc(idx)
            axes[0].annotate("B", xy=(pos, df["low"].iloc[pos]),
                             xytext=(0, -18), textcoords="offset points",
                             fontsize=9, fontweight="bold", color=COLORS["buy"],
                             ha="center", va="top")
    if sell_signals.any():
        sell_idx = df.index[sell_signals.values]
        for idx in sell_idx:
            pos = df.index.get_loc(idx)
            axes[0].annotate("S", xy=(pos, df["high"].iloc[pos]),
                             xytext=(0, 8), textcoords="offset points",
                             fontsize=9, fontweight="bold", color=COLORS["sell"],
                             ha="center", va="bottom")

    # 净值面板：策略 vs 基准图例
    if nav_panel < len(axes):
        nav_ax = axes[nav_panel]
        nav_legend = [
            Line2D([0], [0], color=COLORS["strategy"], linewidth=1.5,
                   label=f"{strategy_label}净值"),
            Line2D([0], [0], color=COLORS["benchmark"], linewidth=1.0, linestyle="--",
                   label="买入持有"),
        ]
        nav_ax.legend(handles=nav_legend, loc="upper left", fontsize=8,
                      framealpha=0.9, borderpad=0.5)

    # 保存
    save_path = Path(save_path) if save_path else REPORTS_DIR / f"{symbol}_{strategy_label}_backtest.png"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


# ============================================================================
# 多策略对比图：净值曲线叠加
# ============================================================================

def plot_strategy_comparison(
    nav_frame: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    symbol: str,
    market: str = "CN",
    save_path: Optional[Path | str] = None,
    figsize: tuple[int, int] = (14, 7),
) -> Path:
    """绘制多策略净值对比图。

    nav_frame: 每列一个策略的净值序列（包含买入持有基准列）
    metrics: 各策略的绩效指标 DataFrame
    """
    display = format_display_symbol(symbol, market)
    dates = pd.to_datetime(nav_frame.index) if isinstance(nav_frame.index, pd.DatetimeIndex) \
        else pd.to_datetime(nav_frame.index)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize,
                                     gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(f"{display} — 多策略净值对比", fontsize=14, fontweight="bold")

    # 净值曲线
    strategy_colors = plt.cm.tab10(np.linspace(0, 1, len(nav_frame.columns)))
    for i, col in enumerate(nav_frame.columns):
        is_benchmark = "买入持有" in col or "buy" in col.lower()
        ax1.plot(dates, nav_frame[col].values, label=col,
                 color=COLORS["benchmark"] if is_benchmark else strategy_colors[i],
                 linewidth=1.2 if is_benchmark else 1.5,
                 linestyle="--" if is_benchmark else "-",
                 alpha=0.5 if is_benchmark else 0.9)
    ax1.axhline(y=1.0, color="black", linewidth=0.5, linestyle=":")
    ax1.set_ylabel("净值")
    ax1.legend(fontsize=8, loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(dates.min(), dates.max())

    # 绩效表格
    if not metrics.empty:
        display_metrics = metrics.copy()
        ax2.axis("off")
        table = ax2.table(
            cellText=display_metrics.round(4).values,
            colLabels=display_metrics.columns.tolist(),
            rowLabels=display_metrics.index.tolist(),
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.4)

    plt.tight_layout()
    save_path = Path(save_path) if save_path else REPORTS_DIR / f"{symbol}_strategy_comparison.png"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


# ============================================================================
# 因子组合回测图：净值对比 + 持仓统计
# ============================================================================

def plot_factor_portfolio(
    portfolio_result,
    *,
    save_path: Optional[Path | str] = None,
    figsize: tuple[int, int] = (14, 8),
) -> Path:
    """绘制因子组合回测图：净值对比 + 超额收益 + 换手率。"""
    from .factor_portfolio import FactorPortfolioResult

    port_rets = portfolio_result.portfolio_returns
    bmk_rets = portfolio_result.benchmark_returns
    turnover = portfolio_result.turnover_series
    name = portfolio_result.factor_name
    metrics = portfolio_result.metrics

    port_nav = (1 + port_rets["ret"]).cumprod()
    common_len = min(len(port_nav), len(bmk_rets))
    bmk_nav = (1 + bmk_rets.iloc[:common_len]).cumprod()

    fig, axes = plt.subplots(3, 1, figsize=figsize,
                              gridspec_kw={"height_ratios": [3, 1.5, 1]})
    fig.suptitle(f"因子组合回测 — {name}", fontsize=14, fontweight="bold")

    # Panel 1: 净值对比
    ax1 = axes[0]
    ax1.plot(port_nav.values, label=f"{name}组合", color=COLORS["strategy"], linewidth=1.5)
    ax1.plot(bmk_nav.values, label="等权基准", color=COLORS["benchmark"], linewidth=1.2, linestyle="--")
    ax1.axhline(y=1.0, color="black", linewidth=0.5, linestyle=":")
    ax1.set_ylabel("净值")
    ax1.legend(fontsize=9, loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.set_title(
        f"组合年化 {metrics['portfolio_annual_return']:.1%}  |  "
        f"基准 {metrics['benchmark_annual_return']:.1%}  |  "
        f"超额 {metrics['excess_annual_return']:.1%}  |  "
        f"夏普 {metrics['portfolio_sharpe']:.2f}  |  "
        f"最大回撤 {metrics['portfolio_max_drawdown']:.1%}",
        fontsize=9, color="gray"
    )

    # Panel 2: 累计超额
    ax2 = axes[1]
    excess = (port_nav.iloc[:common_len].values - bmk_nav.values) / bmk_nav.values
    ax2.fill_between(range(len(excess)), 0, excess,
                      where=(np.array(excess) >= 0), color=COLORS["buy"], alpha=0.3, label="超额")
    ax2.fill_between(range(len(excess)), 0, excess,
                      where=(np.array(excess) < 0), color=COLORS["sell"], alpha=0.3, label="跑输")
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("相对基准超额")
    ax2.grid(True, alpha=0.3)

    # Panel 3: 换手率
    ax3 = axes[2]
    ax3.bar(range(len(turnover)), turnover.values, color=COLORS["strategy"], alpha=0.7, width=0.8)
    ax3.axhline(y=turnover.mean(), color=COLORS["sell"], linewidth=1, linestyle="--",
                label=f"均值 {turnover.mean():.1%}")
    ax3.set_ylabel("换手率")
    ax3.set_xlabel("调仓期")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    save_path = Path(save_path) if save_path else REPORTS_DIR / f"factor_{name}_portfolio.png"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


# ============================================================================
# 内部辅助
# ============================================================================

def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """将回测 DataFrame 转为 mplfinance 需要的 OHLCV 格式。"""
    required = ["trade_date", "open", "high", "low", "close", "volume"]
    available = [c for c in required if c in df.columns]
    if len(available) < 5:
        raise ValueError(f"缺少必要列，需要至少 open/high/low/close，当前有: {available}")

    ohlcv = df[available].copy()
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    ohlcv = ohlcv.set_index("trade_date")
    for col in ["open", "high", "low", "close"]:
        if col in ohlcv.columns:
            ohlcv[col] = pd.to_numeric(ohlcv[col], errors="coerce")
    if "volume" not in ohlcv.columns:
        ohlcv["volume"] = 0
    ohlcv["volume"] = pd.to_numeric(ohlcv["volume"], errors="coerce").fillna(0)

    # 额外列原样带上
    extra_cols = [c for c in df.columns if c not in required and c != "trade_date"]
    for col in extra_cols:
        ohlcv[col] = df[col].values

    return ohlcv.dropna(subset=["open", "high", "low", "close"])


def _build_panel_ratios(panel_count: int) -> tuple[float, ...]:
    """根据面板数分配高度比例。"""
    if panel_count <= 1:
        return (1,)
    ratios = [3.0, 1.0]  # K线 : 成交量
    for _ in range(panel_count - 2):
        ratios.append(1.5)
    return tuple(ratios)
