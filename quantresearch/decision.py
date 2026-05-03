from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .constants import DECISIONS_DIR, DEFAULT_DATASET_NAME, DEFAULT_DB_PATH
from .experiments import record_experiment
from .labels import format_display_symbol
from .metrics import format_metrics
from .serialization import dataframe_dict, dataframe_records, write_json
from .signals import SIGNAL_TEXT, build_signal_snapshot
from .technical_strategies import (
    STRATEGY_REGISTRY,
    compare_strategies,
    extract_trades,
    load_qlib_ohlcv,
)

VOTING_STRATEGIES = {"kdj", "bollinger", "ma_cross", "macd", "rsi"}


def generate_decision_report(
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
    history_years: int = 2,
    risk_free_rate: float = 0.0,
) -> dict:
    params = params or {}
    start = _subtract_years(as_of, history_years)
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
    )
    signal_snapshot = build_signal_snapshot(
        frame=frame,
        symbol=symbol,
        market=market,
        asset_type=asset_type,
        as_of=as_of,
        strategies=strategies,
        params=params,
        dataset_name=dataset_name,
    )
    health = _health_from_frame(frame, as_of=as_of)
    vote_signals = [
        item for item in signal_snapshot["signals"] if item["strategy"] in VOTING_STRATEGIES and item["strategy"] in strategies
    ]
    average_score = sum(float(item["score"]) for item in vote_signals) / len(vote_signals) if vote_signals else 0.0
    decision = _decide(average_score=average_score, health_ok=bool(health["ok"]))
    metrics = pd.DataFrame()
    details: dict[str, pd.DataFrame] = {}
    if not frame.empty:
        metrics_strategies = [strategy for strategy in strategies if strategy in STRATEGY_REGISTRY]
        _, metrics, details = compare_strategies(
            frame,
            metrics_strategies,
            risk_free_rate=risk_free_rate,
            **params,
        )
    recent_trades = _recent_trade_rows(details)
    return {
        "symbol": symbol.upper(),
        "market": market.upper(),
        "asset_type": asset_type.upper(),
        "dataset_name": dataset_name,
        "as_of": as_of,
        "start": start,
        "end": as_of,
        "data_asof": signal_snapshot.get("data_asof"),
        "health": health,
        "strategies": strategies,
        "signals": signal_snapshot["signals"],
        "average_score": average_score,
        "decision": decision,
        "metrics": dataframe_dict(metrics),
        "recent_trades": recent_trades,
        "params": params,
        "risk_warnings": _risk_warnings(),
        "reversal_conditions": _reversal_conditions(decision["action"]),
    }


def build_decision_markdown(report: dict, *, show_names: bool = True) -> str:
    display_symbol = (
        format_display_symbol(report["symbol"], report["market"], asset_type=report["asset_type"])
        if show_names
        else report["symbol"]
    )
    health = report["health"]
    signal_rows = [
        {
            "策略": item["label"],
            "信号": SIGNAL_TEXT[item["signal"]],
            "分数": item["score"],
            "置信度": f"{item['confidence']:.0%}",
            "证据": "；".join(item["evidence"]),
        }
        for item in report["signals"]
    ]
    trade_rows = report["recent_trades"]
    metrics = pd.DataFrame(report["metrics"])
    lines = [
        "# 单标的 qlib 决策报告",
        "",
        "## 摘要",
        "",
        f"- 标的：{display_symbol}",
        f"- 数据截止日：`{report.get('data_asof') or '无数据'}`",
        f"- 决策日期：`{report['as_of']}`",
        f"- 回测区间：`{report['start']}` 至 `{report['end']}`",
        f"- qlib 数据集：`{report['dataset_name']}`",
        "",
        "## qlib 数据健康检查",
        "",
        f"- 状态：{'通过' if health['ok'] else '失败'}",
        f"- 行数：`{health['row_count']}`",
        f"- 最新交易日：`{health.get('latest_date') or '无'}`",
        f"- 距离决策日：`{health.get('stale_days')}` 天",
        f"- 缺失值数量：`{health['missing_values']}`",
        f"- 说明：{health['message']}",
        "",
        "## 策略信号表",
        "",
        pd.DataFrame(signal_rows).to_markdown(index=False) if signal_rows else "没有信号。",
        "",
        "## 历史回测摘要",
        "",
        format_metrics(metrics).to_markdown() if not metrics.empty else "没有可用回测指标。",
        "",
        "## 最近真实成交",
        "",
        pd.DataFrame(trade_rows).to_markdown(index=False) if trade_rows else "没有真实成交记录。",
        "",
        "## 当前结论",
        "",
        f"- 投票平均分：`{report['average_score']:.2f}`",
        f"- 结论：**{report['decision']['label']}**",
        f"- 建议目标仓位：`{report['decision']['target_exposure_label']}`",
        f"- 解释：{report['decision']['reason']}",
        "",
        "## 推翻条件",
        "",
        *[f"- {item}" for item in report["reversal_conditions"]],
        "",
        "## 风险提示",
        "",
        *[f"- {item}" for item in report["risk_warnings"]],
    ]
    return "\n".join(lines)


