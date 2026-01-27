"""Tool Builder Wizard: build simple CSV analyses without coding.

README
Purpose: Provide a GUI wizard for loading one or more CSV files, merging them, and running common analysis steps.
Inputs/Outputs: CSV input path(s), optional merge settings, and recipe batch options; outputs results in the GUI,
chart previews, and can export to CSV/TXT.
Example command: python tools/tool_builder.py data/sample.csv
Self-check: python tools/tool_builder.py --self-check
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import math
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from tools import tool_plugins, tool_sessions


OPERATIONS = [
    "COUNT",
    "SUM",
    "AVERAGE",
    "MAX",
    "MIN",
    "MOST FREQUENT",
    "MISSING DETECTION",
    "OUTLIER DETECTION",
    "TREND",
]

FILTER_OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "contains"]
MERGE_MODES = ["Single file", "Stack (concat)", "Side-by-side (join)"]
NUMERIC_OPERATIONS = {"SUM", "AVERAGE", "MAX", "MIN", "OUTLIER DETECTION", "TREND"}
CHART_TYPES = ["Bar", "Line", "Pie"]
THEME_MODES = ["Default", "Dark", "Large Fonts", "Compact"]
PLUGIN_FOLDER = Path(__file__).resolve().parent / "plugins"


@dataclass(frozen=True)
class FilterRule:
    column: str
    operator: str
    value: str


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tipwindow: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: tk.Event) -> None:
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + 16
        self.tipwindow = tk.Toplevel(self.widget)
        self.tipwindow.wm_overrideredirect(True)
        self.tipwindow.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tipwindow, text=self.text, background="#ffffe0", relief=tk.SOLID, borderwidth=1)
        label.pack(ipadx=6, ipady=2)

    def _hide(self, _event: tk.Event) -> None:
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


def get_tool_metadata() -> dict[str, str]:
    return {
        "name": "Tool Builder Wizard",
        "description": "GUI wizard to build lightweight CSV analyses without coding.",
        "input_type": "csv",
    }


def load_dataframe(csv_path: str | Path) -> pd.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")
    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - need to surface CSV parsing errors
        raise ValueError(f"Invalid CSV: {exc}") from exc
    if df.empty:
        raise ValueError("CSV file has no data rows.")
    return df


def merge_dataframes(paths: list[str], mode: str, join_key: str | None) -> pd.DataFrame:
    if not paths:
        raise ValueError("Select at least one CSV file.")
    dataframes = [load_dataframe(path) for path in paths]
    if mode == "Single file":
        if len(dataframes) > 1:
            raise ValueError("Single file mode supports one CSV. Choose a merge mode for multiple files.")
        return dataframes[0]
    if mode == "Stack (concat)":
        return pd.concat(dataframes, ignore_index=True, sort=False)
    if mode == "Side-by-side (join)":
        if not join_key:
            raise ValueError("Provide a join key column for side-by-side merges.")
        merged: pd.DataFrame | None = None
        for path, df in zip(paths, dataframes):
            if join_key not in df.columns:
                raise ValueError(f"Join key '{join_key}' not found in {path}.")
            prefix = Path(path).stem
            renamed = df.rename(
                columns={col: f"{prefix}_{col}" for col in df.columns if col != join_key},
            )
            merged = renamed if merged is None else pd.merge(merged, renamed, on=join_key, how="outer")
        if merged is None:
            raise ValueError("No data available to merge.")
        return merged
    raise ValueError(f"Unsupported merge mode: {mode}")


def preview_dataframe(df: pd.DataFrame, rows: int = 8) -> str:
    return df.head(rows).to_string(index=False)


def apply_filters(df: pd.DataFrame, filters: list[FilterRule]) -> pd.DataFrame:
    filtered = df.copy()
    for rule in filters:
        if not rule.column or not rule.operator:
            continue
        if rule.column not in filtered.columns:
            raise ValueError(f"Filter column '{rule.column}' not found.")
        series = filtered[rule.column]
        value = rule.value
        if rule.operator in {">", ">=", "<", "<="}:
            try:
                target = float(value)
            except ValueError as exc:
                raise ValueError(f"Filter value '{value}' must be numeric for {rule.operator}.") from exc
            numeric_series = pd.to_numeric(series, errors="coerce")
            if rule.operator == ">":
                mask = numeric_series > target
            elif rule.operator == ">=":
                mask = numeric_series >= target
            elif rule.operator == "<":
                mask = numeric_series < target
            else:
                mask = numeric_series <= target
        elif rule.operator == "contains":
            mask = series.astype(str).str.contains(value, case=False, na=False)
        elif rule.operator == "!=":
            mask = series.astype(str) != value
        else:
            mask = series.astype(str) == value
        filtered = filtered[mask]
    if filtered.empty:
        raise ValueError("Filters removed all rows. Adjust filter settings.")
    return filtered


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    numeric_df = df[columns].apply(pd.to_numeric, errors="coerce")
    non_numeric = [col for col in columns if numeric_df[col].notna().sum() == 0]
    if non_numeric:
        joined = ", ".join(non_numeric)
        raise ValueError(f"Selected columns are not numeric: {joined}")
    return numeric_df


def _columns_missing_numeric_values(df: pd.DataFrame, columns: list[str]) -> list[str]:
    numeric_df = df[columns].apply(pd.to_numeric, errors="coerce")
    return [col for col in columns if numeric_df[col].notna().sum() == 0]


def suggest_columns(df: pd.DataFrame) -> dict[str, Any]:
    row_count = len(df)
    suggestions: dict[str, Any] = {"group_by": [], "numeric": [], "top_patterns": {}}
    if row_count == 0:
        return suggestions
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    suggestions["numeric"] = numeric_columns
    candidate_columns = []
    for column in df.columns:
        unique_count = df[column].nunique(dropna=True)
        if 1 < unique_count <= min(12, max(2, row_count // 2)):
            candidate_columns.append(column)
    suggestions["group_by"] = candidate_columns
    if candidate_columns:
        target = candidate_columns[0]
        top_values = df[target].astype(str).value_counts(dropna=False).head(5)
        suggestions["top_patterns"] = {target: top_values.to_dict()}
    return suggestions


def _trend_slope(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_vals = list(range(n))
    x_mean = sum(x_vals) / n
    y_mean = sum(values) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, values))
    denominator = sum((x - x_mean) ** 2 for x in x_vals) or 1.0
    return numerator / denominator


def _trend_label(slope: float) -> str:
    if math.isclose(slope, 0.0, abs_tol=1e-3):
        return "Flat"
    return "Up" if slope > 0 else "Down"


def perform_operation(
    df: pd.DataFrame,
    selected_columns: list[str],
    group_by: list[str],
    operation: str,
) -> pd.DataFrame:
    if not selected_columns:
        raise ValueError("Select at least one column for analysis.")
    missing_cols = [col for col in selected_columns if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Columns not found: {', '.join(missing_cols)}")
    if group_by:
        for col in group_by:
            if col not in df.columns:
                raise ValueError(f"Group-by column '{col}' not found.")

    grouped = df.groupby(group_by) if group_by else None

    if operation == "COUNT":
        return (grouped[selected_columns].count() if grouped else df[selected_columns].count().to_frame().T)
    if operation == "SUM":
        numeric_df = _coerce_numeric(df, selected_columns)
        return (grouped[numeric_df.columns].sum() if grouped else numeric_df.sum().to_frame().T)
    if operation == "AVERAGE":
        numeric_df = _coerce_numeric(df, selected_columns)
        return (grouped[numeric_df.columns].mean() if grouped else numeric_df.mean().to_frame().T)
    if operation == "MAX":
        numeric_df = _coerce_numeric(df, selected_columns)
        return (grouped[numeric_df.columns].max() if grouped else numeric_df.max().to_frame().T)
    if operation == "MIN":
        numeric_df = _coerce_numeric(df, selected_columns)
        return (grouped[numeric_df.columns].min() if grouped else numeric_df.min().to_frame().T)
    if operation == "MOST FREQUENT":
        if grouped:
            result = grouped[selected_columns].agg(lambda s: s.mode().iat[0] if not s.mode().empty else "")
        else:
            result = df[selected_columns].apply(lambda s: s.mode().iat[0] if not s.mode().empty else "")
            result = result.to_frame().T
        return result
    if operation == "MISSING DETECTION":
        if grouped:
            result = grouped[selected_columns].apply(lambda g: g.isna().sum())
        else:
            result = df[selected_columns].isna().sum().to_frame().T
        return result
    if operation == "OUTLIER DETECTION":
        numeric_df = _coerce_numeric(df, selected_columns)
        rows: list[dict[str, Any]] = []
        grouped_iter = grouped if grouped else [("All Data", numeric_df)]
        for name, group in grouped_iter:
            for column in numeric_df.columns:
                series = pd.to_numeric(group[column], errors="coerce").dropna()
                if series.empty:
                    continue
                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                iqr = q3 - q1
                lower = q1 - 1.5 * iqr
                upper = q3 + 1.5 * iqr
                outliers = series[(series < lower) | (series > upper)].count()
                rows.append(
                    {
                        "Group": name,
                        "Column": column,
                        "Lower Bound": round(lower, 4),
                        "Upper Bound": round(upper, 4),
                        "Outlier Count": int(outliers),
                    }
                )
        return pd.DataFrame(rows)
    if operation == "TREND":
        numeric_df = _coerce_numeric(df, selected_columns)
        rows = []
        grouped_iter = grouped if grouped else [("All Data", numeric_df)]
        for name, group in grouped_iter:
            for column in numeric_df.columns:
                slope = _trend_slope(group[column])
                rows.append(
                    {
                        "Group": name,
                        "Column": column,
                        "Slope": round(slope, 4),
                        "Direction": _trend_label(slope),
                    }
                )
        return pd.DataFrame(rows)

    raise ValueError(f"Unsupported operation: {operation}")


class ToolBuilderApp(tk.Tk):
    def __init__(self, initial_csv: str | None = None) -> None:
        super().__init__()
        self.title("MOIT Tool Builder Wizard")
        self.geometry("1050x750")
        self.df: pd.DataFrame | None = None
        self.last_result: pd.DataFrame | str | None = None
        self.csv_paths: list[str] = []
        self.chart_config = tool_sessions.ChartConfig()
        self.plugins: list[tool_plugins.PluginTool] = []

        self.csv_path_var = tk.StringVar(value=initial_csv or "")
        self.operation_var = tk.StringVar(value=OPERATIONS[0])
        self.filter_column_var = tk.StringVar()
        self.filter_operator_var = tk.StringVar(value=FILTER_OPERATORS[0])
        self.filter_value_var = tk.StringVar()
        self.merge_mode_var = tk.StringVar(value=MERGE_MODES[0])
        self.merge_key_var = tk.StringVar()
        self.chart_type_var = tk.StringVar(value=CHART_TYPES[0])
        self.chart_column_var = tk.StringVar()
        self.theme_var = tk.StringVar(value=THEME_MODES[0])
        self.status_var = tk.StringVar(value="Load a CSV to begin.")
        self.warning_var = tk.StringVar(value="")
        self.plugin_var = tk.StringVar(value="")
        self._base_font_size = tkfont.nametofont("TkDefaultFont").actual()["size"]

        self._build_layout()
        if initial_csv:
            self._load_csv([initial_csv])

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)

        header = ttk.Label(self, text="Tool Builder Wizard", font=("Segoe UI", 18, "bold"))
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        subtitle = ttk.Label(self, text="Build quick CSV analyses using simple form inputs.")
        subtitle.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        theme_frame = ttk.Frame(self)
        theme_frame.grid(row=0, column=0, sticky="e", padx=16, pady=(16, 4))
        ttk.Label(theme_frame, text="Theme:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        theme_combo = ttk.Combobox(
            theme_frame,
            textvariable=self.theme_var,
            values=THEME_MODES,
            state="readonly",
            width=14,
        )
        theme_combo.grid(row=0, column=1, sticky="e")

        file_frame = ttk.LabelFrame(self, text="1) Load CSV File")
        file_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="CSV Path:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        csv_entry = ttk.Entry(file_frame, textvariable=self.csv_path_var)
        csv_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        browse_btn = ttk.Button(file_frame, text="Browse", command=self._browse_csv)
        browse_btn.grid(row=0, column=2, sticky="ew", padx=8, pady=8)
        browse_multi_btn = ttk.Button(file_frame, text="Browse Multiple", command=self._browse_csvs)
        browse_multi_btn.grid(row=0, column=3, sticky="ew", padx=8, pady=8)
        load_btn = ttk.Button(file_frame, text="Load", command=self._load_csv_from_entry)
        load_btn.grid(row=0, column=4, sticky="ew", padx=8, pady=8)

        ttk.Label(file_frame, text="Merge Mode:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        merge_mode_combo = ttk.Combobox(
            file_frame,
            textvariable=self.merge_mode_var,
            values=MERGE_MODES,
            state="readonly",
        )
        merge_mode_combo.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ttk.Label(file_frame, text="Join Key:").grid(row=1, column=2, sticky="w", padx=8, pady=6)
        join_key_entry = ttk.Entry(file_frame, textvariable=self.merge_key_var)
        join_key_entry.grid(row=1, column=3, sticky="ew", padx=8, pady=6)

        preview_frame = ttk.LabelFrame(self, text="2) Preview Data")
        preview_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=6)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_text = tk.Text(preview_frame, height=6, wrap="none")
        preview_scroll = ttk.Scrollbar(preview_frame, command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)
        self.preview_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        preview_scroll.grid(row=0, column=1, sticky="ns", pady=8)

        config_frame = ttk.LabelFrame(self, text="3) Configure Analysis")
        config_frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=6)
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(2, weight=1)

        ttk.Label(config_frame, text="Select Columns:").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.column_listbox = tk.Listbox(config_frame, selectmode=tk.MULTIPLE, height=6)
        self.column_listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        ttk.Label(config_frame, text="Group By:").grid(row=0, column=1, sticky="w", padx=8, pady=(8, 4))
        self.group_listbox = tk.Listbox(config_frame, selectmode=tk.MULTIPLE, height=6)
        self.group_listbox.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 8))

        ttk.Label(config_frame, text="Operation:").grid(row=0, column=2, sticky="w", padx=8, pady=(8, 4))
        operation_combo = ttk.Combobox(config_frame, textvariable=self.operation_var, values=OPERATIONS, state="readonly")
        operation_combo.grid(row=1, column=2, sticky="ew", padx=8, pady=(0, 8))

        filter_frame = ttk.LabelFrame(self, text="Optional Filter")
        filter_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=6)
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text="Column:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.filter_column_combo = ttk.Combobox(filter_frame, textvariable=self.filter_column_var, state="readonly")
        self.filter_column_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(filter_frame, text="Operator:").grid(row=0, column=2, sticky="w", padx=8, pady=6)
        operator_combo = ttk.Combobox(filter_frame, textvariable=self.filter_operator_var, values=FILTER_OPERATORS, state="readonly")
        operator_combo.grid(row=0, column=3, sticky="ew", padx=8, pady=6)

        ttk.Label(filter_frame, text="Value:").grid(row=0, column=4, sticky="w", padx=8, pady=6)
        value_entry = ttk.Entry(filter_frame, textvariable=self.filter_value_var)
        value_entry.grid(row=0, column=5, sticky="ew", padx=8, pady=6)
        clear_filter_btn = ttk.Button(filter_frame, text="Clear Filter", command=self._clear_filter)
        clear_filter_btn.grid(row=0, column=6, sticky="ew", padx=8, pady=6)

        action_frame = ttk.Frame(self)
        action_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(6, 2))
        action_frame.columnconfigure(0, weight=1)

        run_btn = ttk.Button(action_frame, text="Run Analysis", command=self._run_analysis)
        run_btn.grid(row=0, column=0, sticky="w", padx=4)
        save_btn = ttk.Button(action_frame, text="Save Results", command=self._save_results)
        save_btn.grid(row=0, column=1, sticky="w", padx=4)
        copy_btn = ttk.Button(action_frame, text="Copy Results", command=self._copy_results)
        copy_btn.grid(row=0, column=2, sticky="w", padx=4)
        suggest_btn = ttk.Button(action_frame, text="Smart Suggest", command=self._smart_suggest)
        suggest_btn.grid(row=0, column=3, sticky="w", padx=4)
        recipe_save_btn = ttk.Button(action_frame, text="Save Recipe", command=self._save_recipe)
        recipe_save_btn.grid(row=0, column=4, sticky="w", padx=4)
        recipe_load_btn = ttk.Button(action_frame, text="Load Recipe", command=self._load_recipe)
        recipe_load_btn.grid(row=0, column=5, sticky="w", padx=4)
        batch_btn = ttk.Button(action_frame, text="Run Recipe Batch", command=self._run_recipe_batch)
        batch_btn.grid(row=0, column=6, sticky="w", padx=4)
        clear_btn = ttk.Button(action_frame, text="Clear Results", command=self._clear_results)
        clear_btn.grid(row=0, column=7, sticky="w", padx=4)
        save_session_btn = ttk.Button(action_frame, text="Save Session", command=self._save_session)
        save_session_btn.grid(row=1, column=0, sticky="w", padx=4, pady=(6, 0))
        load_session_btn = ttk.Button(action_frame, text="Load Session", command=self._load_session)
        load_session_btn.grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
        ask_ai_btn = ttk.Button(action_frame, text="Ask AI", command=self._explain_data)
        ask_ai_btn.grid(row=1, column=2, sticky="w", padx=4, pady=(6, 0))
        share_btn = ttk.Button(action_frame, text="Share Analysis", command=self._share_analysis)
        share_btn.grid(row=1, column=3, sticky="w", padx=4, pady=(6, 0))

        plugin_frame = ttk.LabelFrame(self, text="Plugin Tools")
        plugin_frame.grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 6))
        plugin_frame.columnconfigure(1, weight=1)
        ttk.Label(plugin_frame, text="Plugin:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.plugin_combo = ttk.Combobox(plugin_frame, textvariable=self.plugin_var, state="readonly", width=30)
        self.plugin_combo.grid(row=0, column=1, sticky="w", padx=8, pady=6)
        plugin_run_btn = ttk.Button(plugin_frame, text="Run Plugin", command=self._run_plugin)
        plugin_run_btn.grid(row=0, column=2, sticky="w", padx=8, pady=6)
        plugin_reload_btn = ttk.Button(plugin_frame, text="Reload Plugins", command=self._reload_plugins)
        plugin_reload_btn.grid(row=0, column=3, sticky="w", padx=8, pady=6)

        result_frame = ttk.LabelFrame(self, text="4) Results")
        result_frame.grid(row=8, column=0, sticky="nsew", padx=16, pady=6)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        results_notebook = ttk.Notebook(result_frame)
        results_notebook.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        result_frame.rowconfigure(0, weight=1)

        table_frame = ttk.Frame(results_notebook)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.results_text = tk.Text(table_frame, wrap="none")
        results_scroll = ttk.Scrollbar(table_frame, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew")
        results_scroll.grid(row=0, column=1, sticky="ns")

        chart_frame = ttk.Frame(results_notebook)
        chart_controls = ttk.Frame(chart_frame)
        chart_controls.pack(anchor="w", pady=(0, 8))
        ttk.Label(chart_controls, text="Chart Type:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        chart_type_combo = ttk.Combobox(
            chart_controls,
            textvariable=self.chart_type_var,
            values=CHART_TYPES,
            state="readonly",
            width=10,
        )
        chart_type_combo.grid(row=0, column=1, sticky="w")
        ttk.Label(chart_controls, text="Value Column:").grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.chart_column_combo = ttk.Combobox(
            chart_controls,
            textvariable=self.chart_column_var,
            state="readonly",
            width=18,
        )
        self.chart_column_combo.grid(row=0, column=3, sticky="w")
        chart_edit_btn = ttk.Button(chart_controls, text="Edit Chart", command=self._open_chart_editor)
        chart_edit_btn.grid(row=0, column=4, sticky="w", padx=(12, 4))
        chart_export_btn = ttk.Button(chart_controls, text="Export PNG", command=self._export_chart_dialog)
        chart_export_btn.grid(row=0, column=5, sticky="w")
        self.chart_canvas = tk.Canvas(chart_frame, height=320, background="white")
        self.chart_canvas.pack(fill="both", expand=True)

        results_notebook.add(table_frame, text="Table")
        results_notebook.add(chart_frame, text="Chart Preview")

        status_frame = ttk.Frame(self)
        status_frame.grid(row=9, column=0, sticky="ew", padx=16, pady=(4, 12))
        status_label = ttk.Label(status_frame, textvariable=self.status_var)
        status_label.pack(anchor="w")
        warning_label = tk.Label(status_frame, textvariable=self.warning_var, fg="#b54700")
        warning_label.pack(anchor="w")

        Tooltip(browse_btn, "Browse for a CSV file.")
        Tooltip(browse_multi_btn, "Browse and select multiple CSV files.")
        Tooltip(load_btn, "Load the selected CSV file.")
        Tooltip(merge_mode_combo, "Pick how to combine multiple files.")
        Tooltip(join_key_entry, "Column name to join on when merging side-by-side.")
        Tooltip(self.column_listbox, "Choose one or more columns to analyze.")
        Tooltip(self.group_listbox, "Optional: group results by these columns.")
        Tooltip(operation_combo, "Select the analysis operation to run.")
        Tooltip(self.filter_column_combo, "Optional: filter rows by a column.")
        Tooltip(operator_combo, "Comparison operator for filters.")
        Tooltip(value_entry, "Value to compare against the filter column.")
        Tooltip(run_btn, "Run the configured analysis.")
        Tooltip(save_btn, "Save results to CSV or TXT.")
        Tooltip(copy_btn, "Copy results to clipboard for Excel/email.")
        Tooltip(suggest_btn, "Suggest useful groupings and highlight frequent values.")
        Tooltip(recipe_save_btn, "Save current configuration as a recipe JSON.")
        Tooltip(recipe_load_btn, "Load a saved recipe JSON.")
        Tooltip(batch_btn, "Run a recipe across a folder of CSVs.")
        Tooltip(save_session_btn, "Save the current session to a .moitsession.json file.")
        Tooltip(load_session_btn, "Load a saved .moitsession.json session file.")
        Tooltip(ask_ai_btn, "Summarize the current data in natural language.")
        Tooltip(share_btn, "Export a shareable ZIP with results and session files.")
        Tooltip(theme_combo, "Switch theme and typography modes.")
        Tooltip(chart_type_combo, "Pick a chart type for preview.")
        Tooltip(self.chart_column_combo, "Choose which column to chart.")
        Tooltip(chart_edit_btn, "Adjust chart labels, colors, and display options.")
        Tooltip(chart_export_btn, "Export the current chart preview as a PNG image.")
        Tooltip(self.plugin_combo, "Select a plugin from the plugins folder.")
        Tooltip(plugin_run_btn, "Run the selected plugin against the loaded data.")
        Tooltip(plugin_reload_btn, "Reload plugins from the plugins folder.")

        self.rowconfigure(8, weight=1)

        self.column_listbox.bind("<<ListboxSelect>>", lambda _event: self._validate_inputs())
        self.group_listbox.bind("<<ListboxSelect>>", lambda _event: self._validate_inputs())
        operation_combo.bind("<<ComboboxSelected>>", lambda _event: self._validate_inputs())
        self.filter_column_combo.bind("<<ComboboxSelected>>", lambda _event: self._validate_inputs())
        operator_combo.bind("<<ComboboxSelected>>", lambda _event: self._validate_inputs())
        self.merge_mode_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.merge_key_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.filter_value_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.csv_path_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.chart_type_var.trace_add("write", lambda *_args: self._render_chart())
        self.chart_column_var.trace_add("write", lambda *_args: self._render_chart())
        self.theme_var.trace_add("write", lambda *_args: self._apply_theme())
        self._apply_theme()
        self._reload_plugins()

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path:
            self.csv_path_var.set(path)
            self.csv_paths = [path]

    def _browse_csvs(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("CSV Files", "*.csv")])
        if paths:
            self.csv_paths = list(paths)
            self.csv_path_var.set("; ".join(paths))
            if len(paths) > 1 and self.merge_mode_var.get() == "Single file":
                self.merge_mode_var.set("Stack (concat)")

    def _load_csv_from_entry(self) -> None:
        paths = self._resolve_csv_paths()
        if not paths:
            messagebox.showwarning("Missing CSV", "Please choose a CSV file.")
            return
        self._load_csv(paths)

    def _load_csv(self, paths: list[str]) -> None:
        try:
            self.df = merge_dataframes(paths, self.merge_mode_var.get(), self.merge_key_var.get().strip() or None)
        except (FileNotFoundError, ValueError) as exc:
            messagebox.showerror("CSV Load Error", str(exc))
            self.status_var.set(f"Error: {exc}")
            return
        self.csv_path_var.set("; ".join(paths))
        self.csv_paths = paths
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, preview_dataframe(self.df))
        self._populate_columns()
        self.status_var.set(f"Loaded {len(self.df)} rows and {len(self.df.columns)} columns.")
        self._validate_inputs()
        self._update_chart_options(pd.DataFrame())

    def _resolve_csv_paths(self) -> list[str]:
        raw = self.csv_path_var.get().strip()
        if not raw:
            return self.csv_paths
        paths = [item.strip() for item in raw.replace("\n", ";").split(";") if item.strip()]
        return paths

    def _populate_columns(self) -> None:
        columns = list(self.df.columns) if self.df is not None else []
        for listbox in (self.column_listbox, self.group_listbox):
            listbox.delete(0, tk.END)
            for col in columns:
                listbox.insert(tk.END, col)
        self.filter_column_combo["values"] = columns
        if columns:
            self.filter_column_var.set(columns[0])
        else:
            self.filter_column_var.set("")

    def _selected_listbox_values(self, listbox: tk.Listbox) -> list[str]:
        return [listbox.get(i) for i in listbox.curselection()]

    def _current_filters(self) -> list[FilterRule]:
        if not self.filter_column_var.get().strip():
            return []
        if not self.filter_value_var.get().strip():
            return []
        return [
            FilterRule(
                column=self.filter_column_var.get(),
                operator=self.filter_operator_var.get(),
                value=self.filter_value_var.get(),
            )
        ]

    def _validate_inputs(self) -> None:
        warnings: list[str] = []
        if not self._resolve_csv_paths():
            warnings.append("Pick at least one CSV file.")
        merge_mode = self.merge_mode_var.get()
        if merge_mode == "Side-by-side (join)":
            join_key = self.merge_key_var.get().strip()
            if not join_key:
                warnings.append("Join key is required for side-by-side merges.")
            elif self.df is not None and join_key not in self.df.columns:
                warnings.append(f"Join key '{join_key}' not found in loaded data.")
        if self.df is not None:
            selected_columns = self._selected_listbox_values(self.column_listbox)
            if not selected_columns:
                warnings.append("Select at least one column to analyze.")
            if self.operation_var.get() in NUMERIC_OPERATIONS and selected_columns:
                non_numeric = _columns_missing_numeric_values(self.df, selected_columns)
                if non_numeric:
                    warnings.append(f"Non-numeric columns selected: {', '.join(non_numeric)}.")
        filter_value = self.filter_value_var.get().strip()
        if self.filter_operator_var.get() in {">", ">=", "<", "<="} and filter_value:
            try:
                float(filter_value)
            except ValueError:
                warnings.append("Filter value should be numeric for comparison operators.")
        self.warning_var.set("Warnings: " + " ".join(warnings) if warnings else "")

    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        theme = self.theme_var.get()
        default_font = tkfont.nametofont("TkDefaultFont")
        text_bg = "white"
        text_fg = "black"
        if theme == "Dark":
            style.configure(".", background="#1f1f1f", foreground="#f2f2f2")
            style.configure("TLabel", background="#1f1f1f", foreground="#f2f2f2")
            style.configure("TLabelframe", background="#1f1f1f", foreground="#f2f2f2")
            style.configure("TLabelframe.Label", background="#1f1f1f", foreground="#f2f2f2")
            text_bg = "#2a2a2a"
            text_fg = "#f2f2f2"
            default_font.configure(size=self._base_font_size)
        elif theme == "Large Fonts":
            style.configure(".", background="", foreground="")
            default_font.configure(size=self._base_font_size + 2)
        elif theme == "Compact":
            style.configure(".", background="", foreground="")
            default_font.configure(size=max(8, self._base_font_size - 2))
        else:
            style.configure(".", background="", foreground="")
            default_font.configure(size=self._base_font_size)
        self.results_text.configure(background=text_bg, foreground=text_fg)
        self.preview_text.configure(background=text_bg, foreground=text_fg)
        self.chart_canvas.configure(background="white" if theme != "Dark" else "#2a2a2a")

    def _smart_suggest(self) -> None:
        if self.df is None:
            messagebox.showwarning("No Data", "Load a CSV file before requesting suggestions.")
            return
        suggestions = suggest_columns(self.df)
        group_by = suggestions.get("group_by", [])
        numeric = suggestions.get("numeric", [])
        top_patterns = suggestions.get("top_patterns", {})
        lines = []
        if group_by:
            lines.append(f"Suggested group-by columns: {', '.join(group_by)}")
        if numeric:
            lines.append(f"Numeric columns: {', '.join(numeric)}")
        if top_patterns:
            for column, counts in top_patterns.items():
                patterns = ", ".join(f"{key} ({value})" for key, value in counts.items())
                lines.append(f"Top values in {column}: {patterns}")
        if not lines:
            lines.append("No suggestions available for the current data.")
        messagebox.showinfo("Smart Suggestions", "\n".join(lines))

    def _update_chart_options(self, result: pd.DataFrame) -> None:
        numeric_columns = result.select_dtypes(include="number").columns.tolist()
        self.chart_column_combo["values"] = numeric_columns
        if numeric_columns:
            if self.chart_column_var.get() not in numeric_columns:
                self.chart_column_var.set(numeric_columns[0])
        else:
            self.chart_column_var.set("")

    def _normalized_chart_color(self) -> str:
        color = self.chart_config.color.strip() or "#4a90e2"
        if color.startswith("#") and len(color) == 7:
            return color
        return "#4a90e2"

    def _generate_palette(self, base_color: str, count: int) -> list[str]:
        if not base_color.startswith("#") or len(base_color) != 7:
            base_color = "#4a90e2"
        red = int(base_color[1:3], 16)
        green = int(base_color[3:5], 16)
        blue = int(base_color[5:7], 16)
        palette = []
        for idx in range(count):
            factor = 0.85 + (idx % 5) * 0.03
            palette.append(
                f"#{min(255, int(red * factor)):02x}"
                f"{min(255, int(green * factor)):02x}"
                f"{min(255, int(blue * factor)):02x}"
            )
        return palette

    def _sorted_chart_data(self, labels: list[str], values: list[float]) -> tuple[list[str], list[float]]:
        sort_order = self.chart_config.sort_order
        if sort_order == "Original":
            return labels, values
        reverse = sort_order == "Descending"
        pairs = sorted(zip(labels, values), key=lambda item: item[1], reverse=reverse)
        if not pairs:
            return labels, values
        sorted_labels, sorted_values = zip(*pairs)
        return list(sorted_labels), list(sorted_values)

    def _render_chart(self) -> None:
        self.chart_canvas.delete("all")
        if not isinstance(self.last_result, pd.DataFrame):
            self.chart_canvas.create_text(10, 10, anchor="nw", text="No chartable data available.")
            return
        result = self.last_result
        if result.empty:
            self.chart_canvas.create_text(10, 10, anchor="nw", text="No data to chart.")
            return
        column = self.chart_column_var.get()
        if not column:
            self.chart_canvas.create_text(10, 10, anchor="nw", text="Select a numeric column to chart.")
            return
        chart_type = self.chart_type_var.get()
        labels = [str(label) for label in result.index.tolist()]
        values = pd.to_numeric(result[column], errors="coerce").fillna(0).tolist()
        labels, values = self._sorted_chart_data(labels, values)
        if len(values) > 20:
            self.chart_canvas.create_text(10, 10, anchor="nw", text="Chart preview limited to 20 points.")
            labels = labels[:20]
            values = values[:20]
        self.chart_canvas.update_idletasks()
        width = self.chart_canvas.winfo_width() or 600
        height = self.chart_canvas.winfo_height() or 320
        padding = 40
        top_padding = 40
        if self.chart_config.title:
            top_padding = 55
            self.chart_canvas.create_text(
                width / 2,
                16,
                text=self.chart_config.title,
                font=("Segoe UI", 12, "bold"),
            )
        if self.chart_config.x_label:
            self.chart_canvas.create_text(
                width / 2,
                height - 10,
                text=self.chart_config.x_label,
                font=("Segoe UI", 10),
            )
        if self.chart_config.y_label:
            self.chart_canvas.create_text(
                14,
                height / 2,
                text=self.chart_config.y_label,
                angle=90,
                font=("Segoe UI", 10),
            )
        base_color = self._normalized_chart_color()
        if chart_type == "Pie":
            total = sum(abs(value) for value in values)
            if total == 0:
                self.chart_canvas.create_text(10, 10, anchor="nw", text="Pie chart needs non-zero values.")
                return
            start_angle = 0
            radius = min(width, height) // 3
            center_x = width // 2
            center_y = height // 2
            palette = self._generate_palette(base_color, len(values))
            for idx, value in enumerate(values):
                extent = 360 * abs(value) / total
                color = palette[idx]
                self.chart_canvas.create_arc(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    start=start_angle,
                    extent=extent,
                    fill=color,
                    outline="",
                )
                if self.chart_config.show_data_labels:
                    label_text = f"{labels[idx]} ({value})"
                    self.chart_canvas.create_text(center_x, center_y + radius + 18 + idx * 14, text=label_text)
                start_angle += extent
            self.chart_canvas.create_text(10, height - 20, anchor="sw", text=" | ".join(labels))
            return
        max_value = max(values) if values else 1
        min_value = min(values) if values else 0
        value_range = max_value - min_value or 1
        if chart_type == "Bar":
            bar_width = (width - 2 * padding) / max(1, len(values))
            for idx, value in enumerate(values):
                x0 = padding + idx * bar_width
                x1 = x0 + bar_width * 0.8
                scaled = (value - min_value) / value_range
                y1 = height - padding
                y0 = y1 - scaled * (height - padding - top_padding)
                self.chart_canvas.create_rectangle(x0, y0, x1, y1, fill=base_color, outline="")
                if self.chart_config.show_data_labels:
                    self.chart_canvas.create_text((x0 + x1) / 2, y0 - 8, text=f"{value}")
        else:
            points = []
            for idx, value in enumerate(values):
                x = padding + idx * (width - 2 * padding) / max(1, len(values) - 1)
                scaled = (value - min_value) / value_range
                y = height - padding - scaled * (height - padding - top_padding)
                points.append((x, y))
            for idx in range(1, len(points)):
                self.chart_canvas.create_line(*points[idx - 1], *points[idx], fill=base_color, width=2)
            for idx, (x, y) in enumerate(points):
                self.chart_canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=base_color, outline="")
                if self.chart_config.show_data_labels:
                    self.chart_canvas.create_text(x, y - 10, text=f"{values[idx]}")
        for idx, label in enumerate(labels):
            x = padding + idx * (width - 2 * padding) / max(1, len(labels) - 1)
            self.chart_canvas.create_text(
                x,
                height - padding + 10,
                text=label,
                anchor="n",
                angle=self.chart_config.x_label_rotation,
            )

    def _open_chart_editor(self) -> None:
        editor = tk.Toplevel(self)
        editor.title("Chart Editor")
        editor.geometry("420x360")
        editor.transient(self)
        editor.grab_set()

        title_var = tk.StringVar(value=self.chart_config.title)
        x_label_var = tk.StringVar(value=self.chart_config.x_label)
        y_label_var = tk.StringVar(value=self.chart_config.y_label)
        color_var = tk.StringVar(value=self.chart_config.color)
        sort_var = tk.StringVar(value=self.chart_config.sort_order)
        rotation_var = tk.StringVar(value=str(self.chart_config.x_label_rotation))
        data_labels_var = tk.BooleanVar(value=self.chart_config.show_data_labels)

        ttk.Label(editor, text="Chart Title:").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        ttk.Entry(editor, textvariable=title_var).grid(row=0, column=1, sticky="ew", padx=12, pady=(12, 4))
        ttk.Label(editor, text="X Axis Label:").grid(row=1, column=0, sticky="w", padx=12, pady=4)
        ttk.Entry(editor, textvariable=x_label_var).grid(row=1, column=1, sticky="ew", padx=12, pady=4)
        ttk.Label(editor, text="Y Axis Label:").grid(row=2, column=0, sticky="w", padx=12, pady=4)
        ttk.Entry(editor, textvariable=y_label_var).grid(row=2, column=1, sticky="ew", padx=12, pady=4)
        ttk.Label(editor, text="Primary Color:").grid(row=3, column=0, sticky="w", padx=12, pady=4)
        ttk.Entry(editor, textvariable=color_var).grid(row=3, column=1, sticky="ew", padx=12, pady=4)
        ttk.Label(editor, text="Sort Order:").grid(row=4, column=0, sticky="w", padx=12, pady=4)
        sort_combo = ttk.Combobox(editor, textvariable=sort_var, values=tool_sessions.CHART_SORT_OPTIONS, state="readonly")
        sort_combo.grid(row=4, column=1, sticky="ew", padx=12, pady=4)
        ttk.Label(editor, text="X Label Rotation:").grid(row=5, column=0, sticky="w", padx=12, pady=4)
        rotation_combo = ttk.Combobox(
            editor,
            textvariable=rotation_var,
            values=[str(val) for val in tool_sessions.CHART_ROTATION_OPTIONS],
            state="readonly",
        )
        rotation_combo.grid(row=5, column=1, sticky="ew", padx=12, pady=4)
        data_label_check = ttk.Checkbutton(editor, text="Show data labels", variable=data_labels_var)
        data_label_check.grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=6)

        button_frame = ttk.Frame(editor)
        button_frame.grid(row=7, column=0, columnspan=2, pady=12)
        apply_btn = ttk.Button(
            button_frame,
            text="Apply",
            command=lambda: self._apply_chart_editor(
                editor,
                title_var.get(),
                x_label_var.get(),
                y_label_var.get(),
                color_var.get(),
                sort_var.get(),
                rotation_var.get(),
                data_labels_var.get(),
            ),
        )
        apply_btn.grid(row=0, column=0, padx=6)
        export_btn = ttk.Button(button_frame, text="Export PNG", command=self._export_chart_dialog)
        export_btn.grid(row=0, column=1, padx=6)
        close_btn = ttk.Button(button_frame, text="Close", command=editor.destroy)
        close_btn.grid(row=0, column=2, padx=6)

        editor.columnconfigure(1, weight=1)
        Tooltip(apply_btn, "Apply chart settings and refresh the preview.")
        Tooltip(export_btn, "Export the chart preview as a PNG file.")
        Tooltip(close_btn, "Close the chart editor.")

    def _apply_chart_editor(
        self,
        editor: tk.Toplevel,
        title: str,
        x_label: str,
        y_label: str,
        color: str,
        sort_order: str,
        rotation: str,
        show_labels: bool,
    ) -> None:
        self.chart_config = tool_sessions.ChartConfig(
            title=title.strip(),
            x_label=x_label.strip(),
            y_label=y_label.strip(),
            color=color.strip() or "#4a90e2",
            sort_order=sort_order if sort_order in tool_sessions.CHART_SORT_OPTIONS else "Original",
            x_label_rotation=(
                int(rotation)
                if rotation.isdigit() and int(rotation) in tool_sessions.CHART_ROTATION_OPTIONS
                else tool_sessions.CHART_ROTATION_OPTIONS[0]
            ),
            show_data_labels=show_labels,
        )
        self._render_chart()
        editor.focus_set()

    def _pillow_available(self) -> bool:
        return importlib.util.find_spec("PIL") is not None

    def _export_chart_dialog(self) -> None:
        if not self._pillow_available():
            messagebox.showwarning(
                "Export Unavailable",
                "PNG export requires Pillow. Install it or use a different system.",
            )
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if not path:
            return
        if self._export_chart_png(path):
            self.status_var.set(f"Chart exported to {path}.")

    def _export_chart_png(self, path: str) -> bool:
        if not self._pillow_available():
            return False
        if not isinstance(self.last_result, pd.DataFrame):
            messagebox.showwarning("No Chart", "Run an analysis to generate chart data.")
            return False
        from PIL import Image

        self.chart_canvas.update()
        ps_data = self.chart_canvas.postscript(colormode="color")
        try:
            image = Image.open(io.BytesIO(ps_data.encode("utf-8")))
            image.save(path, "png")
        except Exception as exc:  # noqa: BLE001 - surface export errors
            messagebox.showerror("Export Error", f"Could not export chart: {exc}")
            return False
        return True

    def _reload_plugins(self) -> None:
        PLUGIN_FOLDER.mkdir(parents=True, exist_ok=True)
        plugins, errors = tool_plugins.load_plugins(PLUGIN_FOLDER)
        self.plugins = plugins
        names = [plugin.name for plugin in plugins]
        if hasattr(self, "plugin_combo"):
            self.plugin_combo["values"] = names
        if names:
            self.plugin_var.set(names[0])
        else:
            self.plugin_var.set("")
        if hasattr(self, "plugin_var"):
            self.status_var.set("Plugins loaded." if plugins else "No plugins found.")
        if errors:
            messagebox.showwarning("Plugin Load Issues", "\n".join(errors))

    def _run_plugin(self) -> None:
        if self.df is None:
            messagebox.showwarning("No Data", "Load a CSV file before running plugins.")
            return
        plugin_name = self.plugin_var.get()
        plugin = next((item for item in self.plugins if item.name == plugin_name), None)
        if plugin is None:
            messagebox.showwarning("Plugin Missing", "Select a valid plugin tool.")
            return
        try:
            filtered = apply_filters(self.df, self._current_filters())
        except ValueError as exc:
            messagebox.showerror("Filter Error", str(exc))
            return
        ok, result, error_text = tool_plugins.run_plugin_safe(plugin, filtered)
        if not ok:
            messagebox.showerror("Plugin Error", error_text)
            return
        self.last_result = result if isinstance(result, pd.DataFrame) else str(result)
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, self.last_result.to_string() if isinstance(self.last_result, pd.DataFrame) else self.last_result)
        if isinstance(self.last_result, pd.DataFrame):
            self._update_chart_options(self.last_result)
            self._render_chart()
        self.status_var.set(f"Plugin '{plugin.name}' completed.")

    def _save_session(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".moitsession.json",
            filetypes=[("MOIT Session", "*.moitsession.json")],
        )
        if not path:
            return
        payload = tool_sessions.build_session_payload(
            csv_paths=self._resolve_csv_paths(),
            merge_mode=self.merge_mode_var.get(),
            merge_key=self.merge_key_var.get(),
            selected_columns=self._selected_listbox_values(self.column_listbox),
            group_by=self._selected_listbox_values(self.group_listbox),
            operation=self.operation_var.get(),
            filter_data={
                "column": self.filter_column_var.get(),
                "operator": self.filter_operator_var.get(),
                "value": self.filter_value_var.get(),
            },
            chart_config=self.chart_config,
            last_result=self.last_result,
        )
        try:
            tool_sessions.save_session(path, payload)
        except OSError as exc:
            messagebox.showerror("Session Error", f"Could not save session: {exc}")
            return
        self.status_var.set(f"Session saved to {path}.")

    def _load_session(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MOIT Session", "*.moitsession.json")])
        if not path:
            return
        try:
            data = tool_sessions.load_session(path)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Session Error", f"Could not load session: {exc}")
            return
        csv_paths = data.get("csv_paths") or []
        if csv_paths:
            self.merge_mode_var.set(data.get("merge_mode", MERGE_MODES[0]))
            self.merge_key_var.set(data.get("merge_key", ""))
            self._load_csv(csv_paths)
        self.operation_var.set(data.get("operation", OPERATIONS[0]))
        self._set_listbox_selection(self.column_listbox, data.get("selected_columns", []))
        self._set_listbox_selection(self.group_listbox, data.get("group_by", []))
        filter_data = data.get("filter", {})
        self.filter_column_var.set(filter_data.get("column", ""))
        self.filter_operator_var.set(filter_data.get("operator", FILTER_OPERATORS[0]))
        self.filter_value_var.set(filter_data.get("value", ""))
        self.chart_config = tool_sessions.ChartConfig.from_dict(data.get("chart_config", {}))
        self.last_result = tool_sessions.deserialize_last_result(data.get("last_result", {}))
        self.results_text.delete("1.0", tk.END)
        if isinstance(self.last_result, pd.DataFrame):
            self.results_text.insert(tk.END, self.last_result.to_string())
            self._update_chart_options(self.last_result)
            self._render_chart()
        elif self.last_result is not None:
            self.results_text.insert(tk.END, str(self.last_result))
            self._render_chart()
        self.status_var.set(f"Session loaded from {path}.")
        self._validate_inputs()

    def _explain_data(self) -> None:
        if self.df is None:
            messagebox.showwarning("No Data", "Load a CSV file before asking for a summary.")
            return
        summary_text = self._build_data_summary()
        self._show_text_report("Explain This Data", summary_text)

    def _build_data_summary(self) -> str:
        df = self.df
        if df is None:
            return "No data available."
        profiling_available = importlib.util.find_spec("ydata_profiling") is not None
        if profiling_available:
            from ydata_profiling import ProfileReport

            profile = ProfileReport(df, minimal=True, progress_bar=False)
            description = profile.get_description()
            overview = description.get("overview", {})
            text_lines = [
                "Automated Data Summary (ydata-profiling)",
                f"Rows: {overview.get('n', len(df))}",
                f"Columns: {overview.get('n_var', len(df.columns))}",
                "",
            ]
            for column, details in description.get("variables", {}).items():
                common = details.get("top")
                missing = details.get("n_missing")
                text_lines.append(f"{column}: top={common}, missing={missing}")
            return "\n".join(text_lines)
        profiling_available = importlib.util.find_spec("pandas_profiling") is not None
        if profiling_available:
            from pandas_profiling import ProfileReport

            profile = ProfileReport(df, minimal=True, progress_bar=False)
            description = profile.get_description()
            overview = description.get("overview", {})
            text_lines = [
                "Automated Data Summary (pandas-profiling)",
                f"Rows: {overview.get('n', len(df))}",
                f"Columns: {overview.get('n_var', len(df.columns))}",
                "",
            ]
            for column, details in description.get("variables", {}).items():
                common = details.get("top")
                missing = details.get("n_missing")
                text_lines.append(f"{column}: top={common}, missing={missing}")
            return "\n".join(text_lines)
        describe = df.describe(include="all").transpose()
        missing_counts = df.isna().sum()
        common_values = []
        for column in df.select_dtypes(exclude="number").columns:
            top_values = df[column].astype(str).value_counts().head(3).to_dict()
            common_values.append(f"{column}: {top_values}")
        outlier_lines = []
        for column in df.select_dtypes(include="number").columns:
            series = pd.to_numeric(df[column], errors="coerce").dropna()
            if series.empty:
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = series[(series < lower) | (series > upper)].count()
            outlier_lines.append(f"{column}: {outliers} outliers (bounds {lower:.2f} to {upper:.2f})")
        text_lines = [
            "Basic Data Summary",
            f"Rows: {len(df)}",
            f"Columns: {len(df.columns)}",
            "",
            "Missing values by column:",
            missing_counts.to_string(),
            "",
            "Common values (top 3):",
            "\n".join(common_values) if common_values else "No categorical columns found.",
            "",
            "Outlier scan:",
            "\n".join(outlier_lines) if outlier_lines else "No numeric columns found.",
            "",
            "Summary statistics:",
            describe.to_string(),
        ]
        return "\n".join(text_lines)

    def _show_text_report(self, title: str, text: str) -> None:
        report = tk.Toplevel(self)
        report.title(title)
        report.geometry("700x500")
        report.transient(self)
        report.grab_set()
        text_frame = ttk.Frame(report)
        text_frame.pack(fill="both", expand=True, padx=12, pady=12)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        report_text = tk.Text(text_frame, wrap="word")
        scroll = ttk.Scrollbar(text_frame, command=report_text.yview)
        report_text.configure(yscrollcommand=scroll.set)
        report_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        report_text.insert(tk.END, text)
        report_text.configure(state="disabled")

        def save_report() -> None:
            path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
            if not path:
                return
            Path(path).write_text(text, encoding="utf-8")
            self.status_var.set(f"Summary saved to {path}.")

        button_frame = ttk.Frame(report)
        button_frame.pack(pady=(0, 12))
        save_btn = ttk.Button(button_frame, text="Save Summary", command=save_report)
        save_btn.grid(row=0, column=0, padx=6)
        close_btn = ttk.Button(button_frame, text="Close", command=report.destroy)
        close_btn.grid(row=0, column=1, padx=6)
        Tooltip(save_btn, "Save the summary text to a file.")
        Tooltip(close_btn, "Close the summary window.")

    def _share_analysis(self) -> None:
        if self.df is None:
            messagebox.showwarning("No Data", "Load data before sharing analysis.")
            return
        zip_path = filedialog.asksaveasfilename(defaultextension=".zip", filetypes=[("ZIP Files", "*.zip")])
        if not zip_path:
            return
        temp_dir = Path(tempfile.mkdtemp())
        try:
            recipe_path = temp_dir / "recipe.json"
            session_path = temp_dir / "session.moitsession.json"
            result_path = temp_dir / "results.csv"
            chart_path = temp_dir / "chart.png"
            summary_path = temp_dir / "summary.txt"

            recipe = {
                "csv_paths": self._resolve_csv_paths(),
                "merge_mode": self.merge_mode_var.get(),
                "merge_key": self.merge_key_var.get(),
                "selected_columns": self._selected_listbox_values(self.column_listbox),
                "group_by": self._selected_listbox_values(self.group_listbox),
                "operation": self.operation_var.get(),
                "filter": {
                    "column": self.filter_column_var.get(),
                    "operator": self.filter_operator_var.get(),
                    "value": self.filter_value_var.get(),
                },
            }
            recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

            session_payload = tool_sessions.build_session_payload(
                csv_paths=self._resolve_csv_paths(),
                merge_mode=self.merge_mode_var.get(),
                merge_key=self.merge_key_var.get(),
                selected_columns=self._selected_listbox_values(self.column_listbox),
                group_by=self._selected_listbox_values(self.group_listbox),
                operation=self.operation_var.get(),
                filter_data=recipe["filter"],
                chart_config=self.chart_config,
                last_result=self.last_result,
            )
            tool_sessions.save_session(session_path, session_payload)

            if isinstance(self.last_result, pd.DataFrame):
                self.last_result.to_csv(result_path, index=True)
            else:
                result_path.write_text(str(self.last_result or ""), encoding="utf-8")

            chart_written = False
            if self._pillow_available() and isinstance(self.last_result, pd.DataFrame):
                chart_written = self._export_chart_png(str(chart_path))

            summary_text = "\n".join(
                [
                    "MOIT Tool Builder Share Summary",
                    f"CSV files: {', '.join(self._resolve_csv_paths())}",
                    f"Operation: {self.operation_var.get()}",
                    f"Group By: {', '.join(self._selected_listbox_values(self.group_listbox)) or 'None'}",
                    f"Chart Type: {self.chart_type_var.get()}",
                    f"Chart Exported: {'Yes' if chart_written else 'No'}",
                ]
            )
            summary_path.write_text(summary_text, encoding="utf-8")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.write(recipe_path, arcname=recipe_path.name)
                zip_file.write(session_path, arcname=session_path.name)
                zip_file.write(summary_path, arcname=summary_path.name)
                zip_file.write(result_path, arcname=result_path.name)
                if chart_written:
                    zip_file.write(chart_path, arcname=chart_path.name)
        finally:
            for item in temp_dir.glob("*"):
                item.unlink(missing_ok=True)
            temp_dir.rmdir()
        self.clipboard_clear()
        self.clipboard_append(zip_path)
        messagebox.showinfo("Share Analysis", f"ZIP exported to:\n{zip_path}\n(Path copied to clipboard.)")
        self.status_var.set(f"Shared analysis exported to {zip_path}.")

    def _run_analysis(self) -> None:
        if self.df is None:
            messagebox.showwarning("No Data", "Load a CSV file before running analysis.")
            return
        selected_columns = self._selected_listbox_values(self.column_listbox)
        group_by = self._selected_listbox_values(self.group_listbox)
        operation = self.operation_var.get()
        try:
            df = apply_filters(self.df, self._current_filters())
            result = perform_operation(df, selected_columns, group_by, operation)
        except ValueError as exc:
            messagebox.showerror("Analysis Error", str(exc))
            self.status_var.set(f"Error: {exc}")
            return
        self.last_result = result
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, result.to_string())
        self.status_var.set("Analysis complete.")
        self._update_chart_options(result)
        self._render_chart()

    def _save_results(self) -> None:
        if self.last_result is None:
            messagebox.showwarning("No Results", "Run an analysis first.")
            return
        default_ext = ".csv" if isinstance(self.last_result, pd.DataFrame) else ".txt"
        path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            filetypes=[("CSV Files", "*.csv"), ("Text Files", "*.txt")],
        )
        if not path:
            return
        try:
            if isinstance(self.last_result, pd.DataFrame):
                self.last_result.to_csv(path, index=True)
            else:
                Path(path).write_text(str(self.last_result), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Save Error", f"Could not save results: {exc}")
            self.status_var.set(f"Error: {exc}")
            return
        self.status_var.set(f"Results saved to {path}.")

    def _copy_results(self) -> None:
        if self.last_result is None:
            messagebox.showwarning("No Results", "Run an analysis first.")
            return
        text = self.last_result.to_string() if isinstance(self.last_result, pd.DataFrame) else str(self.last_result)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Results copied to clipboard.")

    def _run_recipe_batch(self) -> None:
        recipe_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not recipe_path:
            return
        folder = filedialog.askdirectory()
        if not folder:
            return
        try:
            data = json.loads(Path(recipe_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Recipe Error", f"Could not load recipe: {exc}")
            return
        merge_mode = data.get("merge_mode", MERGE_MODES[0])
        if merge_mode != "Single file":
            messagebox.showwarning(
                "Batch Limit",
                "Batch runs support single-file recipes. Adjust the recipe merge mode to Single file.",
            )
            return
        selected_columns = data.get("selected_columns", [])
        group_by = data.get("group_by", [])
        operation = data.get("operation", OPERATIONS[0])
        filter_data = data.get("filter", {})
        filter_rules = []
        if filter_data.get("column") and filter_data.get("value"):
            filter_rules.append(
                FilterRule(
                    column=filter_data.get("column", ""),
                    operator=filter_data.get("operator", FILTER_OPERATORS[0]),
                    value=filter_data.get("value", ""),
                )
            )
        rows = []
        for csv_path in sorted(Path(folder).glob("*.csv")):
            try:
                df = load_dataframe(csv_path)
                filtered = apply_filters(df, filter_rules)
                result = perform_operation(filtered, selected_columns, group_by, operation)
            except ValueError as exc:
                messagebox.showerror("Batch Error", f"{csv_path.name}: {exc}")
                return
            if result.empty:
                continue
            prepared = result.reset_index()
            prepared.insert(0, "Source File", csv_path.name)
            rows.append(prepared)
        if not rows:
            messagebox.showwarning("Batch Results", "No results produced for the selected folder.")
            return
        aggregated = pd.concat(rows, ignore_index=True)
        self.last_result = aggregated
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, aggregated.to_string(index=False))
        self.status_var.set(f"Batch run complete for {len(rows)} files.")
        self._update_chart_options(aggregated)
        self._render_chart()

    def _save_recipe(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        recipe = {
            "csv_paths": self._resolve_csv_paths(),
            "merge_mode": self.merge_mode_var.get(),
            "merge_key": self.merge_key_var.get(),
            "selected_columns": self._selected_listbox_values(self.column_listbox),
            "group_by": self._selected_listbox_values(self.group_listbox),
            "operation": self.operation_var.get(),
            "filter": {
                "column": self.filter_column_var.get(),
                "operator": self.filter_operator_var.get(),
                "value": self.filter_value_var.get(),
            },
        }
        try:
            Path(path).write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Recipe Error", f"Could not save recipe: {exc}")
            return
        self.status_var.set(f"Recipe saved to {path}.")

    def _load_recipe(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Recipe Error", f"Could not load recipe: {exc}")
            return
        csv_paths = data.get("csv_paths") or []
        csv_path = data.get("csv_path") or ""
        if csv_path and not csv_paths:
            csv_paths = [csv_path]
        self.merge_mode_var.set(data.get("merge_mode", MERGE_MODES[0]))
        self.merge_key_var.set(data.get("merge_key", ""))
        if csv_paths:
            self._load_csv(csv_paths)
        self.operation_var.set(data.get("operation", OPERATIONS[0]))
        self._set_listbox_selection(self.column_listbox, data.get("selected_columns", []))
        self._set_listbox_selection(self.group_listbox, data.get("group_by", []))
        filter_data = data.get("filter", {})
        self.filter_column_var.set(filter_data.get("column", ""))
        self.filter_operator_var.set(filter_data.get("operator", FILTER_OPERATORS[0]))
        self.filter_value_var.set(filter_data.get("value", ""))
        self.status_var.set(f"Loaded recipe from {path}.")
        self._validate_inputs()

    def _set_listbox_selection(self, listbox: tk.Listbox, values: list[str]) -> None:
        listbox.selection_clear(0, tk.END)
        options = listbox.get(0, tk.END)
        for idx, option in enumerate(options):
            if option in values:
                listbox.selection_set(idx)

    def _clear_filter(self) -> None:
        self.filter_value_var.set("")
        self.status_var.set("Filter cleared.")
        self._validate_inputs()

    def _clear_results(self) -> None:
        self.results_text.delete("1.0", tk.END)
        self.last_result = None
        self.status_var.set("Results cleared.")
        self._validate_inputs()
        self._render_chart()


def self_check() -> tuple[bool, str]:
    data = {
        "Shift": ["A", "A", "B", "B"],
        "Duration": [5, 10, 3, 12],
        "Reason": ["Jam", "Jam", "Reset", "Reset"],
    }
    df = pd.DataFrame(data)
    try:
        result = perform_operation(df, ["Duration"], ["Shift"], "SUM")
        if result.loc["A", "Duration"] != 15:
            return False, "Self-check failed: unexpected SUM result."
        filtered = apply_filters(df, [FilterRule("Shift", "=", "B")])
        if len(filtered) != 2:
            return False, "Self-check failed: filter count mismatch."
        with tempfile.TemporaryDirectory() as tmpdir:
            left_path = Path(tmpdir) / "left.csv"
            right_path = Path(tmpdir) / "right.csv"
            df[["Shift", "Duration"]].to_csv(left_path, index=False)
            df[["Shift", "Reason"]].to_csv(right_path, index=False)
            merged = merge_dataframes([str(left_path), str(right_path)], "Side-by-side (join)", "Shift")
            if "left_Duration" not in merged.columns:
                return False, "Self-check failed: merge result missing expected columns."
    except Exception as exc:  # noqa: BLE001 - surface for diagnostics
        return False, f"Self-check failed: {exc}"
    return True, "Self-check passed."


def run_analysis(input_path: str) -> str:
    app = ToolBuilderApp(initial_csv=input_path)
    app.mainloop()
    return "Tool Builder Wizard closed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Tool Builder Wizard GUI.")
    parser.add_argument("csv", nargs="?", help="Optional CSV file to preload")
    parser.add_argument("--self-check", action="store_true", help="Run a quick self-check")
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:])
    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1
    app = ToolBuilderApp(initial_csv=args.csv)
    app.mainloop()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
