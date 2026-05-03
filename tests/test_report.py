import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quantresearch.rotation import build_rotation_report, save_rotation_report


class ReportTestCase(unittest.TestCase):
    def test_build_rotation_report_contains_sections(self):
        index = pd.date_range("2024-01-01", periods=3, freq="B")
        strategy_nav = pd.Series([1.0, 1.01, 1.02], index=index)
        benchmark_nav = pd.Series([1.0, 1.005, 1.01], index=index)
        picks = pd.DataFrame(
            [{"decision_date": "2024-01-31", "effective_date": "2024-02-01", "selected": "US_QQQ", "scores": "US_QQQ:1.00%"}]
        )
        report = build_rotation_report(
            strategy_nav=strategy_nav,
            benchmark_nav=benchmark_nav,
            picks=picks,
            start="2024-01-01",
            end="2024-12-31",
            lookback=20,
            top_k=1,
            rebalance="monthly",
            require_positive_momentum=False,
            universe=["US_QQQ"],
            risk_free_rate=0.0,
            show_names=False,
        )
        self.assertIn("# 指数动量轮动报告", report)
        self.assertIn("## 绩效指标", report)
        self.assertIn("## 最近调仓", report)

    def test_save_rotation_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.md"
            output = save_rotation_report("# hello", path)
            self.assertTrue(output.exists())
            self.assertIn("# hello", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
