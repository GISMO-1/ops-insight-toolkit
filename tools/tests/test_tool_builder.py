import importlib
import os
import unittest

from tools import csv_engine, tool_builder


class ToolBuilderTests(unittest.TestCase):
    def test_self_check(self) -> None:
        ok, message = tool_builder.self_check()
        self.assertTrue(ok, message)

    def test_filter_contains(self) -> None:
        data = csv_engine.CSVTable(
            columns=["Reason"],
            rows=[{"Reason": "Jam"}, {"Reason": "Reset"}, {"Reason": "Jam"}],
        )
        filtered = tool_builder.apply_filters(
            data,
            [tool_builder.FilterRule("Reason", "contains", "jam")],
        )
        self.assertEqual(len(filtered.rows), 2)

    def test_count_grouped_baseline(self) -> None:
        data = csv_engine.CSVTable(
            columns=["Shift", "Duration"],
            rows=[
                {"Shift": "A", "Duration": "5"},
                {"Shift": "A", "Duration": "7"},
                {"Shift": "B", "Duration": "3"},
            ],
        )
        result = tool_builder.perform_operation(data, ["Duration"], ["Shift"], "COUNT")
        counts = {row["Shift"]: row["COUNT_Duration"] for row in result.rows}
        self.assertEqual(counts.get("A"), "2")
        self.assertEqual(counts.get("B"), "1")

    def test_count_no_columns_total(self) -> None:
        data = csv_engine.CSVTable(
            columns=["Shift", "Duration"],
            rows=[
                {"Shift": "A", "Duration": "5"},
                {"Shift": "A", "Duration": "7"},
                {"Shift": "B", "Duration": "3"},
            ],
        )
        result = tool_builder.perform_operation(data, [], [], "COUNT")
        self.assertEqual(result.columns, ["count"])
        self.assertEqual(result.rows[0]["count"], "3")

    def test_import_without_pandas_env(self) -> None:
        original = os.environ.get("MOIT_DISABLE_PANDAS")
        os.environ["MOIT_DISABLE_PANDAS"] = "1"
        try:
            reloaded = importlib.reload(tool_builder)
            self.assertFalse(reloaded.PANDAS_AVAILABLE)
            data = csv_engine.CSVTable(
                columns=["Shift"],
                rows=[{"Shift": "A"}, {"Shift": "B"}],
            )
            result = reloaded.perform_operation(data, [], [], "COUNT")
            self.assertEqual(result.rows[0]["count"], "2")
        finally:
            if original is None:
                os.environ.pop("MOIT_DISABLE_PANDAS", None)
            else:
                os.environ["MOIT_DISABLE_PANDAS"] = original
            importlib.reload(tool_builder)

    def test_compute_palette_contrast(self) -> None:
        palette = tool_builder.compute_palette("vista")
        self.assertEqual(palette.field_bg, "#ffffff")
        self.assertEqual(palette.field_fg, "#1a1a1a")
        dark_palette = tool_builder.compute_palette("dark")
        self.assertNotEqual(dark_palette.field_bg, palette.field_bg)


if __name__ == "__main__":
    unittest.main()
