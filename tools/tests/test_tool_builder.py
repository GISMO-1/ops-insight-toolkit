import unittest

import importlib.util

PANDAS_AVAILABLE = importlib.util.find_spec("pandas") is not None
if PANDAS_AVAILABLE:
    from tools import tool_builder
else:
    tool_builder = None


class ToolBuilderTests(unittest.TestCase):
    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas is required for Tool Builder tests")
    def test_self_check(self) -> None:
        assert tool_builder is not None
        ok, message = tool_builder.self_check()
        self.assertTrue(ok, message)

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas is required for Tool Builder tests")
    def test_count_grouped(self) -> None:
        import pandas as pd

        assert tool_builder is not None
        df = pd.DataFrame(
            {
                "Shift": ["A", "A", "B"],
                "Duration": [5, 7, 3],
                "Reason": ["Jam", "Reset", "Jam"],
            }
        )
        result = tool_builder.perform_operation(df, ["Duration"], ["Shift"], "COUNT")
        self.assertEqual(result.loc["A", "Duration"], 2)
        self.assertEqual(result.loc["B", "Duration"], 1)

    @unittest.skipUnless(PANDAS_AVAILABLE, "pandas is required for Tool Builder tests")
    def test_filter_contains(self) -> None:
        import pandas as pd

        assert tool_builder is not None
        df = pd.DataFrame({"Reason": ["Jam", "Reset", "Jam"]})
        filtered = tool_builder.apply_filters(
            df,
            [tool_builder.FilterRule("Reason", "contains", "jam")],
        )
        self.assertEqual(len(filtered), 2)


if __name__ == "__main__":
    unittest.main()
