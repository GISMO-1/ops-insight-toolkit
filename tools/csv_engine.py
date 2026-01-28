"""CSV Engine: baseline CSV operations without optional dependencies.

README
Purpose: Provide a minimal CSV table engine for loading, filtering, grouping, and exporting data.
Inputs/Outputs: Inputs are CSV file paths or in-memory rows; outputs are CSVTable instances and text previews.
Example command: python -m tools.csv_engine --self-check
Self-check: python -m tools.csv_engine --self-check
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FilterRule:
    column: str
    operator: str
    value: str


@dataclass
class CSVTable:
    columns: list[str]
    rows: list[dict[str, str]]
    table_type: str = "csv_table"

    @classmethod
    def from_csv(cls, path: str | Path) -> "CSVTable":
        csv_path = Path(path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV file is missing headers.")
            rows = [
                {key: (value or "") for key, value in row.items()}
                for row in reader
            ]
        if not rows:
            raise ValueError("CSV file has no data rows.")
        return cls(columns=list(reader.fieldnames), rows=rows)

    def to_dict(self) -> dict[str, Any]:
        return {"columns": self.columns, "rows": self.rows, "table_type": self.table_type}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CSVTable":
        return cls(columns=list(payload.get("columns", [])), rows=list(payload.get("rows", [])))

    def preview(self, rows: int = 8) -> str:
        return format_table(self.columns, self.rows[:rows])

    def to_text(self) -> str:
        return format_table(self.columns, self.rows)

    def to_csv(self, path: str | Path) -> None:
        csv_path = Path(path)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(self.rows)

    def to_tsv(self, path: str | Path) -> None:
        csv_path = Path(path)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns, delimiter="\t")
            writer.writeheader()
            writer.writerows(self.rows)


def format_table(columns: list[str], rows: list[dict[str, str]]) -> str:
    if not columns:
        return "(No columns)"
    widths = [len(col) for col in columns]
    for row in rows:
        for idx, col in enumerate(columns):
            widths[idx] = max(widths[idx], len(str(row.get(col, ""))))
    header = " | ".join(col.ljust(widths[idx]) for idx, col in enumerate(columns))
    separator = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(str(row.get(col, "")).ljust(widths[idx]) for idx, col in enumerate(columns))
        for row in rows
    ]
    return "\n".join([header, separator, *body]) if rows else "\n".join([header, separator])


def merge_tables(paths: list[str], mode: str, join_key: str | None) -> CSVTable:
    if not paths:
        raise ValueError("Select at least one CSV file.")
    tables = [CSVTable.from_csv(path) for path in paths]
    if mode == "Single file":
        if len(tables) > 1:
            raise ValueError("Single file mode supports one CSV. Choose a merge mode for multiple files.")
        return tables[0]
    if mode == "Stack (concat)":
        columns: list[str] = []
        for table in tables:
            for col in table.columns:
                if col not in columns:
                    columns.append(col)
        rows: list[dict[str, str]] = []
        for table in tables:
            for row in table.rows:
                merged_row = {col: row.get(col, "") for col in columns}
                rows.append(merged_row)
        return CSVTable(columns=columns, rows=rows)
    if mode == "Side-by-side (join)":
        if not join_key:
            raise ValueError("Provide a join key column for side-by-side merges.")
        merged_rows: dict[str, dict[str, str]] = {}
        columns: list[str] = [join_key]
        for path, table in zip(paths, tables):
            if join_key not in table.columns:
                raise ValueError(f"Join key '{join_key}' not found in {path}.")
            prefix = Path(path).stem
            for col in table.columns:
                if col == join_key:
                    continue
                renamed = f"{prefix}_{col}"
                if renamed not in columns:
                    columns.append(renamed)
            for row in table.rows:
                key = row.get(join_key, "")
                merged_row = merged_rows.setdefault(key, {join_key: key})
                for col in table.columns:
                    if col == join_key:
                        continue
                    merged_row[f"{prefix}_{col}"] = row.get(col, "")
        rows = list(merged_rows.values())
        return CSVTable(columns=columns, rows=rows)
    raise ValueError(f"Unsupported merge mode: {mode}")


def apply_filters(table: CSVTable, filters: list[FilterRule]) -> CSVTable:
    if not filters:
        return CSVTable(columns=table.columns, rows=list(table.rows))

    def matches(row: dict[str, str]) -> bool:
        for rule in filters:
            value = row.get(rule.column, "")
            target = rule.value
            if rule.operator in {">", ">=", "<", "<="}:
                try:
                    left = float(value)
                    right = float(target)
                except ValueError:
                    return False
                if rule.operator == ">" and not left > right:
                    return False
                if rule.operator == ">=" and not left >= right:
                    return False
                if rule.operator == "<" and not left < right:
                    return False
                if rule.operator == "<=" and not left <= right:
                    return False
            elif rule.operator == "contains":
                if target.lower() not in value.lower():
                    return False
            elif rule.operator == "!=" and value == target:
                return False
            elif rule.operator == "=" and value != target:
                return False
        return True

    filtered_rows = [row for row in table.rows if matches(row)]
    if not filtered_rows:
        raise ValueError("Filters removed all rows. Adjust filter settings.")
    return CSVTable(columns=table.columns, rows=filtered_rows)


def group_count(table: CSVTable, group_by: list[str], selected_columns: list[str]) -> CSVTable:
    for col in selected_columns:
        if col not in table.columns:
            raise ValueError(f"Columns not found: {col}")
    for col in group_by:
        if col not in table.columns:
            raise ValueError(f"Group-by column '{col}' not found.")
    if not selected_columns:
        counts = _count_rows(table, group_by)
        return CSVTable(columns=list(group_by) + ["count"], rows=counts)
    groups: dict[tuple[str, ...], dict[str, int]] = {}
    for row in table.rows:
        key = tuple(row.get(col, "") for col in group_by)
        counts = groups.setdefault(key, {col: 0 for col in selected_columns})
        for col in selected_columns:
            if row.get(col, "") != "":
                counts[col] += 1
    result_columns = list(group_by) + [f"COUNT_{col}" for col in selected_columns]
    result_rows: list[dict[str, str]] = []
    for key, counts in groups.items():
        row = {col: key[idx] for idx, col in enumerate(group_by)}
        for col in selected_columns:
            row[f"COUNT_{col}"] = str(counts[col])
        result_rows.append(row)
    return CSVTable(columns=result_columns, rows=result_rows)


def _count_rows(table: CSVTable, group_by: list[str]) -> list[dict[str, str]]:
    if not group_by:
        return [{"count": str(len(table.rows))}]
    groups: dict[tuple[str, ...], int] = {}
    for row in table.rows:
        key = tuple(row.get(col, "") for col in group_by)
        groups[key] = groups.get(key, 0) + 1
    result_rows: list[dict[str, str]] = []
    for key, count in groups.items():
        row = {col: key[idx] for idx, col in enumerate(group_by)}
        row["count"] = str(count)
        result_rows.append(row)
    return result_rows


def self_check() -> tuple[bool, str]:
    data = CSVTable(
        columns=["Team", "Value"],
        rows=[
            {"Team": "A", "Value": "1"},
            {"Team": "A", "Value": ""},
            {"Team": "B", "Value": "2"},
        ],
    )
    filtered = apply_filters(data, [FilterRule("Team", "=", "A")])
    if len(filtered.rows) != 2:
        return False, "CSV filter failed."
    grouped = group_count(data, ["Team"], ["Value"])
    if not grouped.rows:
        return False, "CSV grouping failed."
    return True, "CSV engine self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CSV engine utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick CSV engine self-check")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1
    print("Run with --self-check for a quick validation.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
