import importlib.util
import unittest

import qlib
from qlib.config import REG_US
from qlib.data import D

from quantresearch.constants import DEFAULT_DATASET_NAME, QLIB_DATA_DIR


@unittest.skipUnless(importlib.util.find_spec("qlib"), "pyqlib is not installed")
class QlibSmokeTestCase(unittest.TestCase):
    def test_read_built_qlib_dataset(self):
        provider_uri = QLIB_DATA_DIR / DEFAULT_DATASET_NAME
        if not provider_uri.exists():
            self.skipTest(f"Built qlib dataset not found: {provider_uri}")

        qlib.init(provider_uri=str(provider_uri), region=REG_US)
        df = D.features(
            ["US_QQQ"],
            ["$close", "$open", "$factor"],
            start_time="2024-01-02",
            end_time="2024-01-10",
        )
        self.assertFalse(df.empty)
        self.assertIn("$close", df.columns)
        self.assertIn("US_QQQ", df.index.get_level_values("instrument"))


if __name__ == "__main__":
    unittest.main()
