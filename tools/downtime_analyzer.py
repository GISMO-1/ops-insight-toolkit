"""Downtime pattern analyzer for synthetic downtime events."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List

REQUIRED_COLUMNS = [
    "event_id",
    "start_time",
    "end_time",
    "duration_min",
    "area",
    "equipment",
    "category",
    "cause",
    "shift",
    "notes",
]


@dataclass(frozen=True)
class DowntimeEvent:
    event_id: str
    start_time: datetime
    end_time: datetime
    duration_min: int
    area: str
    equipment: str
    category: str
    cause: str
    shift: str
    notes: str


class DowntimeAnalyzerError(ValueError):
    """Raised when downtime analyzer input is invalid."""


def _validate_columns(fieldnames: Iterable[str]) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise DowntimeAnalyzerError(
            "Missing required columns: " + ", ".join(missing)
        )


def load_events(path: str) -> List[DowntimeEvent]:
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DowntimeAnalyzerError("CSV file is missing a header row.")
        _validate_columns(reader.fieldnames)
        events: List[DowntimeEvent] = []
        for row in reader:
            start_time = datetime.fromisoformat(row["start_time"].strip())
            end_time = datetime.fromisoformat(row["end_time"].strip())
            duration_min = int(row["duration_min"].strip())
            actual_duration = int((end_time - start_time).total_seconds() / 60)
            if actual_duration != duration_min:
                raise DowntimeAnalyzerError(
                    f"Duration mismatch for event {row['event_id']}: "
                    f"expected {duration_min} min, got {actual_duration} min"
                )
            events.append(
                DowntimeEvent(
                    event_id=row["event_id"].strip(),
                    start_time=start_time,
                    end_time=end_time,
                    duration_min=duration_min,
                    area=row["area"].strip(),
                    equipment=row["equipment"].strip(),
                    category=row["category"].strip(),
                    cause=row["cause"].strip(),
                    shift=row["shift"].strip(),
                    notes=row["notes"].strip(),
                )
            )

    if not events:
        raise DowntimeAnalyzerError("No downtime events found in CSV.")

    return events


def _accumulate(events: Iterable[DowntimeEvent], key_fn) -> Dict[str, int]:
    totals: Dict[str, int] = defaultdict(int)
    for event in events:
        totals[key_fn(event)] += event.duration_min
    return dict(totals)


def compute_aggregations(events: Iterable[DowntimeEvent]) -> Dict[str, Dict[str, int]]:
    events_list = list(events)
    return {
        "by_cause": _accumulate(events_list, lambda event: event.cause),
        "by_equipment": _accumulate(events_list, lambda event: event.equipment),
        "by_shift": _accumulate(events_list, lambda event: event.shift),
        "by_hour": _accumulate(events_list, lambda event: str(event.start_time.hour)),
    }


def _format_ranked(title: str, data: Dict[str, int], total_minutes: int) -> List[str]:
    lines = [title]
    for name, minutes in sorted(data.items(), key=lambda item: item[1], reverse=True):
        percent = (minutes / total_minutes * 100) if total_minutes else 0
        lines.append(f"- {name}: {minutes} min ({percent:.1f}%)")
    return lines


def _format_simple(title: str, data: Dict[str, int]) -> List[str]:
    lines = [title]
    for name, minutes in sorted(data.items(), key=lambda item: item[0]):
        lines.append(f"- {name}: {minutes} min")
    return lines


def render_report(events: Iterable[DowntimeEvent]) -> str:
    events_list = list(events)
    total_minutes = sum(event.duration_min for event in events_list)
    aggregations = compute_aggregations(events_list)

    report_lines: List[str] = []
    report_lines.extend(_format_ranked("Top causes by downtime minutes:", aggregations["by_cause"], total_minutes))
    report_lines.append("")
    report_lines.extend(
        _format_ranked("Top equipment by downtime minutes:", aggregations["by_equipment"], total_minutes)
    )
    report_lines.append("")
    report_lines.extend(_format_simple("Downtime minutes by shift:", aggregations["by_shift"]))
    report_lines.append("")
    report_lines.extend(
        _format_simple("Hot hours (downtime minutes by hour):", aggregations["by_hour"])
    )
    return "\n".join(report_lines)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("Usage: python tools/downtime_analyzer.py <path/to/downtime.csv>")
        return 1

    try:
        events = load_events(argv[1])
    except (DowntimeAnalyzerError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    print(render_report(events))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
