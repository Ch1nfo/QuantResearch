import unittest

import pandas as pd

from quantresearch.technical_strategies import (
    build_dca_invest_signal,
    build_strategy_report,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_moving_average_signals,
    calculate_rsi,
    compare_strategies,
    extract_trades,
    rank_strategies,
    run_bollinger_backtest,
    run_dca_backtest,
    run_macd_backtest,
    run_ma_cross_backtest,
    run_rsi_backtest,
)


class TechnicalStrategiesTestCase(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=40, freq="B").strftime("%Y-%m-%d"),
                "open": [
                    100,
                    100,
                    100,
                    99,
                    95,
                    96,
                    97,
                    98,
                    99,
                    100,
                    101,
                    102,
                    103,
                    104,
                    103,
                    102,
                    101,
                    100,
                    99,
                    98,
                    97,
                    98,
                    99,
                    100,
                    101,
                    102,
                    103,
                    104,
                    105,
                    104,
                    103,
                    102,
                    101,
                    100,
                    99,
                    98,
                    97,
                    98,
                    99,
                    100,
                ],
                "high": [
                    101,
                    101,
                    101,
                    100,
                    96,
                    97,
                    98,
                    99,
                    100,
                    101,
                    102,
                    103,
                    104,
                    105,
                    104,
                    103,
                    102,
                    101,
                    100,
                    99,
                    98,
                    99,
                    100,
                    101,
                    102,
                    103,
                    104,
                    105,
                    106,
                    105,
                    104,
                    103,
                    102,
                    101,
                    100,
                    99,
                    98,
                    99,
                    100,
                    101,
                ],
                "low": [
                    99,
                    99,
                    99,
                    95,
                    90,
                    94,
                    95,
                    96,
                    97,
                    98,
                    99,
                    100,
                    101,
                    102,
                    101,
                    100,
                    99,
                    98,
                    97,
                    96,
                    95,
                    96,
                    97,
                    98,
                    99,
                    100,
                    101,
                    102,
                    103,
                    102,
                    101,
                    100,
                    99,
                    98,
                    97,
                    96,
                    95,
                    96,
                    97,
                    98,
                ],
                "close": [
                    100,
                    100,
                    100,
                    96,
                    92,
                    95,
                    97,
                    99,
                    101,
                    103,
                    105,
                    106,
                    107,
                    108,
                    106,
                    104,
                    102,
                    100,
                    98,
                    96,
                    95,
                    97,
                    99,
                    101,
                    103,
                    105,
                    107,
                    109,
                    111,
                    108,
                    105,
                    102,
                    99,
                    97,
                    95,
                    94,
                    96,
                    98,
                    100,
                    102,
                ],
                "volume": [1_000_000] * 40,
                "factor": [1.0] * 40,
                "adj_close": [
                    100,
                    100,
                    100,
                    96,
                    92,
                    95,
                    97,
                    99,
                    101,
                    103,
                    105,
                    106,
                    107,
                    108,
                    106,
                    104,
                    102,
                    100,
                    98,
                    96,
                    95,
                    97,
                    99,
                    101,
                    103,
                    105,
                    107,
                    109,
                    111,
                    108,
                    105,
                    102,
                    99,
                    97,
                    95,
                    94,
                    96,
                    98,
                    100,
                    102,
                ],
            }
        )

    def test_calculate_bollinger_bands_adds_columns(self):
        result = calculate_bollinger_bands(self.frame, window=5, std_multiplier=2.0)
        self.assertIn("middle_band", result.columns)
        self.assertIn("upper_band", result.columns)
        self.assertIn("lower_band", result.columns)

    def test_calculate_moving_average_signals_adds_columns(self):
        result = calculate_moving_average_signals(self.frame, short_window=5, long_window=10)
        self.assertIn("ma_short", result.columns)
        self.assertIn("ma_long", result.columns)

    def test_calculate_macd_adds_columns(self):
        result = calculate_macd(self.frame)
        self.assertIn("macd_line", result.columns)
        self.assertIn("macd_signal", result.columns)
        self.assertIn("macd_hist", result.columns)

    def test_calculate_rsi_adds_columns(self):
        result = calculate_rsi(self.frame, period=14)
        self.assertIn("rsi", result.columns)

    def test_run_bollinger_backtest_generates_nav(self):
        result = run_bollinger_backtest(self.frame, window=5, std_multiplier=1.5, signal_mode="reversion")
        self.assertIn("strategy_nav", result.columns)
        self.assertIn("buy_hold_nav", result.columns)
        self.assertEqual(len(result), len(self.frame))

    def test_run_ma_cross_backtest_generates_nav(self):
        result = run_ma_cross_backtest(self.frame, short_window=5, long_window=10)
        self.assertIn("strategy_nav", result.columns)
        self.assertEqual(len(result), len(self.frame))

    def test_run_macd_backtest_generates_nav(self):
        result = run_macd_backtest(self.frame, signal_mode="cross")
        self.assertIn("strategy_nav", result.columns)
        self.assertEqual(len(result), len(self.frame))

    def test_run_rsi_backtest_generates_nav(self):
        result = run_rsi_backtest(self.frame, period=14, signal_mode="reversion")
        self.assertIn("strategy_nav", result.columns)
        self.assertEqual(len(result), len(self.frame))

    def test_run_dca_backtest_generates_holdings(self):
        result = run_dca_backtest(self.frame, amount_per_buy=1000.0, frequency="monthly")
        self.assertIn("strategy_nav", result.columns)
        self.assertIn("cash", result.columns)
        self.assertIn("shares", result.columns)
        self.assertIn("total_value", result.columns)
        self.assertGreater(result["shares"].iloc[-1], 0.0)

    def test_build_dca_invest_signal_supports_multiple_frequencies(self):
        monthly_signal = build_dca_invest_signal(self.frame, frequency="monthly", monthly_day=15)
        weekly_signal = build_dca_invest_signal(self.frame, frequency="weekly", weekly_day=2)
        daily_signal = build_dca_invest_signal(self.frame, frequency="daily")
        quarterly_signal = build_dca_invest_signal(self.frame, frequency="quarterly", monthly_day=15)
        self.assertGreater(monthly_signal.sum(), 0)
        self.assertGreater(weekly_signal.sum(), 0)
        self.assertEqual(int(daily_signal.sum()), len(self.frame))
        self.assertGreater(quarterly_signal.sum(), 0)

    def test_extract_trades_only_shows_real_executions(self):
        backtest = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=4, freq="B"),
                "close": [100.0, 101.0, 102.0, 103.0],
                "signal": [-1, -1, 1, -1],
                "position": [0.0, 0.0, 0.0, 1.0],
            }
        )
        trades = extract_trades(backtest)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["操作"], "买入")
        self.assertEqual(trades.iloc[0]["成交后仓位"], 1.0)
        self.assertIn("执行说明", trades.columns)

    def test_compare_strategies_returns_metrics_for_all(self):
        nav_frame, metrics, details = compare_strategies(
            self.frame,
            ["kdj", "bollinger", "ma_cross", "macd", "rsi", "dca"],
            fee_rate=0.0005,
            kdj_n=9,
            kdj_signal_mode="cross",
            boll_window=5,
            boll_std_multiplier=1.5,
            boll_signal_mode="reversion",
            ma_short_window=5,
            ma_long_window=10,
            macd_signal_mode="cross",
            rsi_signal_mode="reversion",
            dca_amount_per_buy=1000.0,
        )
        self.assertEqual(set(nav_frame.columns), {"KDJ", "布林线", "双均线", "MACD", "RSI", "定投", "买入持有"})
        self.assertEqual(set(details.keys()), {"kdj", "bollinger", "ma_cross", "macd", "rsi", "dca"})
        self.assertIn("annual_return", metrics.index)
        self.assertGreater(details["kdj"]["total_value"].iloc[-1], 1000.0)
        self.assertAlmostEqual(details["dca"]["cumulative_invested"].iloc[-1], 1000.0 * details["dca"]["signal"].eq(1).sum())

    def test_build_strategy_report_is_chinese(self):
        nav_frame, metrics, details = compare_strategies(
            self.frame,
            ["kdj", "bollinger", "dca"],
            kdj_signal_mode="cross",
            boll_window=5,
            boll_std_multiplier=1.5,
            dca_amount_per_buy=1000.0,
        )
        report = build_strategy_report(
            nav_frame=nav_frame,
            metrics=metrics,
            details=details,
            symbol="QQQ",
            market="US",
            asset_type="ETF",
            start="2024-01-01",
            end="2024-03-01",
            strategies=["kdj", "bollinger", "dca"],
            params={"fee_rate": 0.0005, "dca_amount_per_buy": 1000.0, "dca_frequency": "monthly"},
            show_names=False,
        )
        self.assertIn("# 技术策略对比报告", report)
        self.assertIn("## 绩效对比", report)
        self.assertIn("数据来源：`qlib`", report)
        self.assertIn("最终仓位：定投", report)
        self.assertIn("交易表默认只展示真实成交", report)

    def test_rank_strategies_returns_best_first(self):
        _, metrics, _ = compare_strategies(
            self.frame,
            ["kdj", "bollinger", "ma_cross", "macd", "rsi", "dca"],
            kdj_signal_mode="cross",
            boll_window=5,
            boll_std_multiplier=1.5,
            ma_short_window=5,
            ma_long_window=10,
            dca_amount_per_buy=1000.0,
        )
        ranking = rank_strategies(metrics, ["kdj", "bollinger", "ma_cross", "macd", "rsi", "dca"], objective="composite")
        self.assertFalse(ranking.empty)
        self.assertEqual(set(ranking["策略"]), {"KDJ", "布林线", "双均线", "MACD", "RSI", "定投"})
        self.assertGreaterEqual(float(ranking.iloc[0]["综合评分"]), float(ranking.iloc[-1]["综合评分"]))


if __name__ == "__main__":
    unittest.main()
