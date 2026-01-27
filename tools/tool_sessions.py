"""Tool Builder Sessions: save/load shareable analysis sessions.

README
Purpose: Serialize Tool Builder sessions (inputs, filters, chart settings, and results) to JSON files.
Inputs/Outputs: Accepts session state fields + last-result data; outputs dictionaries and .moitsession.json files.
Example command: python -m tools.tool_sessions --self-check
Self-check: python -m tools.tool_sessions --self-check
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools import csv_engine, optional_deps


CHART_SORT_OPTIONS = ("Original", "Ascending", "Descending")
CHART_ROTATION_OPTIONS = (0, 45, 90)


@dataclass
class ChartConfig:
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    color: str = "#4a90e2"
    sort_order: str = CHART_SORT_OPTIONS[0]
    x_label_rotation: int = CHART_ROTATION_OPTIONS[0]
    show_data_labels: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "color": self.color,
            "sort_order": self.sort_order,
            "x_label_rotation": self.x_label_rotation,
            "show_data_labels": self.show_data_labels,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ChartConfig":
        if not payload:
            return cls()
        sort_order = payload.get("sort_order", CHART_SORT_OPTIONS[0])
        if sort_order not in CHART_SORT_OPTIONS:
            sort_order = CHART_SORT_OPTIONS[0]
        rotation = int(payload.get("x_label_rotation", CHART_ROTATION_OPTIONS[0]))
        if rotation not in CHART_ROTATION_OPTIONS:
            rotation = CHART_ROTATION_OPTIONS[0]
        return cls(
            title=str(payload.get("title", "")),
            x_label=str(payload.get("x_label", "")),
            y_label=str(payload.get("y_label", "")),
            color=str(payload.get("color", "#4a90e2")),
            sort_order=sort_order,
            x_label_rotation=rotation,
            show_data_labels=bool(payload.get("show_data_labels", False)),
        )


def _pandas_dataframe(value: Any) -> bool:
    ok, pd_module, _ = optional_deps.try_import_pandas()
    if not ok or pd_module is None:
        return False
    return isinstance(value, pd_module.DataFrame)


def serialize_last_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {"type": "none", "value": None}
    if _pandas_dataframe(result):
        return {"type": "dataframe", "value": result.to_dict(orient="split")}
    if isinstance(result, csv_engine.CSVTable):
        return {"type": "csv_table", "value": result.to_dict()}
    return {"type": "text", "value": str(result)}


def deserialize_last_result(payload: dict[str, Any]) -> Any:
    result_type = payload.get("type", "none")
    value = payload.get("value")
    if result_type == "dataframe" and isinstance(value, dict):
        ok, pd_module, _ = optional_deps.try_import_pandas()
        if ok and pd_module is not None:
            return pd_module.DataFrame(**value)
        return None
    if result_type == "csv_table" and isinstance(value, dict):
        return csv_engine.CSVTable.from_dict(value)
    if result_type == "text":
        return "" if value is None else str(value)
    return None


def build_session_payload(
    *,
    csv_paths: list[str],
    merge_mode: str,
    merge_key: str,
    selected_columns: list[str],
    group_by: list[str],
    operation: str,
    filter_data: dict[str, str],
    chart_config: ChartConfig,
    last_result: Any,
) -> dict[str, Any]:
    return {
        "csv_paths": csv_paths,
        "merge_mode": merge_mode,
        "merge_key": merge_key,
        "selected_columns": selected_columns,
        "group_by": group_by,
        "operation": operation,
        "filter": filter_data,
        "chart_config": chart_config.to_dict(),
        "last_result": serialize_last_result(last_result),
    }


def save_session(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_session(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def default_session_path() -> Path:
    return Path.home() / ".moit_tool_session.json"


def self_check() -> tuple[bool, str]:
    config = ChartConfig(title="Sample")
    payload = build_session_payload(
        csv_paths=["sample.csv"],
        merge_mode="Single file",
        merge_key="",
        selected_columns=["Value"],
        group_by=["Region"],
        operation="SUM",
        filter_data={"column": "", "operator": "=", "value": ""},
        chart_config=config,
        last_result=csv_engine.CSVTable(
            columns=["Region", "Value"],
            rows=[{"Region": "North", "Value": "10"}],
        ),
    )
    parsed_config = ChartConfig.from_dict(payload.get("chart_config"))
    if parsed_config.title != "Sample":
        return False, "ChartConfig round-trip failed."
    restored = deserialize_last_result(payload.get("last_result", {}))
    if not isinstance(restored, csv_engine.CSVTable):
        return False, "Result deserialize failed."
    return True, "Tool sessions self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder session utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick session self-check")
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