def save_decision_report(
    report: dict,
    *,
    output: Path | str | None = None,
    json_output: Path | str | None = None,
    show_names: bool = True,
    record: bool = True,
) -> tuple[Path | None, Path | None, dict | None]:
    markdown_path = None
    json_path = None
    if output:
        markdown_path = Path(output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(build_decision_markdown(report, show_names=show_names), encoding="utf-8")
    if json_output:
        json_path = write_json(report, json_output)
    experiment = None
    if record:
        experiment = record_experiment(
            kind="decision-report",
            payload=report,
            dataset_name=report["dataset_name"],
            markdown_path=markdown_path,
            json_path=json_path,
        )
    return markdown_path, json_path, experiment


def default_decision_output(symbol: str, as_of: str) -> Path:
    return DECISIONS_DIR / f"{symbol.lower()}_{as_of.replace('-', '')}.md"


def default_decision_json_output(symbol: str, as_of: str) -> Path:
    return DECISIONS_DIR / f"{symbol.lower()}_{as_of.replace('-', '')}.json"


def _health_from_frame(frame: pd.DataFrame, *, as_of: str, max_stale_days: int = 10) -> dict:
    if frame.empty:
        return {
            "ok": False,
            "row_count": 0,
            "latest_date": None,
            "stale_days": None,
            "missing_values": None,
            "message": "qlib 没有返回该标的的行情数据。",
        }
    data = frame.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    latest_date = data["trade_date"].max()
    stale_days = (pd.to_datetime(as_of) - latest_date).days
    missing_values = int(data[["open", "high", "low", "close", "volume", "factor"]].isna().sum().sum())
    ok = len(data) >= 30 and stale_days <= max_stale_days and missing_values == 0
    if ok:
        message = "qlib 本地数据可用于本次决策。"
    elif len(data) < 30:
        message = "可用行情少于 30 行，暂不适合做技术策略决策。"
    elif stale_days > max_stale_days:
        message = "本地 qlib 数据距离决策日过久，建议先刷新数据。"
    else:
        message = "行情字段存在缺失值，建议先检查数据源。"
    return {
        "ok": ok,
        "row_count": int(len(data)),
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "stale_days": int(stale_days),
        "missing_values": missing_values,
        "message": message,
    }


def _decide(*, average_score: float, health_ok: bool) -> dict:
    if not health_ok:
        return {
            "action": "NO_DECISION",
            "label": "暂不决策",
            "target_exposure": 0.0,
            "target_exposure_label": "0%",
            "reason": "qlib 数据健康检查没有通过，本次不输出买卖建议。",
        }
    if average_score >= 0.35:
        return {
            "action": "BUY",
            "label": "买入/增持",
            "target_exposure": 0.6,
            "target_exposure_label": "60%",
            "reason": "多数技术信号偏多，第一版规则建议把目标仓位提高到 60%。",
        }
    if average_score <= -0.35:
        return {
            "action": "SELL",
            "label": "卖出/减仓",
            "target_exposure": 0.0,
            "target_exposure_label": "0%",
            "reason": "多数技术信号偏空，第一版规则建议降到空仓观察。",
        }
    return {
        "action": "HOLD",
        "label": "观望/持有",
        "target_exposure": 0.3,
        "target_exposure_label": "30%",
        "reason": "多空信号没有形成明显合力，第一版规则建议保持观察仓位。",
    }


def _recent_trade_rows(details: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    for strategy, detail in details.items():
        trades = extract_trades(detail)
        if trades.empty:
            continue
        latest = trades.tail(1).iloc[0].to_dict()
        rows.append(
            {
                "策略": STRATEGY_REGISTRY[strategy].label,
                "日期": latest.get("日期"),
                "操作": latest.get("操作"),
                "收盘价": latest.get("收盘价"),
                "成交后仓位": latest.get("成交后仓位"),
                "执行说明": latest.get("执行说明"),
            }
        )
    return dataframe_records(pd.DataFrame(rows))


def _reversal_conditions(action: str) -> list[str]:
    if action == "BUY":
        return ["平均信号分跌回 0.00 以下。", "收盘价跌破 20 日均线且 MACD 同步转弱。", "RSI 再次转弱并跌破 50。"]
    if action == "SELL":
        return ["平均信号分回升到 0.00 以上。", "收盘价重新站上 20 日均线。", "MACD 或 RSI 出现明确转强信号。"]
    if action == "HOLD":
        return ["平均信号分上穿 0.35。", "平均信号分下穿 -0.35。", "数据健康检查失败或最新行情缺失。"]
    return ["先修复 qlib 数据健康问题，再重新生成决策报告。"]


def _risk_warnings() -> list[str]:
    return [
        "本报告是量化研究辅助，不是自动交易指令。",
        "技术指标对震荡行情容易产生反复信号，需要结合仓位管理。",
        "指数和股票的波动、流动性、交易时区不同，跨市场对比时要额外谨慎。",
        "若后续接入模型预测，第一阶段仍应保留人工复核。",
    ]


def _subtract_years(as_of: str, years: int) -> str:
    date = datetime.fromisoformat(as_of).date()
    try:
        return date.replace(year=date.year - years).isoformat()
    except ValueError:
        return date.replace(year=date.year - years, day=28).isoformat()
