"""Safety observation trend analyzer for synthetic observations."""

from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

REQUIRED_COLUMNS = [
    "obs_id",
    "date",
    "area",
    "category",
    "severity",
    "near_miss",
    "corrective_action",
    "closed_date",
    "notes",
]

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


def _validate_columns(fieldnames: Iterable[str]) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise SafetyTrendError("Missing required columns: " + ", ".join(missing))


def load_observations(path: str) -> list[SafetyObservation]:
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SafetyTrendError("CSV file is missing a header row.")
        _validate_columns(reader.fieldnames)

        observations: list[SafetyObservation] = []
        for row in reader:
            severity = row["severity"].strip().upper()
            if severity not in VALID_SEVERITIES:
                raise SafetyTrendError(
                    f"Invalid severity '{row['severity']}' in {row['obs_id']}"
                )
            near_miss_value = row["near_miss"].strip().upper()
            if near_miss_value not in VALID_NEAR_MISS:
                raise SafetyTrendError(
                    f"Invalid near_miss '{row['near_miss']}' in {row['obs_id']}"
                )

            closed_date_raw = row["closed_date"].strip()
            closed_date_value = date.fromisoformat(closed_date_raw) if closed_date_raw else None

            observations.append(
                SafetyObservation(
                    obs_id=row["obs_id"].strip(),
                    date=date.fromisoformat(row["date"].strip()),
                    area=row["area"].strip(),
                    category=row["category"].strip(),
                    severity=severity,
                    near_miss=near_miss_value == "TRUE",
                    corrective_action=row["corrective_action"].strip(),
                    closed_date=closed_date_value,
                    notes=row["notes"].strip(),
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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python tools/safety_trend_analyzer.py <path/to/observations.csv>")
        return 1

    try:
        observations = load_observations(argv[1])
    except (SafetyTrendError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    print(render_report(analyze(observations)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
