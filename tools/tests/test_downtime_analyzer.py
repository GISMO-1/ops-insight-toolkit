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

    def test_accepts_alias_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "alias.csv"
            fieldnames = [
                "event id",
                "start time",
                "end time",
                "duration minutes",
                "line area",
                "machine",
                "type",
                "reason",
                "shift label",
                "comment",
            ]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "event id": "EVT-0001",
                        "start time": "2026-01-05T08:00:00",
                        "end time": "2026-01-05T08:15:00",
                        "duration minutes": "15",
                        "line area": "Assembly",
                        "machine": "Line-01",
                        "type": "Mechanical",
                        "reason": "Jam clear",
                        "shift label": "Shift-Alpha",
                        "comment": "Reset completed.",
                    }
                )

            events = downtime_analyzer.load_events(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].shift, "Shift-Alpha")


if __name__ == "__main__":
    unittest.main()
