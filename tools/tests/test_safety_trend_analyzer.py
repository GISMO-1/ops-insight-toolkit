import csv
import tempfile
import unittest
from pathlib import Path

from tools import safety_trend_analyzer


class TestSafetyTrendAnalyzer(unittest.TestCase):
    def test_analyze_sample_data(self):
        observations = safety_trend_analyzer.load_observations(
            "data/sample_safety_observations.csv"
        )
        data = safety_trend_analyzer.analyze(observations)

        self.assertGreater(data["total"], 0)
        self.assertGreater(len(data["counts"]), 0)
        self.assertGreater(len(data["weekly"]), 0)
        self.assertGreaterEqual(data["near_miss_count"], 0)

    def test_missing_columns_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["obs_id", "date"])
                writer.writeheader()
                writer.writerow({"obs_id": "OBS-0001", "date": "2026-01-01"})

            with self.assertRaises(safety_trend_analyzer.SafetyTrendError):
                safety_trend_analyzer.load_observations(path)

    def test_accepts_alias_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "alias.csv"
            fieldnames = [
                "observation id",
                "observation date",
                "line area",
                "type",
                "risk level",
                "near miss",
                "corrective action",
                "closure date",
                "comment",
            ]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "observation id": "OBS-0001",
                        "observation date": "2026-01-03",
                        "line area": "Packaging",
                        "type": "Housekeeping",
                        "risk level": "LOW",
                        "near miss": "TRUE",
                        "corrective action": "Updated floor markings",
                        "closure date": "",
                        "comment": "Follow-up next shift.",
                    }
                )

            observations = safety_trend_analyzer.load_observations(path)
            self.assertEqual(len(observations), 1)
            self.assertTrue(observations[0].near_miss)


if __name__ == "__main__":
    unittest.main()
