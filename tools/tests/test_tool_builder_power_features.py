import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PANDAS_AVAILABLE = importlib.util.find_spec("pandas") is not None
if PANDAS_AVAILABLE:
    import pandas as pd

    from tools import tool_plugins, tool_sessions
else:
    pd = None
    tool_plugins = None
    tool_sessions = None


@unittest.skipUnless(PANDAS_AVAILABLE, "pandas is required for Tool Builder power feature tests")
class ToolBuilderPowerFeatureTests(unittest.TestCase):
    def test_plugin_loader_valid_invalid(self) -> None:
        assert tool_plugins is not None
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)
            (plugin_dir / "good_plugin.py").write_text("def run_plugin(df):\n    return df.head(1)\n", encoding="utf-8")
            (plugin_dir / "bad_plugin.py").write_text("def not_it(df):\n    return df\n", encoding="utf-8")
            plugins, errors = tool_plugins.load_plugins(plugin_dir)
            self.assertEqual(len(plugins), 1)
            self.assertEqual(plugins[0].name, "good_plugin")
            self.assertTrue(any("missing run_plugin" in error for error in errors))

    def test_session_save_load(self) -> None:
        assert tool_sessions is not None
        sample_df = pd.DataFrame({"Team": ["A", "B"], "Value": [3, 4]})
        payload = tool_sessions.build_session_payload(
            csv_paths=["sample.csv"],
            merge_mode="Single file",
            merge_key="",
            selected_columns=["Value"],
            group_by=["Team"],
            operation="SUM",
            filter_data={"column": "", "operator": "=", "value": ""},
            chart_config=tool_sessions.ChartConfig(title="Session"),
            last_result=sample_df,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.moitsession.json"
            tool_sessions.save_session(path, payload)
            loaded = tool_sessions.load_session(path)
        restored = tool_sessions.deserialize_last_result(loaded.get("last_result", {}))
        self.assertIsInstance(restored, pd.DataFrame)
        self.assertEqual(restored.loc[0, "Team"], "A")

    def test_chart_config_parser(self) -> None:
        assert tool_sessions is not None
        payload = {"title": "Chart", "sort_order": "Invalid", "x_label_rotation": 135, "show_data_labels": True}
        config = tool_sessions.ChartConfig.from_dict(payload)
        self.assertEqual(config.sort_order, tool_sessions.CHART_SORT_OPTIONS[0])
        self.assertEqual(config.x_label_rotation, tool_sessions.CHART_ROTATION_OPTIONS[0])
        self.assertTrue(config.show_data_labels)


if __name__ == "__main__":
    unittest.main()
