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


if __name__ == "__main__":
    unittest.main()
