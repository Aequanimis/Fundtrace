import tempfile
import unittest
from pathlib import Path

import app


class AppHelperTests(unittest.TestCase):
    def test_validate_fund_code(self):
        self.assertEqual(app.validate_fund_code("161005"), (True, "161005"))
        for invalid in ("16100", "1610057", "中文", "161 005", "../161005", ""):
            self.assertFalse(app.validate_fund_code(invalid)[0], invalid)

    def test_data_checks_and_chinese_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "中文 路径" / "基金高频"
            (root / "base").mkdir(parents=True)
            self.assertFalse(app.base_data_exists(root))
            for name in app.REQUIRED_BASE_FILES:
                (root / "base" / name).write_text("x", encoding="utf-8")
            self.assertTrue(app.base_data_exists(root))

            (root / "funds" / "161005").mkdir(parents=True)
            self.assertFalse(app.fund_data_exists("161005", root))
            for name in app.REQUIRED_FUND_FILES:
                (root / "funds" / "161005" / name).write_text("x", encoding="utf-8")
            self.assertTrue(app.fund_data_exists("161005", root))

    def test_history_accepts_partial_results_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "output" / "161005"
            result.mkdir(parents=True)
            (result / "report.md").write_text("可信度评级：B", encoding="utf-8")
            self.assertEqual(app.analyzed_funds(root), ["161005"])
            self.assertEqual(app.extract_confidence("## 可信度评级：**B**"), "B")

            (root / "output" / "not-a-code").mkdir()
            self.assertEqual(app.analyzed_funds(root), ["161005"])

    def test_output_decoding(self):
        text = "中文路径正常"
        self.assertEqual(app._decode_output(text.encode("utf-8")), text)
        self.assertEqual(app._decode_output(text.encode("gb18030")), text)

    def test_subprocess_timeout_is_reported(self):
        result = app.run_project_script(
            ("-c", "import time; time.sleep(10)"), timeout=1
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("已停止", result.stderr)


if __name__ == "__main__":
    unittest.main()
