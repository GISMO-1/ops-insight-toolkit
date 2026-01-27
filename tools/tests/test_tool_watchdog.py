import time
import unittest
from pathlib import Path

from tools import tool_watchdog


class ToolWatchdogTests(unittest.TestCase):
    def test_directory_signature_changes(self) -> None:
        temp_dir = Path(".tool_watchdog_test_case")
        temp_dir.mkdir(exist_ok=True)
        file_path = temp_dir / "plugin.py"
        try:
            file_path.write_text("print('one')\n", encoding="utf-8")
            sig_1 = tool_watchdog.compute_directory_signature(temp_dir)
            time.sleep(0.01)
            file_path.write_text("print('two')\n", encoding="utf-8")
            sig_2 = tool_watchdog.compute_directory_signature(temp_dir)
        finally:
            if file_path.exists():
                file_path.unlink()
            temp_dir.rmdir()
        self.assertNotEqual(sig_1, sig_2)


if __name__ == "__main__":
    unittest.main()
