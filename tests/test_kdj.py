import unittest

import pandas as pd

from quantresearch.kdj import calculate_kdj, run_kdj_backtest


class KDJTestCase(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=20, freq="B").strftime("%Y-%m-%d"),
                "open": [10 + i * 0.1 for i in range(20)],
                "high": [10.5 + i * 0.1 for i in range(20)],
                "low": [9.5 + i * 0.1 for i in range(20)],
                "close": [10 + ((-1) ** i) * 0.2 + i * 0.1 for i in range(20)],
                "volume": [1000000] * 20,
                "amount": [10000000] * 20,
                "adj_close": [10 + ((-1) ** i) * 0.2 + i * 0.1 for i in range(20)],
                "factor": [1.0] * 20,
            }
        )

    def test_calculate_kdj_adds_columns(self):
        result = calculate_kdj(self.frame, n=9)
        self.assertIn("k", result.columns)
        self.assertIn("d", result.columns)
        self.assertIn("j", result.columns)

    def test_run_kdj_backtest_generates_nav(self):
        result = run_kdj_backtest(self.frame, n=9, signal_mode="cross")
        self.assertIn("strategy_nav", result.columns)
        self.assertIn("buy_hold_nav", result.columns)
        self.assertEqual(len(result), len(self.frame))


if __name__ == "__main__":
    unittest.main()
