import os
import tempfile
import unittest
from pathlib import Path

from quantresearch.qlib_support import resolve_dump_bin_script


class QlibSupportTestCase(unittest.TestCase):
    def test_resolve_dump_bin_script_from_env_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "qlib"
            scripts_dir = repo / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            dump_bin = scripts_dir / "dump_bin.py"
            dump_bin.write_text("# stub\n", encoding="utf-8")

            old_value = os.environ.get("QLIB_REPO")
            os.environ["QLIB_REPO"] = str(repo)
            try:
                resolved = resolve_dump_bin_script()
            finally:
                if old_value is None:
                    os.environ.pop("QLIB_REPO", None)
                else:
                    os.environ["QLIB_REPO"] = old_value

            self.assertEqual(resolved, dump_bin)


if __name__ == "__main__":
    unittest.main()
