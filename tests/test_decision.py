import unittest

import pandas as pd

from quantresearch.decision import _decide, _health_from_frame, build_decision_markdown


class DecisionTestCase(unittest.TestCase):
    def test_decision_rules_follow_average_score_thresholds(self):
        self.assertEqual(_decide(average_score=0.35, health_ok=True)["label"], "买入/增持")
        self.assertEqual(_decide(average_score=-0.35, health_ok=True)["label"], "卖出/减仓")
        self.assertEqual(_decide(average_score=0.0, health_ok=True)["label"], "观望/持有")
        self.assertEqual(_decide(average_score=0.8, health_ok=False)["label"], "暂不决策")

    def test_health_fails_when_frame_is_empty(self):
        health = _health_from_frame(pd.DataFrame(), as_of="2024-01-31")

        self.assertFalse(health["ok"])
        self.assertIn("没有返回", health["message"])

    def test_health_passes_for_complete_recent_frame(self):
        frame = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=35, freq="B").strftime("%Y-%m-%d"),
                "open": [100.0] * 35,
                "high": [101.0] * 35,
                "low": [99.0] * 35,
                "close": [100.0] * 35,
                "volume": [1000.0] * 35,
                "factor": [1.0] * 35,
            }
        )
        health = _health_from_frame(frame, as_of="2024-02-16")

        self.assertTrue(health["ok"])
        self.assertEqual(health["missing_values"], 0)

    def test_decision_markdown_is_chinese_and_consistent(self):
        report = {
            "symbol": "000510",
            "market": "CN",
            "asset_type": "INDEX",
            "dataset_name": "mixed_etf_stock_fund_day",
            "as_of": "2026-04-30",
            "start": "2024-04-30",
            "end": "2026-04-30",
            "data_asof": "2026-04-30",
            "health": {
                "ok": True,
                "row_count": 300,
                "latest_date": "2026-04-30",
                "stale_days": 0,
                "missing_values": 0,
                "message": "qlib 本地数据可用于本次决策。",
            },
            "signals": [
                {
                    "strategy": "rsi",
                    "label": "RSI",
                    "signal": "BUY",
                    "score": 1,
                    "confidence": 0.6,
                    "evidence": ["RSI=55"],
                    "data_asof": "2026-04-30",
                }
            ],
            "average_score": 1.0,
            "decision": _decide(average_score=1.0, health_ok=True),
            "metrics": {},
            "recent_trades": [],
            "reversal_conditions": ["平均信号分跌回 0.00 以下。"],
            "risk_warnings": ["本报告是量化研究辅助，不是自动交易指令。"],
        }

        markdown = build_decision_markdown(report, show_names=False)

        self.assertIn("# 单标的 qlib 决策报告", markdown)
        self.assertIn("建议目标仓位", markdown)
        self.assertIn("买入/增持", markdown)
        self.assertIn("风险提示", markdown)


if __name__ == "__main__":
    unittest.main()
