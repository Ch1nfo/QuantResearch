import os
import unittest
from unittest.mock import patch

import pandas as pd

from quantresearch.wencai import resolve_wencai_cookie, query_wencai, standardize_wencai_etf_result


class WencaiTestCase(unittest.TestCase):
    def test_resolve_cookie_from_env(self):
        with patch.dict(os.environ, {"WENCAI_COOKIE": "cookie123"}, clear=False):
            self.assertEqual(resolve_wencai_cookie(), "cookie123")

    def test_resolve_cookie_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                resolve_wencai_cookie()

    def test_query_wencai_wraps_dataframe(self):
        fake = pd.DataFrame([{"股票代码": "510300", "股票简称": "沪深300ETF"}])
        with patch("quantresearch.wencai.pywencai.get", return_value=fake):
            result = query_wencai("沪深300ETF", cookie="cookie123")
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["股票代码"], "510300")

    def test_standardize_wencai_etf_result(self):
        fake = pd.DataFrame([{"股票代码": "510300", "股票简称": "沪深300ETF华泰柏瑞"}])
        result = standardize_wencai_etf_result(fake, source_query="沪深300ETF")
        self.assertEqual(
            result.columns.tolist(),
            ["symbol", "name", "market", "asset_type", "exchange", "source_query"],
        )
        self.assertEqual(result.iloc[0]["symbol"], "510300")


if __name__ == "__main__":
    unittest.main()
