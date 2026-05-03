import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantresearch import experiments


class ExperimentsTestCase(unittest.TestCase):
    def test_record_list_and_show_experiment_with_jsonl_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            records_dir = Path(temp_dir) / "qlib_records"
            log_path = records_dir / "experiments.jsonl"
            with patch.object(experiments, "QLIB_RECORDS_DIR", records_dir), patch.object(
                experiments, "EXPERIMENT_LOG_PATH", log_path
            ), patch.object(experiments, "_try_record_with_qlib", return_value=("jsonl_fallback", "offline")):
                record = experiments.record_experiment(
                    kind="signal-snapshot",
                    dataset_name="test_dataset",
                    payload={"symbol": "QQQ", "market": "US", "asset_type": "ETF"},
                    markdown_path="reports/signals/qqq.md",
                    json_path="reports/signals/qqq.json",
                )

                records = experiments.list_experiments()
                loaded = experiments.show_experiment(record["experiment_id"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "signal-snapshot")
        self.assertEqual(loaded["payload"]["symbol"], "QQQ")
        self.assertEqual(loaded["recorder_status"], "jsonl_fallback")


if __name__ == "__main__":
    unittest.main()
