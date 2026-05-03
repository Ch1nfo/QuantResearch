import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quantresearch.etf_lookup import (
    fetch_cn_etf_catalog,
    get_cn_etf_catalog,
    search_cn_etf_catalog,
)


class EtfLookupTestCase(unittest.TestCase):
    def test_fetch_catalog_normalizes_code(self):
        fake = pd.DataFrame(
            [
                {"代码": 510300, "名称": "沪深300ETF华泰柏瑞", "最新价": 4.1},
                {"代码": "159352", "名称": "A500ETF南方", "最新价": 1.1},
            ]
        )
        with patch("quantresearch.etf_lookup.ak.fund_etf_spot_em", return_value=fake):
            result = fetch_cn_etf_catalog()
        self.assertEqual(result.iloc[0]["代码"], "159352")
        self.assertEqual(result.iloc[1]["代码"], "510300")

    def test_get_catalog_uses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cn_etf_catalog.csv"
            pd.DataFrame([{"代码": "510300", "名称": "沪深300ETF华泰柏瑞"}]).to_csv(path, index=False)
            result = get_cn_etf_catalog(path=path)
        self.assertEqual(result.iloc[0]["代码"], "510300")

    def test_search_catalog_filters_by_query(self):
        cached = pd.DataFrame(
            [
                {"代码": "510300", "名称": "沪深300ETF华泰柏瑞"},
                {"代码": "159352", "名称": "A500ETF南方"},
            ]
        )
        with patch("quantresearch.etf_lookup.get_cn_etf_catalog", return_value=cached):
            result = search_cn_etf_catalog(query="南方", limit=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["代码"], "159352")


if __name__ == "__main__":
    unittest.main()
