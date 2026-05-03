import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quantresearch.consistency import check_qlib_consistency
from quantresearch.constants import PARQUET_EXPORT_DIR, QLIB_CSV_EXPORT_DIR
from quantresearch.database import Instrument, MarketDataDB
from quantresearch.exporters import export_dataset_for_qlib


class ConsistencyTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite3"
        self.dataset_name = "consistency_test_dataset"
        self.db = MarketDataDB(self.db_path)
        self.db.init_db()
        self.instrument_id = self.db.upsert_instrument(
            Instrument(symbol="QQQ", market="US", asset_type="ETF", name="QQQ")
        )
        self.db.upsert_daily_bars(
            self.instrument_id,
            pd.DataFrame(
                [
                    {
                        "trade_date": "2024-01-02",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1000.0,
                        "amount": 100000.0,
                        "adj_close": 100.5,
                        "factor": 1.0,
                    }
                ]
            ),
        )

    def tearDown(self):
        shutil.rmtree(QLIB_CSV_EXPORT_DIR / self.dataset_name, ignore_errors=True)
        shutil.rmtree(PARQUET_EXPORT_DIR / self.dataset_name, ignore_errors=True)
        self.temp_dir.cleanup()

    def test_consistency_matches_sqlite_csv_and_bin_symbols(self):
        export_dataset_for_qlib(dataset_name=self.dataset_name, db_path=self.db_path, clean=True)
        qlib_dir = Path(self.temp_dir.name) / "qlib_data"
        (qlib_dir / "features" / "us_qqq").mkdir(parents=True)

        result = check_qlib_consistency(
            dataset_name=self.dataset_name,
            db_path=self.db_path,
            qlib_dir=qlib_dir,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["sqlite_symbols"], ["US_QQQ"])
        self.assertEqual(result["csv_symbols"], ["US_QQQ"])
        self.assertEqual(result["bin_symbols"], ["US_QQQ"])

    def test_consistency_detects_extra_csv_file(self):
        export_dataset_for_qlib(dataset_name=self.dataset_name, db_path=self.db_path, clean=True)
        (QLIB_CSV_EXPORT_DIR / self.dataset_name / "US_OLD.csv").write_text("date,symbol\n", encoding="utf-8")
        qlib_dir = Path(self.temp_dir.name) / "qlib_data"
        (qlib_dir / "features" / "us_qqq").mkdir(parents=True)

        result = check_qlib_consistency(
            dataset_name=self.dataset_name,
            db_path=self.db_path,
            qlib_dir=qlib_dir,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["extra_in_csv"], ["US_OLD"])


if __name__ == "__main__":
    unittest.main()
