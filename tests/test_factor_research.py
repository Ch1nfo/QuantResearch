import unittest
from unittest.mock import patch

import pandas as pd

from quantresearch.factor_research import analyze_factor


class FactorResearchTestCase(unittest.TestCase):
    def test_analyze_factor_generates_summary_and_series(self):
        dates = pd.date_range("2024-01-05", periods=8, freq="W-FRI")
        records = []
        for idx, instrument in enumerate(["CN_A", "CN_B", "CN_C", "CN_D", "CN_E"]):
            for step, trade_date in enumerate(dates):
                records.append(
                    {
                        "instrument": instrument,
                        "datetime": trade_date,
                        "alpha": float(idx + step + 1),
                        "$close": float(100 + idx * 2 + step),
                    }
                )
        frame = pd.DataFrame(records).set_index(["instrument", "datetime"])

        fake_d = type("FakeD", (), {"features": staticmethod(lambda *args, **kwargs: frame)})
        with patch("quantresearch.factor_research.prepare_qlib_universe"), patch("quantresearch.factor_research.D", fake_d):
            result = analyze_factor(
                universe=["CN_A", "CN_B", "CN_C", "CN_D", "CN_E"],
                start="2024-01-01",
                end="2024-03-31",
                factor_name="Alpha",
                expression="alpha",
                quantiles=5,
                forward_days=1,
                rebalance="weekly",
                auto_prepare=False,
            )

        self.assertEqual(result.factor_name, "Alpha")
        self.assertIn("mean_ic", result.summary)
        self.assertFalse(result.preview.empty)
        self.assertFalse(result.ic_series.empty)
        self.assertFalse(result.quantile_returns.empty)
        self.assertIn("累计多空", result.long_short_returns.columns)


if __name__ == "__main__":
    unittest.main()
