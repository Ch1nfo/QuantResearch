from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .constants import DEFAULT_DATASET_NAME, DEFAULT_DB_PATH, SIGNALS_DIR
from .experiments import record_experiment
from .labels import format_display_symbol
from .serialization import write_json
from .technical_strategies import (
    STRATEGY_REGISTRY,
    extract_trades,
    load_qlib_ohlcv,
    run_strategy_backtest,
)

SIGNAL_SCORE = {"BUY": 1, "SELL": -1, "HOLD": 0}
SIGNAL_TEXT = {"BUY": "买入倾向", "SELL": "卖出倾向", "HOLD": "观望/维持"}


def generate_signal_snapshot(
    *,
    symbol: str,
    market: str,
    asset_type: str,
    as_of: str,
    strategies: list[str],
    params: dict[str, Any] | None = None,
    dataset_name: str = DEFAULT_DATASET_NAME,
    db_path: Path | str = DEFAULT_DB_PATH,
    qlib_repo: Path | str | None = None,
    output_dir: Path | str | None = None,
    target_years: int = 20,
    refresh_recent_days: int = 14,
    auto_prepare: bool = True,
    force_refresh_qlib: bool = False,
    lookback_days: int = 500,
) -> dict:
    start = (datetime.fromisoformat(as_of).date() - timedelta(days=lookback_days)).isoformat()
    frame = load_qlib_ohlcv(
        symbol=symbol,
        market=market,
        asset_type=asset_type,
        start=start,
        end=as_of,
        dataset_name=dataset_name,
        db_path=db_path,
        qlib_repo=qlib_repo,
        output_dir=output_dir,
        target_years=target_years,
        refresh_recent_days=refresh_recent_days,
        auto_prepare=auto_prepare,
        force_refresh_qlib=force_refresh_qlib,
    )
    return build_signal_snapshot(
        frame=frame,
        symbol=symbol,
        market=market,
        asset_type=asset_type,
        as_of=as_of,
        strategies=strategies,
        params=params or {},
        dataset_name=dataset_name,
    )


