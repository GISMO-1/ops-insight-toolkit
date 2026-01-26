import unittest

from tools import throughput_model


class TestThroughputModel(unittest.TestCase):
    def test_known_case_output(self):
        inputs = throughput_model.ThroughputInputs(
            nominal_rate=100,
            minor_stops_per_hour=2,
            avg_minor_stop_min=3,
            changeovers_per_shift=1,
            changeover_min=30,
            shift_length_hours=8,
            staffing_factor=1.0,
        )
        results = throughput_model.compute_output(inputs)

        self.assertAlmostEqual(results["minor_stops"], 48.0)
        self.assertAlmostEqual(results["changeovers"], 30.0)
        self.assertAlmostEqual(results["expected_units"], 670.0)

    def test_negative_values_raise(self):
        inputs = throughput_model.ThroughputInputs(
            nominal_rate=-1,
            minor_stops_per_hour=1,
            avg_minor_stop_min=2,
            changeovers_per_shift=1,
            changeover_min=10,
            shift_length_hours=8,
            staffing_factor=1.0,
        )
        with self.assertRaises(throughput_model.ThroughputModelError):
            throughput_model.compute_output(inputs)


if __name__ == "__main__":
    unittest.main()
