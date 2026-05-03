import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quantresearch.database import Instrument, MarketDataDB
from quantresearch.labels import format_display_symbol, format_qlib_instrument, relabel_metric_columns, relabel_rotation_picks


class LabelsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite3"
        db = MarketDataDB(self.db_path)
        db.init_db()
        db.upsert_instrument(Instrument(symbol="QQQ", market="US", asset_type="ETF", name="Invesco QQQ Trust"))
        db.upsert_instrument(Instrument(symbol="159352", market="CN", asset_type="ETF", name="A500ETF南方"))
        db.upsert_instrument(Instrument(symbol="600519", market="CN", asset_type="STOCK", name="贵州茅台"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_format_display_symbol(self):
        label = format_display_symbol("QQQ", "US", db_path=self.db_path)
        self.assertEqual(label, "Invesco QQQ Trust(QQQ)")

    def test_relabel_metric_columns(self):
        metrics = pd.DataFrame({"QQQ": {"annual_return": 0.1}})
        relabeled = relabel_metric_columns(metrics, market="US", db_path=self.db_path)
        self.assertIn("Invesco QQQ Trust(QQQ)", relabeled.columns)

    def test_format_qlib_instrument_infers_stock_name(self):
        label = format_qlib_instrument("CN_600519", db_path=self.db_path)
        self.assertEqual(label, "贵州茅台(600519)")

    def test_relabel_rotation_picks(self):
        picks = pd.DataFrame(
            [{"selected": "US_QQQ,CN_159352", "scores": "US_QQQ:1.00%, CN_159352:2.00%"}]
        )
        relabeled = relabel_rotation_picks(picks, db_path=self.db_path)
        self.assertEqual(
            relabeled.iloc[0]["selected"],
            "Invesco QQQ Trust(QQQ),A500ETF南方(159352)",
        )


if __name__ == "__main__":
    unittest.main()
