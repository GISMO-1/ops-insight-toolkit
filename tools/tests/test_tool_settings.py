import tempfile
import unittest
from pathlib import Path

from tools import tool_settings


class ToolSettingsTests(unittest.TestCase):
    def test_settings_round_trip(self) -> None:
        settings = tool_settings.ToolBuilderSettings(
            restore_last_session=False,
            auto_save_session=False,
            auto_reload_csv=False,
            silent_csv_reload=True,
            auto_reload_plugins=False,
            check_updates_on_launch=True,
            safe_mode=True,
            csv_poll_interval=7.5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            tool_settings.save_settings(path, settings)
            loaded = tool_settings.load_settings(path)
        self.assertEqual(settings, loaded)


if __name__ == "__main__":
    unittest.main()
