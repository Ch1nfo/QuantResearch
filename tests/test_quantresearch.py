import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quantresearch.database import Instrument, MarketDataDB
from quantresearch.constants import PARQUET_EXPORT_DIR, QLIB_CSV_EXPORT_DIR
from quantresearch.exporters import export_dataset_for_qlib
from quantresearch.pipeline import ensure_history_coverage
from quantresearch.queries import get_close_series, get_price_history


class MarketDataDBTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_data.sqlite3"
        self.db = MarketDataDB(self.db_path)
        self.db.init_db()
        self.db.seed_default_sources()
        self.instrument_id = self.db.upsert_instrument(
            Instrument(symbol="QQQ", market="US", asset_type="ETF", name="QQQ", currency="USD")
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_daily_bars_upsert_and_query(self):
        frame = pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-02",
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "close": 101,
                    "volume": 1000,
                    "amount": 100000,
                    "adj_close": 101,
                    "factor": 1.0,
                },
                {
                    "trade_date": "2024-01-03",
                    "open": 101,
                    "high": 103,
                    "low": 100,
                    "close": 102,
                    "volume": 1200,
                    "amount": 120000,
                    "adj_close": 102,
                    "factor": 1.0,
                },
            ]
        )
        self.db.upsert_daily_bars(self.instrument_id, frame)
        self.db.rebuild_weekly_bars([self.instrument_id])

        history = get_price_history("QQQ", "US", "ETF", "2024-01-01", "2024-01-31", db_path=self.db_path)
        self.assertEqual(len(history), 2)
        self.assertEqual(history.iloc[-1]["close"], 102)

        close_series = get_close_series("QQQ", "US", "ETF", "2024-01-01", "2024-01-31", db_path=self.db_path)
        self.assertEqual(close_series.iloc[0], 101)

    def test_export_qlib_csv(self):
        frame = pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-02",
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "close": 101,
                    "volume": 1000,
                    "amount": 100000,
                    "adj_close": 101,
                    "factor": 1.0,
                }
            ]
        )
        self.db.upsert_daily_bars(self.instrument_id, frame)
        export_paths = export_dataset_for_qlib(dataset_name="test_dataset", db_path=self.db_path)
        self.assertEqual(len(export_paths), 1)
        exported = pd.read_csv(export_paths[0])
        self.assertEqual(
            exported.columns.tolist(),
            ["date", "symbol", "open", "close", "high", "low", "volume", "factor"],
        )
        self.assertEqual(exported.iloc[0]["symbol"], "US_QQQ")

    def test_export_qlib_csv_clean_removes_stale_files(self):
        frame = pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-02",
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "close": 101,
                    "volume": 1000,
                    "amount": 100000,
                    "adj_close": 101,
                    "factor": 1.0,
                }
            ]
        )
        self.db.upsert_daily_bars(self.instrument_id, frame)
        dataset_name = "test_dataset_clean"
        export_dir = QLIB_CSV_EXPORT_DIR / dataset_name
        export_dir.mkdir(parents=True, exist_ok=True)
        stale_file = export_dir / "US_OLD.csv"
        stale_file.write_text("date,symbol\n", encoding="utf-8")
        try:
            export_dataset_for_qlib(dataset_name=dataset_name, db_path=self.db_path, clean=True)
            self.assertFalse(stale_file.exists())
            self.assertTrue((export_dir / "US_QQQ.csv").exists())
        finally:
            shutil.rmtree(QLIB_CSV_EXPORT_DIR / dataset_name, ignore_errors=True)
            shutil.rmtree(PARQUET_EXPORT_DIR / dataset_name, ignore_errors=True)

    def test_ensure_history_coverage_backfills_missing_symbol(self):
        mock_frame = pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-02",
                    "open": 100,
                    "high": 102,
                    "low": 99,
                    "close": 101,
                    "volume": 1000,
                    "amount": 100000,
                    "adj_close": 101,
                    "factor": 1.0,
                }
            ]
        )
        with patch("quantresearch.pipeline.collect_history", return_value=mock_frame) as collect_mock:
            result = ensure_history_coverage(
                symbol="SPY",
                market="US",
                asset_type="ETF",
                db_path=self.db_path,
                end="2024-12-31",
                target_years=20,
                refresh_recent_days=0,
            )
        self.assertEqual(result.symbol, "SPY")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(collect_mock.call_count, 1)
        history = get_price_history(
            "SPY",
            "US",
            "ETF",
            "2024-01-01",
            "2024-12-31",
            db_path=self.db_path,
        )
        self.assertEqual(len(history), 1)

    def test_get_price_history_auto_fetches_when_requested(self):
        mock_frame = pd.DataFrame(
            [
                {
                    "trade_date": "2024-02-01",
                    "open": 200,
                    "high": 205,
                    "low": 198,
                    "close": 203,
                    "volume": 2000,
                    "amount": 200000,
                    "adj_close": 203,
                    "factor": 1.0,
                }
            ]
        )
        with patch("quantresearch.pipeline.collect_history", return_value=mock_frame) as collect_mock:
            history = get_price_history(
                "SPY",
                "US",
                "ETF",
                "2024-01-01",
                "2024-12-31",
                db_path=self.db_path,
                auto_fetch=True,
            )
        self.assertEqual(collect_mock.call_count, 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history.iloc[0]["close"], 203)


if __name__ == "__main__":
    unittest.main()
