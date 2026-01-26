"""Unified runner for MOIT tools."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _add_common_csv_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--csv", required=True, help="Path to a CSV file")


def _handle_downtime(args: argparse.Namespace) -> int:
    from tools import downtime_analyzer

    try:
        events = downtime_analyzer.load_events(args.csv)
    except (downtime_analyzer.DowntimeAnalyzerError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    print(downtime_analyzer.render_report(events))
    return 0


def _handle_throughput(args: argparse.Namespace) -> int:
    from tools import throughput_model

    return throughput_model.main(
        [
            "throughput_model",
            "--nominal-rate",
            str(args.nominal_rate),
            "--minor-stops-per-hour",
            str(args.minor_stops_per_hour),
            "--avg-minor-stop-min",
            str(args.avg_minor_stop_min),
            "--changeovers-per-shift",
            str(args.changeovers_per_shift),
            "--changeover-min",
            str(args.changeover_min),
            "--shift-length-hours",
            str(args.shift_length_hours),
            "--staffing-factor",
            str(args.staffing_factor),
        ]
    )


def _handle_safety(args: argparse.Namespace) -> int:
    from tools import safety_trend_analyzer

    return safety_trend_analyzer.main(["safety_trend_analyzer", args.csv])


def _handle_handoff_validate(args: argparse.Namespace) -> int:
    from tools import handoff_validator

    return handoff_validator.main(["handoff_validator", args.file])


def _handle_tests(_: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, "-m", "unittest"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MOIT tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    downtime_parser = subparsers.add_parser("downtime", help="Analyze downtime patterns")
    _add_common_csv_arg(downtime_parser)
    downtime_parser.set_defaults(func=_handle_downtime)

    throughput_parser = subparsers.add_parser(
        "throughput", help="Estimate throughput and sensitivity"
    )
    throughput_parser.add_argument("--nominal-rate", type=float, required=True)
    throughput_parser.add_argument("--minor-stops-per-hour", type=float, required=True)
    throughput_parser.add_argument("--avg-minor-stop-min", type=float, required=True)
    throughput_parser.add_argument("--changeovers-per-shift", type=float, required=True)
    throughput_parser.add_argument("--changeover-min", type=float, required=True)
    throughput_parser.add_argument("--shift-length-hours", type=float, required=True)
    throughput_parser.add_argument("--staffing-factor", type=float, default=1.0)
    throughput_parser.set_defaults(func=_handle_throughput)

    safety_parser = subparsers.add_parser(
        "safety", help="Analyze safety observation trends"
    )
    _add_common_csv_arg(safety_parser)
    safety_parser.set_defaults(func=_handle_safety)

    handoff_parser = subparsers.add_parser(
        "handoff-validate", help="Validate a shift handoff markdown file"
    )
    handoff_parser.add_argument("--file", required=True, help="Path to handoff markdown")
    handoff_parser.set_defaults(func=_handle_handoff_validate)

    test_parser = subparsers.add_parser("test", help="Run unit tests")
    test_parser.set_defaults(func=_handle_tests)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
