"""Sample custom tool: CSV summary statistics.

README
Purpose: Provide simple summary statistics for CSV columns.
Inputs/Outputs: CSV input path; returns a text summary of numeric and categorical columns.
Example command: python tools/sample_custom_tool.py data/sample_downtime.csv
Self-check: python tools/sample_custom_tool.py --self-check
"""

from __future__ import annotations

import argparse
import csv
import statistics
import tempfile
from collections import Counter
from pathlib import Path


def get_tool_metadata() -> dict:
    return {
        "name": "Sample CSV Summary Tool",
        "description": "Computes summary stats for numeric columns and counts for categorical columns.",
        "input_type": "csv",
    }


def _read_rows(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")
    with file_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row.")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV file contains no data rows.")
    return reader.fieldnames, rows


def run_analysis(input_path: str) -> str:
    headers, rows = _read_rows(input_path)
    column_values: dict[str, list[str]] = {header: [] for header in headers}
    for row in rows:
        for header in headers:
            value = (row.get(header) or "").strip()
            if value:
                column_values[header].append(value)

    lines: list[str] = ["CSV Summary Statistics"]
    for header in headers:
        values = column_values[header]
        if not values:
            lines.append(f"\n{header}: no non-empty values")
            continue
        numeric_values: list[float] = []
        non_numeric = 0
        for value in values:
            try:
                numeric_values.append(float(value))
            except ValueError:
                non_numeric += 1
        lines.append(f"\n{header}:")
        if numeric_values:
            lines.append(f"- Count: {len(numeric_values)}")
            lines.append(f"- Mean: {statistics.mean(numeric_values):.2f}")
            lines.append(f"- Min: {min(numeric_values):.2f}")
            lines.append(f"- Max: {max(numeric_values):.2f}")
            if non_numeric:
                lines.append(f"- Non-numeric entries: {non_numeric}")
        else:
            counts = Counter(values)
            top_entries = ", ".join(f"{value} ({count})" for value, count in counts.most_common(3))
            lines.append(f"- Non-empty entries: {len(values)}")
            lines.append(f"- Unique values: {len(counts)}")
            lines.append(f"- Top values: {top_entries}")

    return "\n".join(lines)


def self_check() -> tuple[bool, str]:
    sample_csv = """col_a,col_b,col_c
1,Alpha,10
2,Alpha,20
3,Beta,30
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "sample.csv"
        path.write_text(sample_csv, encoding="utf-8")
        try:
            report = run_analysis(str(path))
        except (OSError, ValueError) as exc:
            return False, f"Self-check failed: {exc}"
    if "CSV Summary Statistics" not in report:
        return False, "Self-check failed: missing header in report."
    return True, "Self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize CSV columns.")
    parser.add_argument("csv", nargs="?", help="Path to CSV file")
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
        report = run_analysis(args.csv)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    print(report)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