def build_signal_snapshot(
    *,
    frame: pd.DataFrame,
    symbol: str,
    market: str,
    asset_type: str,
    as_of: str,
    strategies: list[str],
    params: dict[str, Any] | None = None,
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> dict:
    params = params or {}
    as_of_date = pd.to_datetime(as_of)
    data = frame.copy()
    if not data.empty:
        data["trade_date"] = pd.to_datetime(data["trade_date"])
        data = data.loc[data["trade_date"] <= as_of_date].sort_values("trade_date")
    data_asof = None if data.empty else data["trade_date"].max().strftime("%Y-%m-%d")
    signals = [
        build_strategy_signal(strategy=strategy, frame=data, as_of=as_of, params=params, data_asof=data_asof)
        for strategy in strategies
    ]
    voting_signals = [item for item in signals if item["strategy"] != "dca"]
    average_score = (
        sum(float(item["score"]) for item in voting_signals) / len(voting_signals) if voting_signals else 0.0
    )
    return {
        "symbol": symbol.upper(),
        "market": market.upper(),
        "asset_type": asset_type.upper(),
        "dataset_name": dataset_name,
        "as_of": as_of,
        "data_asof": data_asof,
        "row_count": int(len(data)),
        "strategies": strategies,
        "average_score": average_score,
        "signals": signals,
    }


def build_strategy_signal(
    *,
    strategy: str,
    frame: pd.DataFrame,
    as_of: str,
    params: dict[str, Any] | None = None,
    data_asof: str | None = None,
) -> dict:
    params = params or {}
    definition = STRATEGY_REGISTRY[strategy]
    if strategy == "dca":
        return _signal_payload(
            strategy=strategy,
            label=definition.label,
            signal="HOLD",
            confidence=0.0,
            evidence=["定投是资金计划策略，不参与单日买卖信号投票。"],
            data_asof=data_asof or as_of,
        )
    if frame.empty:
        return _signal_payload(
            strategy=strategy,
            label=definition.label,
            signal="HOLD",
            confidence=0.0,
            evidence=["qlib 在该日期前没有返回可用行情。"],
            data_asof=data_asof or as_of,
        )
    if len(frame) < _minimum_rows_for_strategy(strategy, params):
        return _signal_payload(
            strategy=strategy,
            label=definition.label,
            signal="HOLD",
            confidence=0.0,
            evidence=[f"可用数据只有 {len(frame)} 行，暂时不足以稳定计算该策略。"],
            data_asof=data_asof or as_of,
        )

    result = run_strategy_backtest(strategy, frame, **params)
    latest = result.iloc[-1]
    latest_signal = float(latest.get("signal", 0) or 0)
    position = float(latest.get("position", 0) or 0)
    trades = extract_trades(result)
    last_action = _last_trade_action(trades)

    if latest_signal > 0:
        signal = "BUY"
        confidence = 0.8
        reason = "最新一行出现买入信号，通常表示下一交易日执行。"
    elif latest_signal < 0:
        signal = "SELL"
        confidence = 0.8
        reason = "最新一行出现卖出信号，通常表示下一交易日执行。"
    elif position >= 0.5:
        signal = "BUY"
        confidence = 0.6
        reason = "策略当前处于持仓状态，倾向继续持有或增持。"
    elif last_action == "卖出":
        signal = "SELL"
        confidence = 0.6
        reason = "最近一次真实成交是卖出，当前处于空仓状态。"
    else:
        signal = "HOLD"
        confidence = 0.3
        reason = "当前没有新的真实成交信号。"

    evidence = [
        f"收盘价={_fmt(latest.get('close'))}",
        f"策略仓位={position:.0%}",
        reason,
        *_indicator_evidence(strategy, latest),
    ]
    last_trade = _last_trade_summary(trades)
    if last_trade:
        evidence.append(last_trade)
    return _signal_payload(
        strategy=strategy,
        label=definition.label,
        signal=signal,
        confidence=confidence,
        evidence=evidence,
        data_asof=data_asof or as_of,
    )


def build_signal_snapshot_markdown(snapshot: dict, *, show_names: bool = True) -> str:
    display_symbol = (
        format_display_symbol(snapshot["symbol"], snapshot["market"], asset_type=snapshot["asset_type"])
        if show_names
        else snapshot["symbol"]
    )
    rows = [
        {
            "策略": item["label"],
            "信号": SIGNAL_TEXT[item["signal"]],
            "分数": item["score"],
            "置信度": f"{item['confidence']:.0%}",
            "证据": "；".join(item["evidence"]),
        }
        for item in snapshot["signals"]
    ]
    table = pd.DataFrame(rows)
    lines = [
        "# 策略信号快照",
        "",
        "## 摘要",
        "",
        f"- 标的：{display_symbol}",
        f"- 信号日期：`{snapshot['as_of']}`",
        f"- 数据截止日：`{snapshot.get('data_asof') or '无数据'}`",
        f"- qlib 数据集：`{snapshot['dataset_name']}`",
        f"- 平均投票分：`{snapshot['average_score']:.2f}`",
        "",
        "## 策略信号",
        "",
        table.to_markdown(index=False) if not table.empty else "没有策略信号。",
        "",
        "## 说明",
        "",
        "- `BUY` 记为 `+1`，表示买入或继续持有的倾向。",
        "- `SELL` 记为 `-1`，表示卖出或保持空仓的倾向。",
        "- `HOLD` 记为 `0`，表示证据不足或维持观察。",
        "- 信号只使用 qlib 本地数据，不访问实时行情接口。",
    ]
    return "\n".join(lines)


def save_signal_snapshot(
    snapshot: dict,
    *,
    output: Path | str | None = None,
    json_output: Path | str | None = None,
    show_names: bool = True,
    record: bool = True,
) -> tuple[Path | None, Path | None, dict | None]:
    markdown_path = None
    json_path = None
    if output:
        markdown = build_signal_snapshot_markdown(snapshot, show_names=show_names)
        markdown_path = Path(output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
    if json_output:
        json_path = write_json(snapshot, json_output)
    experiment = None
    if record:
        experiment = record_experiment(
            kind="signal-snapshot",
            payload=snapshot,
            dataset_name=snapshot["dataset_name"],
            markdown_path=markdown_path,
            json_path=json_path,
        )
    return markdown_path, json_path, experiment


def default_signal_output(symbol: str, as_of: str) -> Path:
    return SIGNALS_DIR / f"{symbol.lower()}_{as_of.replace('-', '')}.md"


def default_signal_json_output(symbol: str, as_of: str) -> Path:
    return SIGNALS_DIR / f"{symbol.lower()}_{as_of.replace('-', '')}.json"


def _signal_payload(
    *,
    strategy: str,
    label: str,
    signal: str,
    confidence: float,
    evidence: list[str],
    data_asof: str,
) -> dict:
    return {
        "strategy": strategy,
        "label": label,
        "signal": signal,
        "score": SIGNAL_SCORE[signal],
        "confidence": float(confidence),
        "evidence": evidence,
        "data_asof": data_asof,
    }


def _minimum_rows_for_strategy(strategy: str, params: dict[str, Any]) -> int:
    if strategy == "kdj":
        return int(params.get("kdj_n", 9)) + 2
    if strategy == "bollinger":
        return int(params.get("boll_window", 20)) + 2
    if strategy == "ma_cross":
        return int(params.get("ma_long_window", 30)) + 2
    if strategy == "macd":
        return int(params.get("macd_slow_period", 26)) + int(params.get("macd_signal_period", 9))
    if strategy == "rsi":
        return int(params.get("rsi_period", 14)) + 2
    return 20


def _indicator_evidence(strategy: str, row: pd.Series) -> list[str]:
    columns = {
        "kdj": ("k", "d", "j"),
        "bollinger": ("middle_band", "upper_band", "lower_band"),
        "ma_cross": ("ma_short", "ma_long"),
        "macd": ("macd_line", "macd_signal", "macd_hist"),
        "rsi": ("rsi",),
    }.get(strategy, ())
    labels = {
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
    return [f"{labels[column]}={_fmt(row.get(column))}" for column in columns if column in row.index]


def _last_trade_action(trades: pd.DataFrame) -> str | None:
    if trades.empty or "操作" not in trades.columns:
        return None
    return str(trades.iloc[-1]["操作"])


def _last_trade_summary(trades: pd.DataFrame) -> str | None:
    if trades.empty:
        return None
    latest = trades.iloc[-1]
    date = latest.get("日期")
    action = latest.get("操作")
    position = latest.get("成交后仓位")
    if action is None:
        return None
    if position is None:
        return f"最近一次真实成交={date} {action}"
    return f"最近一次真实成交={date} {action}，成交后仓位={float(position):.0%}"


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    if number != number:
        return "NA"
    return f"{number:.4f}"
