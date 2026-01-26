"""Safety observation trend analyzer for synthetic observations.

README
Purpose: Summarize safety observations by severity, area, and weekly trend.
Inputs/Outputs: CSV input path; returns a human-readable text report string.
Example command: python tools/safety_trend_analyzer.py data/sample_safety_observations.csv
Self-check: python tools/safety_trend_analyzer.py --self-check
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

REQUIRED_COLUMNS = {
    "obs_id": ["obs_id", "obs id", "observation_id", "observation id"],
    "date": ["date", "observation_date", "observation date"],
    "area": ["area", "line", "line_area", "line area", "department"],
    "category": ["category", "type"],
    "severity": ["severity", "risk", "risk_level", "risk level"],
    "near_miss": ["near_miss", "near miss", "near_miss_flag", "near miss flag"],
    "corrective_action": ["corrective_action", "corrective action", "action", "response"],
    "closed_date": ["closed_date", "closed date", "closure_date", "closure date"],
    "notes": ["notes", "note", "comments", "comment", "details"],
}

VALID_SEVERITIES = {"LOW", "MED", "HIGH"}
VALID_NEAR_MISS = {"TRUE", "FALSE"}


@dataclass(frozen=True)
class SafetyObservation:
    obs_id: str
    date: date
    area: str
    category: str
    severity: str
    near_miss: bool
    corrective_action: str
    closed_date: date | None
    notes: str


class SafetyTrendError(ValueError):
    """Raised when safety trend analyzer input is invalid."""


def get_tool_metadata() -> dict:
    return {
        "name": "Safety Observation Trend Analyzer",
        "description": "Highlights safety observation counts, severities, and weekly trends.",
        "input_type": "csv",
    }


def _normalize_column(name: str) -> str:
    return "".join(
        char.lower()
        for char in name.strip().replace("-", "_").replace(" ", "_")
        if char.isalnum() or char == "_"
    )


def _resolve_columns(fieldnames: Iterable[str]) -> dict[str, str]:
    normalized = {_normalize_column(name): name for name in fieldnames}
    resolved: dict[str, str] = {}
    missing = []
    for required, aliases in REQUIRED_COLUMNS.items():
        match = None
        for alias in aliases:
            normalized_alias = _normalize_column(alias)
            if normalized_alias in normalized:
                match = normalized[normalized_alias]
                break
        if match is None:
            missing.append(required)
        else:
            resolved[required] = match

    if missing:
        raise SafetyTrendError("Missing required columns: " + ", ".join(missing))

    return resolved


def load_observations(path: str) -> list[SafetyObservation]:
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SafetyTrendError("CSV file is missing a header row.")
        column_map = _resolve_columns(reader.fieldnames)

        observations: list[SafetyObservation] = []
        for row in reader:
            severity = row[column_map["severity"]].strip().upper()
            if severity not in VALID_SEVERITIES:
                raise SafetyTrendError(
                    f"Invalid severity '{row[column_map['severity']]}' in {row[column_map['obs_id']]}"
                )
            near_miss_value = row[column_map["near_miss"]].strip().upper()
            if near_miss_value not in VALID_NEAR_MISS:
                raise SafetyTrendError(
                    f"Invalid near_miss '{row[column_map['near_miss']]}' in {row[column_map['obs_id']]}"
                )

            closed_date_raw = row[column_map["closed_date"]].strip()
            closed_date_value = date.fromisoformat(closed_date_raw) if closed_date_raw else None

            observations.append(
                SafetyObservation(
                    obs_id=row[column_map["obs_id"]].strip(),
                    date=date.fromisoformat(row[column_map["date"]].strip()),
                    area=row[column_map["area"]].strip(),
                    category=row[column_map["category"]].strip(),
                    severity=severity,
                    near_miss=near_miss_value == "TRUE",
                    corrective_action=row[column_map["corrective_action"]].strip(),
                    closed_date=closed_date_value,
                    notes=row[column_map["notes"]].strip(),
                )
            )

    if not observations:
        raise SafetyTrendError("No observations found in CSV.")

    return observations


def analyze(observations: Iterable[SafetyObservation]) -> dict:
    observations_list = list(observations)
    counts = Counter(
        (obs.category, obs.severity) for obs in observations_list
    )
    near_miss_count = sum(obs.near_miss for obs in observations_list)
    total = len(observations_list)

    closed_days = [
        (obs.closed_date - obs.date).days
        for obs in observations_list
        if obs.closed_date
    ]
    open_count = sum(obs.closed_date is None for obs in observations_list)

    weekly = Counter(
        f"{obs.date.isocalendar().year}-W{obs.date.isocalendar().week:02d}"
        for obs in observations_list
    )

    return {
        "counts": counts,
        "near_miss_count": near_miss_count,
        "total": total,
        "closed_days": closed_days,
        "open_count": open_count,
        "weekly": weekly,
    }


def render_report(data: dict) -> str:
    lines = ["Counts by category and severity:"]
    for (category, severity), count in sorted(
        data["counts"].items(), key=lambda item: (item[0][0], item[0][1])
    ):
        lines.append(f"- {category} / {severity}: {count}")

    near_miss_rate = (data["near_miss_count"] / data["total"] * 100) if data["total"] else 0
    lines.append("")
    lines.append(
        f"Near-miss rate: {near_miss_rate:.1f}% "
        f"({data['near_miss_count']} of {data['total']})"
    )

    if data["closed_days"]:
        avg_close = statistics.mean(data["closed_days"])
        median_close = statistics.median(data["closed_days"])
        lines.append(
            "Time-to-close (days): "
            f"avg {avg_close:.1f}, median {median_close:.1f}; "
            f"open items: {data['open_count']}"
        )
    else:
        lines.append(
            f"Time-to-close (days): no closed items; open items: {data['open_count']}"
        )

    lines.append("")
    lines.append("Weekly trend (ISO week):")
    for week, count in sorted(data["weekly"].items()):
        lines.append(f"- {week}: {count}")

    return "\n".join(lines)


def run_analysis(input_path: str) -> str:
    observations = load_observations(input_path)
    return render_report(analyze(observations))


def self_check() -> tuple[bool, str]:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sample_path = os.path.join(repo_root, "data", "sample_safety_observations.csv")
    try:
        report = run_analysis(sample_path)
    except (SafetyTrendError, FileNotFoundError, OSError) as exc:
        return False, f"Self-check failed: {exc}"
    return True, f"Self-check passed ({len(report.splitlines())} report lines)."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze safety observation trends.")
    parser.add_argument("csv", nargs="?", help="Path to safety observations CSV")
    parser.add_argument("--self-check", action="store_true", help="Run a quick self-check")
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1

    if not args.csv:
        parser.print_usage()
        return 1

    try:
        print(run_analysis(args.csv))
    except (SafetyTrendError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
