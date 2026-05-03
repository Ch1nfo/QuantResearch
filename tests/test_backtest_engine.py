import unittest
from unittest.mock import patch

import pandas as pd

from quantresearch.technical_strategies import resolve_backtest_engine, run_strategy_backtest


class BacktestEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=40, freq="B").strftime("%Y-%m-%d"),
                "open": list(range(100, 140)),
                "high": list(range(101, 141)),
                "low": list(range(99, 139)),
                "close": list(range(100, 140)),
                "volume": [1_000_000] * 40,
                "factor": [1.0] * 40,
                "adj_close": list(range(100, 140)),
            }
        )

    def test_auto_engine_falls_back_to_pandas_when_vectorbt_missing(self):
        with patch("quantresearch.technical_strategies.is_vectorbt_available", return_value=False):
            self.assertEqual(resolve_backtest_engine("ma_cross", "auto"), "pandas")
            result = run_strategy_backtest(
                "ma_cross",
                self.frame,
                ma_short_window=3,
                ma_long_window=5,
                backtest_engine="auto",
            )
        self.assertEqual(result.attrs.get("backtest_engine"), "pandas")

    def test_explicit_vectorbt_requires_dependency(self):
        with patch("quantresearch.technical_strategies.is_vectorbt_available", return_value=False):
            with self.assertRaises(RuntimeError):
                run_strategy_backtest(
                    "ma_cross",
                    self.frame,
                    ma_short_window=3,
                    ma_long_window=5,
                    backtest_engine="vectorbt",
                )

    def test_auto_engine_uses_vectorbt_for_supported_strategy_when_available(self):
        fake_result = self.frame.copy()
        fake_result["position"] = 0.0
        fake_result["signal"] = 0
        fake_result["trade"] = 0.0
        fake_result["strategy_ret"] = 0.0
        fake_result["strategy_nav"] = 1.0
        fake_result["buy_hold_nav"] = 1.0
        fake_result["total_value"] = 1.0
        fake_result["holding_value"] = 0.0
        fake_result["cash"] = 1.0
        fake_result["shares"] = 0.0
        fake_result.attrs["backtest_engine"] = "vectorbt"

        with (
            patch("quantresearch.technical_strategies.is_vectorbt_available", return_value=True),
            patch("quantresearch.technical_strategies.run_vectorbt_backtest", return_value=fake_result) as mock_runner,
        ):
            result = run_strategy_backtest(
                "ma_cross",
                self.frame,
                ma_short_window=3,
                ma_long_window=5,
                backtest_engine="auto",
            )

        self.assertTrue(mock_runner.called)
        self.assertEqual(result.attrs.get("backtest_engine"), "vectorbt")


if __name__ == "__main__":
    unittest.main()
