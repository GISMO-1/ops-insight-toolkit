import csv
import tempfile
import unittest
from pathlib import Path

from tools import downtime_analyzer


class TestDowntimeAnalyzer(unittest.TestCase):
    def test_load_and_aggregate(self):
        sample_path = Path("data/sample_downtime.csv")
        events = downtime_analyzer.load_events(sample_path)
        aggregations = downtime_analyzer.compute_aggregations(events)

        self.assertTrue(events)
        self.assertIn("by_cause", aggregations)
        self.assertIn("by_equipment", aggregations)
        self.assertIn("by_shift", aggregations)
        self.assertIn("by_hour", aggregations)

    def test_missing_columns_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["event_id", "start_time"])
                writer.writeheader()
                writer.writerow({"event_id": "EVT-0001", "start_time": "2026-01-05T08:00:00"})

            with self.assertRaises(downtime_analyzer.DowntimeAnalyzerError):
                downtime_analyzer.load_events(path)


if __name__ == "__main__":
    unittest.main()
