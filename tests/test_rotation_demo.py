import unittest
import tempfile
from pathlib import Path

import pandas as pd

from quantresearch.database import Instrument, MarketDataDB
from quantresearch.rotation import parse_qlib_instrument, resolve_asset_type, run_rotation_strategy


class RotationDemoTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite3"
        self.db = MarketDataDB(self.db_path)
        self.db.init_db()
        self.db.seed_default_sources()
        self.db.upsert_instrument(Instrument(symbol="QQQ", market="US", asset_type="ETF", name="QQQ"))
        self.db.upsert_instrument(Instrument(symbol="600519", market="CN", asset_type="STOCK", name="贵州茅台"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_strategy_returns_nonempty_nav(self):
        index = pd.date_range("2024-01-01", periods=40, freq="B")
        close_panel = pd.DataFrame(
            {
                "US_QQQ": range(100, 140),
                "US_SPY": [100 + i * 0.2 for i in range(40)],
                "CN_510300": [100 - i * 0.1 for i in range(40)],
            },
            index=index,
        )
        strategy_nav, benchmark_nav, weights, picks = run_rotation_strategy(
            close_panel=close_panel,
            lookback=5,
            top_k=1,
            rebalance="weekly",
        )
        self.assertFalse(strategy_nav.empty)
        self.assertFalse(benchmark_nav.empty)
        self.assertEqual(len(strategy_nav), len(close_panel))
        self.assertTrue((weights.sum(axis=1) <= 1.0 + 1e-9).all())
        self.assertFalse(picks.empty)

    def test_parse_qlib_instrument(self):
        market, symbol = parse_qlib_instrument("US_QQQ")
        self.assertEqual(market, "US")
        self.assertEqual(symbol, "QQQ")

    def test_resolve_asset_type_prefers_db_record(self):
        self.assertEqual(resolve_asset_type("QQQ", "US", db_path=self.db_path), "ETF")
        self.assertEqual(resolve_asset_type("600519", "CN", db_path=self.db_path), "STOCK")
        self.assertEqual(resolve_asset_type("159352", "CN", db_path=self.db_path), "INDEX")


if __name__ == "__main__":
    unittest.main()
