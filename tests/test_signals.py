import unittest

import pandas as pd

from quantresearch.signals import build_signal_snapshot, build_strategy_signal, build_signal_snapshot_markdown


class SignalsTestCase(unittest.TestCase):
    def setUp(self):
        closes = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 100, 102, 104, 106, 108, 110]
        self.frame = pd.DataFrame(
            {
                "trade_date": pd.date_range("2024-01-01", periods=len(closes), freq="B").strftime("%Y-%m-%d"),
                "open": closes,
                "high": [value + 1 for value in closes],
                "low": [value - 1 for value in closes],
                "close": closes,
                "volume": [1000.0] * len(closes),
                "factor": [1.0] * len(closes),
                "adj_close": closes,
            }
        )

    def test_strategy_signal_has_standard_shape(self):
        signal = build_strategy_signal(
            strategy="ma_cross",
            frame=self.frame,
            as_of="2024-01-22",
            params={"ma_short_window": 3, "ma_long_window": 5},
            data_asof="2024-01-22",
        )

        self.assertEqual(signal["strategy"], "ma_cross")
        self.assertIn(signal["signal"], {"BUY", "SELL", "HOLD"})
        self.assertIn(signal["score"], {-1, 0, 1})
        self.assertTrue(signal["evidence"])

    def test_dca_signal_is_hold_and_not_voted(self):
        snapshot = build_signal_snapshot(
            frame=self.frame,
            symbol="QQQ",
            market="US",
            asset_type="ETF",
            as_of="2024-01-22",
            strategies=["ma_cross", "dca"],
            params={"ma_short_window": 3, "ma_long_window": 5},
        )

        dca = next(item for item in snapshot["signals"] if item["strategy"] == "dca")
        self.assertEqual(dca["signal"], "HOLD")
        self.assertEqual(dca["score"], 0)
        self.assertEqual(snapshot["row_count"], len(self.frame))

    def test_insufficient_data_returns_hold(self):
        signal = build_strategy_signal(
            strategy="bollinger",
            frame=self.frame.head(3),
            as_of="2024-01-03",
            params={"boll_window": 20},
            data_asof="2024-01-03",
        )

        self.assertEqual(signal["signal"], "HOLD")
        self.assertIn("不足", signal["evidence"][0])

    def test_markdown_is_chinese(self):
        snapshot = build_signal_snapshot(
            frame=self.frame,
            symbol="QQQ",
            market="US",
            asset_type="ETF",
            as_of="2024-01-22",
            strategies=["ma_cross"],
            params={"ma_short_window": 3, "ma_long_window": 5},
        )
        markdown = build_signal_snapshot_markdown(snapshot, show_names=False)

        self.assertIn("# 策略信号快照", markdown)
        self.assertIn("策略信号", markdown)
        self.assertIn("平均投票分", markdown)


if __name__ == "__main__":
    unittest.main()
