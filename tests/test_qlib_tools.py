import unittest

import pandas as pd

from quantresearch.qlib_tools import format_health_table


class QlibToolsTestCase(unittest.TestCase):
    def test_format_health_table_uses_chinese_columns(self):
        frame = pd.DataFrame(
            [
                {
                    "标的": "QQQ(QQQ)",
                    "代码": "US_QQQ",
                    "开始日期": "2024-01-01",
                    "结束日期": "2024-12-31",
                    "行数": 10,
                    "缺失值数量": 0,
                    "缺失率": 0.0,
                    "大幅波动天数": 0,
                }
            ]
        )
        text = format_health_table(frame)
        self.assertIn("缺失率", text)
        self.assertIn("0.00%", text)


if __name__ == "__main__":
    unittest.main()
