import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quantresearch.stock_lookup import (
    fetch_cn_stock_catalog,
    get_cn_stock_catalog,
    search_cn_stock_catalog,
)


class StockLookupTestCase(unittest.TestCase):
    def test_fetch_catalog_normalizes_code(self):
        fake = pd.DataFrame(
            [
                {"代码": 1, "名称": "平安银行", "最新价": 10.0},
                {"代码": "600519", "名称": "贵州茅台", "最新价": 1500.0},
            ]
        )
        with patch("quantresearch.stock_lookup.ak.stock_zh_a_spot_em", return_value=fake):
            result = fetch_cn_stock_catalog()
        self.assertEqual(result.iloc[0]["代码"], "000001")
        self.assertEqual(result.iloc[1]["代码"], "600519")

    def test_get_catalog_uses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cn_stock_catalog.csv"
            pd.DataFrame([{"代码": "000001", "名称": "平安银行"}]).to_csv(path, index=False)
            result = get_cn_stock_catalog(path=path)
        self.assertEqual(result.iloc[0]["代码"], "000001")

    def test_search_catalog_filters(self):
        cached = pd.DataFrame(
            [
                {"代码": "000001", "名称": "平安银行"},
                {"代码": "600519", "名称": "贵州茅台"},
            ]
        )
        with patch("quantresearch.stock_lookup.get_cn_stock_catalog", return_value=cached):
            result = search_cn_stock_catalog(query="茅台", limit=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["代码"], "600519")


if __name__ == "__main__":
    unittest.main()
