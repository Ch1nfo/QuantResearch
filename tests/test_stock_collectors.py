import unittest
from unittest.mock import patch

import pandas as pd

from quantresearch.collectors import collect_history


class StockCollectorTestCase(unittest.TestCase):
    def test_collect_cn_stock_history_normalizes_columns(self):
        fake = pd.DataFrame(
            [
                {
                    "日期": "2024-01-02",
                    "开盘": 10.0,
                    "收盘": 10.5,
                    "最高": 10.6,
                    "最低": 9.9,
                    "成交量": 1000000,
                    "成交额": 10500000,
                }
            ]
        )
        with patch("quantresearch.collectors.ak.stock_zh_a_hist", return_value=fake):
            frame = collect_history("000001", "CN", "STOCK", "2024-01-01", "2024-01-31")
        self.assertEqual(
            frame.columns.tolist(),
            ["trade_date", "open", "high", "low", "close", "volume", "amount", "adj_close", "factor"],
        )
        self.assertEqual(frame.iloc[0]["trade_date"], "2024-01-02")


if __name__ == "__main__":
    unittest.main()
