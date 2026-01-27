import tempfile
import unittest
from pathlib import Path

from tools import tool_updater


class ToolUpdaterTests(unittest.TestCase):
    def test_parse_github_repo(self) -> None:
        parsed = tool_updater.parse_github_repo("https://github.com/openai/example.git")
        self.assertEqual(parsed, ("openai", "example"))

    def test_version_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "version.json"
            tool_updater.write_version_file(path, "abc123")
            self.assertEqual(tool_updater.read_version_file(path), "abc123")


if __name__ == "__main__":
    unittest.main()
