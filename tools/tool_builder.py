"""Tool Builder Wizard: build simple CSV analyses without coding.

README
Purpose: Provide a GUI wizard for loading CSV files, running lightweight analysis, and exporting results.
Inputs/Outputs: CSV input path(s), analysis settings, optional plugins, outputs results in the GUI and export files.
Example command: python -m tools.tool_builder
Self-check: python -m tools.tool_builder --self-check
"""

from __future__ import annotations

import argparse
import io
import json
import math
import queue
import tempfile
import threading
import zipfile
from dataclasses import dataclass
import importlib.util
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from tools import (
    csv_engine,
    optional_deps,
    tool_plugins,
    tool_sessions,
    tool_settings,
    tool_updater,
    tool_watchdog,
)

PANDAS_AVAILABLE, pd, _PANDAS_MESSAGE = optional_deps.try_import_pandas()
MATPLOTLIB_AVAILABLE, _mpl, _MATPLOTLIB_MESSAGE = optional_deps.try_import_matplotlib()


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
DENSITY_MODES = ["Comfortable", "Compact", "Large text"]
PLUGIN_FOLDER = Path(__file__).resolve().parent / "plugins"
SESSION_PATH = tool_sessions.default_session_path()


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


def _requires_pandas(operation: str) -> bool:
    return operation in {
        "SUM",
        "AVERAGE",
        "MAX",
        "MIN",
        "MOST FREQUENT",
        "MISSING DETECTION",
        "OUTLIER DETECTION",
        "TREND",
    }


def load_data(paths: list[str], mode: str, join_key: str | None) -> Any:
    if PANDAS_AVAILABLE and pd is not None:
        return merge_dataframes(paths, mode, join_key)
    return csv_engine.merge_tables(paths, mode, join_key)


def preview_data(data: Any, rows: int = 8) -> str:
    if PANDAS_AVAILABLE and pd is not None and isinstance(data, pd.DataFrame):
        return data.head(rows).to_string(index=False)
    if isinstance(data, csv_engine.CSVTable):
        return data.preview(rows=rows)
    return "(No preview available.)"


def apply_filters(data: Any, filters: list[FilterRule]) -> Any:
    if PANDAS_AVAILABLE and pd is not None and isinstance(data, pd.DataFrame):
        return apply_pandas_filters(data, filters)
    if isinstance(data, csv_engine.CSVTable):
        return csv_engine.apply_filters(data, [csv_engine.FilterRule(**rule.__dict__) for rule in filters])
    return data


def perform_operation(data: Any, selected_columns: list[str], group_by: list[str], operation: str) -> Any:
    if PANDAS_AVAILABLE and pd is not None and isinstance(data, pd.DataFrame):
        return perform_pandas_operation(data, selected_columns, group_by, operation)
    if operation != "COUNT":
        raise ValueError("This operation requires pandas. Install optional features to enable it.")
    if not isinstance(data, csv_engine.CSVTable):
        raise ValueError("No data loaded.")
    return csv_engine.group_count(data, group_by, selected_columns)


def merge_dataframes(paths: list[str], mode: str, join_key: str | None) -> Any:
    if not PANDAS_AVAILABLE or pd is None:
        raise RuntimeError("pandas is required for this operation.")
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
        merged: Any | None = None
        for path, df in zip(paths, dataframes):
            if join_key not in df.columns:
                raise ValueError(f"Join key '{join_key}' not found in {path}.")
            prefix = Path(path).stem
            renamed = df.rename(columns={col: f"{prefix}_{col}" for col in df.columns if col != join_key})
            merged = renamed if merged is None else pd.merge(merged, renamed, on=join_key, how="outer")
        if merged is None:
            raise ValueError("No data available to merge.")
        return merged
    raise ValueError(f"Unsupported merge mode: {mode}")


def load_dataframe(csv_path: str | Path) -> Any:
    if not PANDAS_AVAILABLE or pd is None:
        raise RuntimeError("pandas is required for this operation.")
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


def apply_pandas_filters(df: Any, filters: list[FilterRule]) -> Any:
    if not PANDAS_AVAILABLE or pd is None:
        raise RuntimeError("pandas is required for this operation.")
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


def _coerce_numeric(df: Any, columns: list[str]) -> Any:
    if not PANDAS_AVAILABLE or pd is None:
        raise RuntimeError("pandas is required for this operation.")
    numeric_df = df[columns].apply(pd.to_numeric, errors="coerce")
    non_numeric = [col for col in columns if numeric_df[col].notna().sum() == 0]
    if non_numeric:
        joined = ", ".join(non_numeric)
        raise ValueError(f"Selected columns are not numeric: {joined}")
    return numeric_df


def _columns_missing_numeric_values(df: Any, columns: list[str]) -> list[str]:
    if not PANDAS_AVAILABLE or pd is None:
        return []
    numeric_df = df[columns].apply(pd.to_numeric, errors="coerce")
    return [col for col in columns if numeric_df[col].notna().sum() == 0]


def suggest_columns(df: Any) -> dict[str, Any]:
    if not PANDAS_AVAILABLE or pd is None:
        return {"group_by": [], "numeric": [], "top_patterns": {}}
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


def _trend_slope(series: Any) -> float:
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


def perform_pandas_operation(
    df: Any,
    selected_columns: list[str],
    group_by: list[str],
    operation: str,
) -> Any:
    if not PANDAS_AVAILABLE or pd is None:
        raise RuntimeError("pandas is required for this operation.")
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
        return grouped[selected_columns].count() if grouped else df[selected_columns].count().to_frame().T
    if operation == "SUM":
        numeric_df = _coerce_numeric(df, selected_columns)
        return grouped[numeric_df.columns].sum() if grouped else numeric_df.sum().to_frame().T
    if operation == "AVERAGE":
        numeric_df = _coerce_numeric(df, selected_columns)
        return grouped[numeric_df.columns].mean() if grouped else numeric_df.mean().to_frame().T
    if operation == "MAX":
        numeric_df = _coerce_numeric(df, selected_columns)
        return grouped[numeric_df.columns].max() if grouped else numeric_df.max().to_frame().T
    if operation == "MIN":
        numeric_df = _coerce_numeric(df, selected_columns)
        return grouped[numeric_df.columns].min() if grouped else numeric_df.min().to_frame().T
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
        self.geometry("1100x780")
        self.minsize(980, 640)

        self.data: Any | None = None
        self.last_result: Any | None = None
        self.csv_paths: list[str] = []
        self.chart_config = tool_sessions.ChartConfig()
        self.plugins: list[tool_plugins.PluginTool] = []
        self._status_queue: queue.Queue[str] = queue.Queue()

        settings = tool_settings.load_settings(tool_settings.default_settings_path())

        self.csv_path_var = tk.StringVar(value=initial_csv or "")
        self.operation_var = tk.StringVar(value=OPERATIONS[0])
        self.filter_column_var = tk.StringVar()
        self.filter_operator_var = tk.StringVar(value=FILTER_OPERATORS[0])
        self.filter_value_var = tk.StringVar()
        self.merge_mode_var = tk.StringVar(value=MERGE_MODES[0])
        self.merge_key_var = tk.StringVar()
        self.chart_type_var = tk.StringVar(value=CHART_TYPES[0])
        self.chart_column_var = tk.StringVar()
        self.theme_var = tk.StringVar(value=ttk.Style().theme_use())
        self.density_var = tk.StringVar(value=DENSITY_MODES[0])
        self.status_var = tk.StringVar(value="Load a CSV to begin.")
        self.warning_var = tk.StringVar(value="")
        self.plugin_var = tk.StringVar(value="")
        self.auto_reload_csv_var = tk.BooleanVar(value=settings.auto_reload_csv)
        self.silent_csv_reload_var = tk.BooleanVar(value=settings.silent_csv_reload)
        self.auto_reload_plugins_var = tk.BooleanVar(value=settings.auto_reload_plugins)
        self.restore_session_var = tk.BooleanVar(value=settings.restore_last_session)
        self.auto_save_session_var = tk.BooleanVar(value=settings.auto_save_session)
        self.check_updates_var = tk.BooleanVar(value=settings.check_updates_on_launch)
        self.safe_mode_var = tk.BooleanVar(value=settings.safe_mode)
        self._base_font_size = tkfont.nametofont("TkDefaultFont").actual()["size"]
        self._csv_poll_interval = settings.csv_poll_interval
        self._csv_watcher: tool_watchdog.FileChangeWatcher | None = None
        self._plugin_watcher: tool_watchdog.DirectoryWatcher | None = None
        self._csv_reload_prompt_active = False
        self._update_check_in_progress = False
        self._last_update_check = "Never"
        self._density_padding = 8
        self._frames_with_padding: list[ttk.Labelframe] = []

        self._build_layout()
        self._initialize_watchers(self._csv_poll_interval)
        self._bind_setting_traces()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if initial_csv:
            self._load_csv([initial_csv])
        else:
            self.after(200, self._maybe_restore_session)
        self.after(400, self._maybe_check_updates_on_launch)
        self.after(500, self._drain_status_queue)
        self._set_empty_states()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="Tool Builder Wizard", font=("Segoe UI", 18, "bold"))
        subtitle = ttk.Label(header, text="Build quick CSV analyses using simple form inputs.")
        title.grid(row=0, column=0, sticky="w")
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(controls, text="Theme:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        theme_combo = ttk.Combobox(
            controls,
            textvariable=self.theme_var,
            values=sorted(ttk.Style().theme_names()),
            state="readonly",
            width=14,
        )
        theme_combo.grid(row=0, column=1, sticky="e", padx=(0, 12))
        ttk.Label(controls, text="Density:").grid(row=0, column=2, sticky="e", padx=(0, 6))
        density_combo = ttk.Combobox(
            controls,
            textvariable=self.density_var,
            values=DENSITY_MODES,
            state="readonly",
            width=14,
        )
        density_combo.grid(row=0, column=3, sticky="e")

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))

        self.data_tab = ttk.Frame(self.notebook)
        self.analyze_tab = ttk.Frame(self.notebook)
        self.results_tab = ttk.Frame(self.notebook)
        self.charts_tab = ttk.Frame(self.notebook)
        self.automation_tab = ttk.Frame(self.notebook)
        self.plugins_tab = ttk.Frame(self.notebook)

        for tab in [
            self.data_tab,
            self.analyze_tab,
            self.results_tab,
            self.charts_tab,
            self.automation_tab,
            self.plugins_tab,
        ]:
            tab.columnconfigure(0, weight=1)

        self.notebook.add(self.data_tab, text="Data")
        self.notebook.add(self.analyze_tab, text="Analyze")
        self.notebook.add(self.results_tab, text="Results")
        self.notebook.add(self.charts_tab, text="Charts")
        self.notebook.add(self.automation_tab, text="Automation")
        self.notebook.add(self.plugins_tab, text="Plugins")

        self._build_data_tab()
        self._build_analyze_tab()
        self._build_results_tab()
        self._build_charts_tab()
        self._build_automation_tab()
        self._build_plugins_tab()

        status_frame = ttk.Frame(self, padding=(12, 6))
        status_frame.grid(row=2, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        status_label = ttk.Label(status_frame, textvariable=self.status_var)
        status_label.grid(row=0, column=0, sticky="w")
        warning_label = ttk.Label(status_frame, textvariable=self.warning_var, foreground="#b54700")
        warning_label.grid(row=1, column=0, sticky="w")
        details_btn = ttk.Button(status_frame, text="Details…", command=self._open_diagnostics)
        details_btn.grid(row=0, column=1, rowspan=2, sticky="e")

        Tooltip(theme_combo, "Switch the Tk/ttk theme.")
        Tooltip(density_combo, "Adjust layout density and font size.")
        Tooltip(details_btn, "Open diagnostics for optional dependencies and watchers.")

        self.theme_var.trace_add("write", lambda *_args: self._apply_theme())
        self.density_var.trace_add("write", lambda *_args: self._apply_density())
        self._apply_theme()
        self._apply_density()
        self._reload_plugins()

        self.column_listbox.bind("<<ListboxSelect>>", lambda _event: self._validate_inputs())
        self.group_listbox.bind("<<ListboxSelect>>", lambda _event: self._validate_inputs())
        self.operation_combo.bind("<<ComboboxSelected>>", lambda _event: self._validate_inputs())
        self.filter_column_combo.bind("<<ComboboxSelected>>", lambda _event: self._validate_inputs())
        self.merge_mode_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.merge_key_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.filter_value_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.csv_path_var.trace_add("write", lambda *_args: self._validate_inputs())
        self.chart_type_var.trace_add("write", lambda *_args: self._render_chart())
        self.chart_column_var.trace_add("write", lambda *_args: self._render_chart())

    def _add_labelframe(self, parent: ttk.Frame, title: str, row: int) -> ttk.Labelframe:
        frame = ttk.Labelframe(parent, text=title, padding=(10, 8))
        frame.grid(row=row, column=0, sticky="nsew", padx=12, pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        self._frames_with_padding.append(frame)
        return frame

    def _build_data_tab(self) -> None:
        self.data_tab.rowconfigure(1, weight=1)

        file_frame = self._add_labelframe(self.data_tab, "Load CSV Files", 0)
        for col in range(4):
            file_frame.columnconfigure(col, weight=1)
        ttk.Label(file_frame, text="CSV Path:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        csv_entry = ttk.Entry(file_frame, textvariable=self.csv_path_var)
        csv_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4, pady=4)
        browse_btn = ttk.Button(file_frame, text="Browse", command=self._browse_csv)
        browse_btn.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        browse_multi_btn = ttk.Button(file_frame, text="Browse Multiple", command=self._browse_csvs)
        browse_multi_btn.grid(row=1, column=3, sticky="ew", padx=4, pady=4)
        load_btn = ttk.Button(file_frame, text="Load", command=self._load_csv_from_entry)
        load_btn.grid(row=2, column=3, sticky="ew", padx=4, pady=4)

        ttk.Label(file_frame, text="Merge Mode:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        merge_mode_combo = ttk.Combobox(
            file_frame,
            textvariable=self.merge_mode_var,
            values=MERGE_MODES,
            state="readonly",
        )
        merge_mode_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(file_frame, text="Join Key:").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        join_key_entry = ttk.Entry(file_frame, textvariable=self.merge_key_var)
        join_key_entry.grid(row=1, column=3, sticky="ew", padx=4, pady=4)

        preview_frame = self._add_labelframe(self.data_tab, "Preview", 1)
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview_text = tk.Text(preview_frame, height=10, wrap="none")
        preview_scroll = ttk.Scrollbar(preview_frame, command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=preview_scroll.set)
        self.preview_text.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        preview_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)

        Tooltip(browse_btn, "Browse for a CSV file.")
        Tooltip(browse_multi_btn, "Browse and select multiple CSV files.")
        Tooltip(load_btn, "Load the selected CSV file.")
        Tooltip(merge_mode_combo, "Pick how to combine multiple files.")
        Tooltip(join_key_entry, "Column name to join on when merging side-by-side.")

    def _build_analyze_tab(self) -> None:
        self.analyze_tab.rowconfigure(1, weight=1)
        self._analysis_widgets: list[tk.Widget] = []
        if not PANDAS_AVAILABLE:
            banner_frame = ttk.Frame(self.analyze_tab)
            banner_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
            banner_frame.columnconfigure(0, weight=1)
            banner = ttk.Label(
                banner_frame,
                text="Optional features disabled: pandas is not installed. You can still run COUNT analyses.",
                foreground="#b54700",
                padding=(12, 6),
            )
            banner.grid(row=0, column=0, sticky="w")
            install_btn = ttk.Button(banner_frame, text="Install optional features", command=self._open_install_help)
            install_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))

        columns_frame = self._add_labelframe(self.analyze_tab, "Select Columns", 1)
        columns_frame.columnconfigure(0, weight=1)
        columns_frame.columnconfigure(1, weight=1)
        columns_frame.rowconfigure(1, weight=1)

        ttk.Label(columns_frame, text="Analyze Columns:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.column_listbox = tk.Listbox(columns_frame, selectmode=tk.MULTIPLE, height=8)
        self.column_listbox.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Label(columns_frame, text="Group By:").grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.group_listbox = tk.Listbox(columns_frame, selectmode=tk.MULTIPLE, height=8)
        self.group_listbox.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

        operation_frame = self._add_labelframe(self.analyze_tab, "Operation", 2)
        operation_frame.columnconfigure(1, weight=1)
        ttk.Label(operation_frame, text="Operation:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.operation_combo = ttk.Combobox(
            operation_frame,
            textvariable=self.operation_var,
            values=OPERATIONS,
            state="readonly",
        )
        self.operation_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(operation_frame, text="Smart Suggest:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        suggest_btn = ttk.Button(operation_frame, text="Suggest Columns", command=self._smart_suggest)
        suggest_btn.grid(row=1, column=1, sticky="w", padx=4, pady=4)

        filter_frame = self._add_labelframe(self.analyze_tab, "Optional Filter", 3)
        for col in range(6):
            filter_frame.columnconfigure(col, weight=1)
        ttk.Label(filter_frame, text="Column:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.filter_column_combo = ttk.Combobox(filter_frame, textvariable=self.filter_column_var, state="readonly")
        self.filter_column_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(filter_frame, text="Operator:").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        operator_combo = ttk.Combobox(filter_frame, textvariable=self.filter_operator_var, values=FILTER_OPERATORS, state="readonly")
        operator_combo.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        ttk.Label(filter_frame, text="Value:").grid(row=0, column=4, sticky="w", padx=4, pady=4)
        value_entry = ttk.Entry(filter_frame, textvariable=self.filter_value_var)
        value_entry.grid(row=0, column=5, sticky="ew", padx=4, pady=4)
        clear_filter_btn = ttk.Button(filter_frame, text="Clear Filter", command=self._clear_filter)
        clear_filter_btn.grid(row=1, column=5, sticky="e", padx=4, pady=4)

        action_frame = self._add_labelframe(self.analyze_tab, "Actions", 4)
        for col in range(4):
            action_frame.columnconfigure(col, weight=1)
        self.run_btn = ttk.Button(action_frame, text="Run Analysis", command=self._run_analysis)
        self.run_btn.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.save_btn = ttk.Button(action_frame, text="Save Results", command=self._save_results)
        self.save_btn.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.copy_btn = ttk.Button(action_frame, text="Copy Results", command=self._copy_results)
        self.copy_btn.grid(row=0, column=2, sticky="ew", padx=4, pady=4)
        self.clear_btn = ttk.Button(action_frame, text="Clear Results", command=self._clear_results)
        self.clear_btn.grid(row=0, column=3, sticky="ew", padx=4, pady=4)

        recipe_save_btn = ttk.Button(action_frame, text="Save Recipe", command=self._save_recipe)
        recipe_save_btn.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        recipe_load_btn = ttk.Button(action_frame, text="Load Recipe", command=self._load_recipe)
        recipe_load_btn.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        batch_btn = ttk.Button(action_frame, text="Run Recipe Batch", command=self._run_recipe_batch)
        batch_btn.grid(row=1, column=2, sticky="ew", padx=4, pady=4)

        Tooltip(self.column_listbox, "Choose one or more columns to analyze.")
        Tooltip(self.group_listbox, "Optional: group results by these columns.")
        Tooltip(self.operation_combo, "Select the analysis operation to run.")
        Tooltip(self.filter_column_combo, "Optional: filter rows by a column.")
        Tooltip(operator_combo, "Comparison operator for filters.")
        Tooltip(value_entry, "Value to compare against the filter column.")
        Tooltip(self.run_btn, "Run the configured analysis.")
        Tooltip(self.save_btn, "Save results to CSV or TXT.")
        Tooltip(self.copy_btn, "Copy results to clipboard for Excel/email.")
        Tooltip(self.clear_btn, "Clear the current results.")
        Tooltip(suggest_btn, "Suggest useful groupings and highlight frequent values.")
        Tooltip(recipe_save_btn, "Save current configuration as a recipe JSON.")
        Tooltip(recipe_load_btn, "Load a saved recipe JSON.")
        Tooltip(batch_btn, "Run a recipe across a folder of CSVs.")
        self._analysis_widgets.extend(
            [
                self.column_listbox,
                self.group_listbox,
                self.operation_combo,
                self.filter_column_combo,
                operator_combo,
                value_entry,
                clear_filter_btn,
                self.run_btn,
                suggest_btn,
                recipe_save_btn,
                recipe_load_btn,
                batch_btn,
            ]
        )
        if not PANDAS_AVAILABLE:
            self.operation_var.set("COUNT")
            self.operation_combo.configure(values=["COUNT"])

    def _build_results_tab(self) -> None:
        self.results_tab.rowconfigure(0, weight=1)
        results_frame = self._add_labelframe(self.results_tab, "Results", 0)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        self.results_text = tk.Text(results_frame, wrap="none", height=16)
        results_scroll = ttk.Scrollbar(results_frame, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        results_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)

        helper_frame = self._add_labelframe(self.results_tab, "Summary", 1)
        helper_frame.columnconfigure(0, weight=1)
        ask_ai_btn = ttk.Button(helper_frame, text="Explain Data", command=self._explain_data)
        ask_ai_btn.grid(row=0, column=0, sticky="w", padx=4, pady=4)
        share_btn = ttk.Button(helper_frame, text="Share Analysis", command=self._share_analysis)
        share_btn.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        Tooltip(ask_ai_btn, "Summarize the current data in natural language.")
        Tooltip(share_btn, "Export a shareable ZIP with results and session files.")

    def _build_charts_tab(self) -> None:
        self.charts_tab.rowconfigure(1, weight=1)
        if not MATPLOTLIB_AVAILABLE:
            banner_frame = ttk.Frame(self.charts_tab)
            banner_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
            banner_frame.columnconfigure(0, weight=1)
            banner = ttk.Label(
                banner_frame,
                text="Charts are disabled because matplotlib is not installed.",
                foreground="#b54700",
                padding=(12, 6),
            )
            banner.grid(row=0, column=0, sticky="w")
            install_btn = ttk.Button(banner_frame, text="Install optional features", command=self._open_install_help)
            install_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))
            self.notebook.tab(self.charts_tab, state="disabled")
            return

        chart_controls = self._add_labelframe(self.charts_tab, "Chart Controls", 0)
        chart_controls.columnconfigure(1, weight=1)
        ttk.Label(chart_controls, text="Chart Type:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        chart_type_combo = ttk.Combobox(
            chart_controls,
            textvariable=self.chart_type_var,
            values=CHART_TYPES,
            state="readonly",
            width=10,
        )
        chart_type_combo.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(chart_controls, text="Value Column:").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.chart_column_combo = ttk.Combobox(
            chart_controls,
            textvariable=self.chart_column_var,
            state="readonly",
            width=18,
        )
        self.chart_column_combo.grid(row=0, column=3, sticky="w", padx=4, pady=4)
        chart_edit_btn = ttk.Button(chart_controls, text="Edit Chart", command=self._open_chart_editor)
        chart_edit_btn.grid(row=0, column=4, sticky="w", padx=4, pady=4)
        chart_export_btn = ttk.Button(chart_controls, text="Export PNG", command=self._export_chart_dialog)
        chart_export_btn.grid(row=0, column=5, sticky="w", padx=4, pady=4)

        chart_frame = self._add_labelframe(self.charts_tab, "Preview", 1)
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)
        self.chart_canvas = tk.Canvas(chart_frame, height=320, background="white")
        self.chart_canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        Tooltip(chart_type_combo, "Pick a chart type for preview.")
        Tooltip(self.chart_column_combo, "Choose which column to chart.")
        Tooltip(chart_edit_btn, "Adjust chart labels, colors, and display options.")
        Tooltip(chart_export_btn, "Export the current chart preview as a PNG image.")

    def _build_automation_tab(self) -> None:
        automation_frame = self._add_labelframe(self.automation_tab, "Automation Controls", 0)
        for col in range(2):
            automation_frame.columnconfigure(col, weight=1)
        auto_reload_csv_check = ttk.Checkbutton(
            automation_frame,
            text="Auto-reload CSV on change",
            variable=self.auto_reload_csv_var,
        )
        auto_reload_csv_check.grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.silent_reload_check = ttk.Checkbutton(
            automation_frame,
            text="Silent CSV reload",
            variable=self.silent_csv_reload_var,
        )
        self.silent_reload_check.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        auto_reload_plugins_check = ttk.Checkbutton(
            automation_frame,
            text="Auto-reload plugins",
            variable=self.auto_reload_plugins_var,
        )
        auto_reload_plugins_check.grid(row=1, column=0, sticky="w", padx=4, pady=4)
        restore_session_check = ttk.Checkbutton(
            automation_frame,
            text="Restore last session",
            variable=self.restore_session_var,
        )
        restore_session_check.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        auto_save_session_check = ttk.Checkbutton(
            automation_frame,
            text="Auto-save session on exit",
            variable=self.auto_save_session_var,
        )
        auto_save_session_check.grid(row=2, column=0, sticky="w", padx=4, pady=4)
        check_updates_check = ttk.Checkbutton(
            automation_frame,
            text="Check updates on launch",
            variable=self.check_updates_var,
        )
        check_updates_check.grid(row=2, column=1, sticky="w", padx=4, pady=4)
        safe_mode_check = ttk.Checkbutton(
            automation_frame,
            text="Safe mode (disable background watchers)",
            variable=self.safe_mode_var,
        )
        safe_mode_check.grid(row=3, column=0, sticky="w", padx=4, pady=4)

        update_frame = self._add_labelframe(self.automation_tab, "Update Checks", 1)
        update_frame.columnconfigure(1, weight=1)
        ttk.Label(update_frame, text="Last checked:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.last_checked_label = ttk.Label(update_frame, text=self._last_update_check)
        self.last_checked_label.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        check_updates_btn = ttk.Button(update_frame, text="Run now", command=self._check_for_updates)
        check_updates_btn.grid(row=0, column=2, sticky="e", padx=4, pady=4)

        session_frame = self._add_labelframe(self.automation_tab, "Session Tools", 2)
        save_session_btn = ttk.Button(session_frame, text="Save Session", command=self._save_session)
        save_session_btn.grid(row=0, column=0, sticky="w", padx=4, pady=4)
        load_session_btn = ttk.Button(session_frame, text="Load Session", command=self._load_session)
        load_session_btn.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        Tooltip(auto_reload_csv_check, "Watch the loaded CSV files for changes and reload them.")
        Tooltip(self.silent_reload_check, "Reload CSV files automatically without prompting.")
        Tooltip(auto_reload_plugins_check, "Watch the plugins folder for new or updated plugins.")
        Tooltip(restore_session_check, "Prompt to restore the last saved session on startup.")
        Tooltip(auto_save_session_check, "Save session state when closing the Tool Builder.")
        Tooltip(check_updates_check, "Check for updates automatically when launching the tool.")
        Tooltip(check_updates_btn, "Check GitHub for a newer Tool Builder version.")
        Tooltip(safe_mode_check, "Disable file watchers for troubleshooting.")
        Tooltip(save_session_btn, "Save the current session to a .moitsession.json file.")
        Tooltip(load_session_btn, "Load a saved .moitsession.json session file.")

    def _build_plugins_tab(self) -> None:
        plugin_frame = self._add_labelframe(self.plugins_tab, "Plugin Tools", 0)
        plugin_frame.columnconfigure(1, weight=1)
        self.plugin_status_label = ttk.Label(plugin_frame, text="")
        self.plugin_status_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 8))
        ttk.Label(plugin_frame, text="Plugin:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.plugin_combo = ttk.Combobox(plugin_frame, textvariable=self.plugin_var, state="readonly", width=30)
        self.plugin_combo.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        self.plugin_empty_label = ttk.Label(plugin_frame, text="")
        self.plugin_empty_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))
        plugin_run_btn = ttk.Button(plugin_frame, text="Run Plugin", command=self._run_plugin)
        plugin_run_btn.grid(row=1, column=2, sticky="w", padx=4, pady=4)
        plugin_reload_btn = ttk.Button(plugin_frame, text="Reload Plugins", command=self._reload_plugins)
        plugin_reload_btn.grid(row=2, column=2, sticky="w", padx=4, pady=4)
        install_btn = ttk.Button(plugin_frame, text="Install optional features", command=self._open_install_help)
        install_btn.grid(row=3, column=0, sticky="w", padx=4, pady=4)

        Tooltip(self.plugin_combo, "Select a plugin from the plugins folder.")
        Tooltip(plugin_run_btn, "Run the selected plugin against the loaded data.")
        Tooltip(plugin_reload_btn, "Reload plugins from the plugins folder.")

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
            self.data = load_data(paths, self.merge_mode_var.get(), self.merge_key_var.get().strip() or None)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            messagebox.showerror("CSV Load Error", str(exc))
            self.status_var.set(f"Error: {exc}")
            return
        self.csv_path_var.set("; ".join(paths))
        self.csv_paths = paths
        self._update_csv_watch(paths)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, preview_data(self.data))
        self._populate_columns()
        self._set_analyze_state(True)
        total_rows = len(self.data) if PANDAS_AVAILABLE and pd is not None and isinstance(self.data, pd.DataFrame) else len(self.data.rows)
        total_columns = len(self.data.columns) if isinstance(self.data, csv_engine.CSVTable) else len(self.data.columns)
        self.status_var.set(f"Loaded {total_rows} rows and {total_columns} columns.")
        self._validate_inputs()
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.data, pd.DataFrame):
            self._update_chart_options(pd.DataFrame())
        else:
            self._update_chart_options(None)

    def _resolve_csv_paths(self) -> list[str]:
        raw = self.csv_path_var.get().strip()
        if not raw:
            return self.csv_paths
        paths = [item.strip() for item in raw.replace("\n", ";").split(";") if item.strip()]
        return paths

    def _populate_columns(self) -> None:
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.data, pd.DataFrame):
            columns = list(self.data.columns)
        elif isinstance(self.data, csv_engine.CSVTable):
            columns = list(self.data.columns)
        else:
            columns = []
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
            elif self.data is not None:
                data_columns = self.data.columns if isinstance(self.data, csv_engine.CSVTable) else self.data.columns
                if join_key not in data_columns:
                    warnings.append(f"Join key '{join_key}' not found in loaded data.")
        if self.data is not None:
            selected_columns = self._selected_listbox_values(self.column_listbox)
            if not selected_columns:
                warnings.append("Select at least one column to analyze.")
            if PANDAS_AVAILABLE and pd is not None and self.operation_var.get() in NUMERIC_OPERATIONS and selected_columns:
                non_numeric = _columns_missing_numeric_values(self.data, selected_columns)
                if non_numeric:
                    warnings.append(f"Non-numeric columns selected: {', '.join(non_numeric)}.")
        filter_value = self.filter_value_var.get().strip()
        if self.filter_operator_var.get() in {">", ">=", "<", "<="} and filter_value:
            try:
                float(filter_value)
            except ValueError:
                warnings.append("Filter value should be numeric for comparison operators.")
        if not PANDAS_AVAILABLE and _requires_pandas(self.operation_var.get()):
            warnings.append("This operation requires pandas (optional dependency).")
        self.warning_var.set("Warnings: " + " ".join(warnings) if warnings else "")

    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        theme = self.theme_var.get()
        if theme in style.theme_names():
            style.theme_use(theme)

    def _apply_density(self) -> None:
        density = self.density_var.get()
        default_font = tkfont.nametofont("TkDefaultFont")
        if density == "Compact":
            self._density_padding = 6
            default_font.configure(size=max(9, self._base_font_size - 1))
        elif density == "Large text":
            self._density_padding = 10
            default_font.configure(size=self._base_font_size + 2)
        else:
            self._density_padding = 8
            default_font.configure(size=self._base_font_size)
        for frame in self._frames_with_padding:
            frame.configure(padding=(self._density_padding, self._density_padding - 2))

    def _smart_suggest(self) -> None:
        if not PANDAS_AVAILABLE or pd is None:
            messagebox.showinfo(
                "Suggestions Disabled",
                "Smart suggestions require pandas. Install optional dependencies to enable them.",
            )
            return
        if self.data is None or not isinstance(self.data, pd.DataFrame):
            messagebox.showwarning("No Data", "Load a CSV file before requesting suggestions.")
            return
        suggestions = suggest_columns(self.data)
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

    def _update_chart_options(self, result: Any | None) -> None:
        if not MATPLOTLIB_AVAILABLE:
            return
        if not PANDAS_AVAILABLE or pd is None or result is None:
            self.chart_column_combo["values"] = []
            self.chart_column_var.set("")
            return
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
        if not MATPLOTLIB_AVAILABLE:
            return
        self.chart_canvas.delete("all")
        if not (PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame)):
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
        if not MATPLOTLIB_AVAILABLE:
            messagebox.showinfo("Charts Disabled", "Install matplotlib to use chart previews.")
            return
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
        if not (PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame)):
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

    def _reload_plugins(self, status_message: str | None = None) -> None:
        PLUGIN_FOLDER.mkdir(parents=True, exist_ok=True)
        plugins, errors = tool_plugins.load_plugins(PLUGIN_FOLDER)
        self.plugins = plugins
        names = [plugin.name for plugin in plugins]
        if hasattr(self, "plugin_combo"):
            self.plugin_combo["values"] = names
        if names:
            self.plugin_var.set(names[0])
            self.plugin_empty_label.config(text="")
        else:
            self.plugin_var.set("")
            self.plugin_empty_label.config(text="No plugins found. Put .py files in tools/plugins/")
        status = tool_plugins.plugin_status()
        self.plugin_status_label.config(text=status.message)
        if hasattr(self, "plugin_var"):
            if status_message:
                self.status_var.set(status_message)
            else:
                self.status_var.set("Plugins loaded." if plugins else "No plugins found.")
        if errors:
            messagebox.showwarning("Plugin Load Issues", "\n".join(errors))

    def _initialize_watchers(self, interval: float) -> None:
        PLUGIN_FOLDER.mkdir(parents=True, exist_ok=True)
        self._csv_watcher = tool_watchdog.FileChangeWatcher([], interval, self._on_csv_files_changed)
        self._plugin_watcher = tool_watchdog.DirectoryWatcher(PLUGIN_FOLDER, interval, self._on_plugins_changed)
        if self.safe_mode_var.get():
            return
        if self.auto_reload_csv_var.get():
            self._csv_watcher.start()
        if self.auto_reload_plugins_var.get():
            self._plugin_watcher.start()
        self._update_silent_reload_state()

    def _bind_setting_traces(self) -> None:
        self.auto_reload_csv_var.trace_add("write", lambda *_args: self._handle_csv_watch_toggle())
        self.auto_reload_plugins_var.trace_add("write", lambda *_args: self._handle_plugin_watch_toggle())
        self.safe_mode_var.trace_add("write", lambda *_args: self._handle_safe_mode_toggle())

    def _handle_csv_watch_toggle(self) -> None:
        self._update_silent_reload_state()
        if not self._csv_watcher or self.safe_mode_var.get():
            return
        if self.auto_reload_csv_var.get():
            self._csv_watcher.start()
            self.status_var.set("CSV auto-reload enabled.")
        else:
            self._csv_watcher.stop()
            self.status_var.set("CSV auto-reload disabled.")

    def _handle_plugin_watch_toggle(self) -> None:
        if not self._plugin_watcher or self.safe_mode_var.get():
            return
        if self.auto_reload_plugins_var.get():
            self._plugin_watcher.start()
            self.status_var.set("Plugin auto-reload enabled.")
        else:
            self._plugin_watcher.stop()
            self.status_var.set("Plugin auto-reload disabled.")

    def _handle_safe_mode_toggle(self) -> None:
        if self.safe_mode_var.get():
            if self._csv_watcher:
                self._csv_watcher.stop()
            if self._plugin_watcher:
                self._plugin_watcher.stop()
            self.status_var.set("Safe mode enabled: watchers paused.")
        else:
            self._initialize_watchers(self._csv_poll_interval)
            self.status_var.set("Safe mode disabled: watchers active based on settings.")

    def _update_silent_reload_state(self) -> None:
        if hasattr(self, "silent_reload_check"):
            state = "normal" if self.auto_reload_csv_var.get() and not self.safe_mode_var.get() else "disabled"
            self.silent_reload_check.configure(state=state)

    def _update_csv_watch(self, paths: list[str]) -> None:
        if self._csv_watcher:
            self._csv_watcher.update_paths([Path(path) for path in paths])

    def _on_csv_files_changed(self, changed_paths: list[Path]) -> None:
        if not self.auto_reload_csv_var.get() or not self.csv_paths:
            return
        if self.safe_mode_var.get():
            return
        if self._csv_reload_prompt_active:
            return

        def prompt_reload() -> None:
            self._csv_reload_prompt_active = False
            if not self.auto_reload_csv_var.get() or self.safe_mode_var.get():
                return
            if self.silent_csv_reload_var.get():
                self._reload_current_csv(silent=True)
                return
            if messagebox.askyesno("CSV Updated", "CSV file has changed. Reload now?"):
                self._reload_current_csv(silent=False)

        self._csv_reload_prompt_active = True
        self.after(0, prompt_reload)

    def _reload_current_csv(self, silent: bool) -> None:
        if not self.csv_paths:
            return
        self.status_var.set("Reloading CSV data...")
        self._load_csv(self.csv_paths)
        if silent:
            self.status_var.set("CSV auto-reload complete.")

    def _on_plugins_changed(self, change: tool_watchdog.DirectoryChange) -> None:
        if not self.auto_reload_plugins_var.get() or self.safe_mode_var.get():
            return

        def reload_plugins() -> None:
            message_parts = []
            if change.added:
                message_parts.append(f"Added: {', '.join(sorted(change.added))}")
            if change.removed:
                message_parts.append(f"Removed: {', '.join(sorted(change.removed))}")
            if change.modified:
                message_parts.append(f"Updated: {', '.join(sorted(change.modified))}")
            status_message = "Plugins reloaded."
            if message_parts:
                status_message = f"Plugins reloaded. {' | '.join(message_parts)}"
            self._reload_plugins(status_message=status_message)

        self.after(0, reload_plugins)

    def _maybe_restore_session(self) -> None:
        if not self.restore_session_var.get():
            return
        if not SESSION_PATH.exists():
            return
        if messagebox.askyesno("Restore Session", "Restore the last session settings?"):
            self._load_session_from_path(SESSION_PATH, source="Auto-restored session")

    def _maybe_check_updates_on_launch(self) -> None:
        if self.check_updates_var.get():
            self._check_for_updates()

    def _check_for_updates(self) -> None:
        if self._update_check_in_progress:
            return
        self._update_check_in_progress = True
        self.status_var.set("Checking for updates...")

        def run_check() -> None:
            repo_path = Path(__file__).resolve().parents[1]
            version_path = tool_updater.default_version_path()
            result = tool_updater.check_for_updates(repo_path, version_path)
            self.after(0, lambda: self._handle_update_result(result))

        threading.Thread(target=run_check, daemon=True).start()

    def _handle_update_result(self, result: tool_updater.UpdateCheckResult) -> None:
        self._update_check_in_progress = False
        self._last_update_check = "Just now"
        self.last_checked_label.config(text=self._last_update_check)
        if result.status == "up_to_date":
            self.status_var.set(result.message)
            messagebox.showinfo("Update Check", result.message)
            return
        if result.status == "update_available":
            prompt = "New version available. Run 'git pull'?"
            if messagebox.askyesno("Update Available", prompt):
                self._run_git_pull()
            else:
                self.status_var.set("Update available but skipped.")
            return
        self.status_var.set(result.message)
        messagebox.showwarning("Update Check", result.message)

    def _run_git_pull(self) -> None:
        self.status_var.set("Running git pull...")

        def run_pull() -> None:
            repo_path = Path(__file__).resolve().parents[1]
            version_path = tool_updater.default_version_path()
            ok, message = tool_updater.run_git_pull(repo_path, version_path)
            self.after(0, lambda: self._finish_git_pull(ok, message))

        threading.Thread(target=run_pull, daemon=True).start()

    def _finish_git_pull(self, ok: bool, message: str) -> None:
        if ok:
            self.status_var.set("Update complete.")
            messagebox.showinfo("Update Complete", message)
        else:
            self.status_var.set("Update failed.")
            messagebox.showerror("Update Failed", message)

    def _build_session_payload(self) -> dict[str, Any]:
        return tool_sessions.build_session_payload(
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

    def _save_session_to_path(self, path: Path) -> None:
        payload = self._build_session_payload()
        tool_sessions.save_session(path, payload)

    def _load_session_from_path(self, path: Path, source: str) -> None:
        try:
            data = tool_sessions.load_session(path)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Session Error", f"Could not load session: {exc}")
            return
        self._apply_session_data(data, source)

    def _apply_session_data(self, data: dict[str, Any], source: str) -> None:
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
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
            self.results_text.insert(tk.END, self.last_result.to_string())
            self._update_chart_options(self.last_result)
            self._render_chart()
        elif isinstance(self.last_result, csv_engine.CSVTable):
            self.results_text.insert(tk.END, self.last_result.to_text())
        elif self.last_result is not None:
            self.results_text.insert(tk.END, str(self.last_result))
        self.status_var.set(source)
        self._validate_inputs()

    def _save_settings(self) -> None:
        settings = tool_settings.ToolBuilderSettings(
            restore_last_session=self.restore_session_var.get(),
            auto_save_session=self.auto_save_session_var.get(),
            auto_reload_csv=self.auto_reload_csv_var.get(),
            silent_csv_reload=self.silent_csv_reload_var.get(),
            auto_reload_plugins=self.auto_reload_plugins_var.get(),
            check_updates_on_launch=self.check_updates_var.get(),
            safe_mode=self.safe_mode_var.get(),
            csv_poll_interval=self._csv_poll_interval,
        )
        tool_settings.save_settings(tool_settings.default_settings_path(), settings)

    def _save_auto_session(self) -> None:
        if not self.auto_save_session_var.get():
            return
        try:
            self._save_session_to_path(SESSION_PATH)
        except OSError as exc:
            self.status_var.set(f"Auto-save failed: {exc}")

    def _on_close(self) -> None:
        self._save_auto_session()
        self._save_settings()
        if self._csv_watcher:
            self._csv_watcher.stop()
        if self._plugin_watcher:
            self._plugin_watcher.stop()
        self.destroy()

    def _run_plugin(self) -> None:
        if self.data is None:
            messagebox.showwarning("No Data", "Load a CSV file before running plugins.")
            return
        plugin_name = self.plugin_var.get()
        plugin = next((item for item in self.plugins if item.name == plugin_name), None)
        if plugin is None:
            messagebox.showwarning("Plugin Missing", "Select a valid plugin tool.")
            return
        if not PANDAS_AVAILABLE:
            messagebox.showwarning(
                "Plugin Disabled",
                "Plugins require pandas. Install optional dependencies to enable plugins.",
            )
            return
        try:
            filtered = apply_filters(self.data, self._current_filters())
        except ValueError as exc:
            messagebox.showerror("Filter Error", str(exc))
            return
        ok, result, error_text = tool_plugins.run_plugin_safe(plugin, filtered)
        if not ok:
            messagebox.showerror("Plugin Error", error_text)
            return
        self.last_result = result if PANDAS_AVAILABLE and pd is not None and isinstance(result, pd.DataFrame) else str(result)
        self.results_text.delete("1.0", tk.END)
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
            self.results_text.insert(tk.END, self.last_result.to_string())
            self._update_chart_options(self.last_result)
            self._render_chart()
        else:
            self.results_text.insert(tk.END, str(self.last_result))
        self.status_var.set(f"Plugin '{plugin.name}' completed.")

    def _save_session(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".moitsession.json",
            filetypes=[("MOIT Session", "*.moitsession.json")],
        )
        if not path:
            return
        try:
            self._save_session_to_path(Path(path))
        except OSError as exc:
            messagebox.showerror("Session Error", f"Could not save session: {exc}")
            return
        self.status_var.set(f"Session saved to {path}.")

    def _load_session(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MOIT Session", "*.moitsession.json")])
        if not path:
            return
        self._load_session_from_path(Path(path), source=f"Session loaded from {path}.")

    def _explain_data(self) -> None:
        if self.data is None:
            messagebox.showwarning("No Data", "Load a CSV file before asking for a summary.")
            return
        summary_text = self._build_data_summary()
        self._show_text_report("Explain This Data", summary_text)

    def _build_data_summary(self) -> str:
        if not (PANDAS_AVAILABLE and pd is not None and isinstance(self.data, pd.DataFrame)):
            return "Basic summary unavailable without pandas. Install optional dependencies for advanced summaries."
        df = self.data
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
        text_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        report.rowconfigure(0, weight=1)
        report.columnconfigure(0, weight=1)
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
        button_frame.grid(row=1, column=0, pady=(0, 12))
        save_btn = ttk.Button(button_frame, text="Save Summary", command=save_report)
        save_btn.grid(row=0, column=0, padx=6)
        close_btn = ttk.Button(button_frame, text="Close", command=report.destroy)
        close_btn.grid(row=0, column=1, padx=6)
        Tooltip(save_btn, "Save the summary text to a file.")
        Tooltip(close_btn, "Close the summary window.")

    def _share_analysis(self) -> None:
        if self.data is None:
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

            if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
                self.last_result.to_csv(result_path, index=True)
            elif isinstance(self.last_result, csv_engine.CSVTable):
                self.last_result.to_csv(result_path)
            else:
                result_path.write_text(str(self.last_result or ""), encoding="utf-8")

            chart_written = False
            if self._pillow_available() and PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
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
        if self.data is None:
            messagebox.showwarning("No Data", "Load a CSV file before running analysis.")
            return
        selected_columns = self._selected_listbox_values(self.column_listbox)
        group_by = self._selected_listbox_values(self.group_listbox)
        operation = self.operation_var.get()
        try:
            filtered = apply_filters(self.data, self._current_filters())
            result = perform_operation(filtered, selected_columns, group_by, operation)
        except ValueError as exc:
            messagebox.showerror("Analysis Error", str(exc))
            self.status_var.set(f"Error: {exc}")
            return
        self.last_result = result
        self.results_text.delete("1.0", tk.END)
        if PANDAS_AVAILABLE and pd is not None and isinstance(result, pd.DataFrame):
            self.results_text.insert(tk.END, result.to_string())
            self._update_chart_options(result)
            self._render_chart()
        elif isinstance(result, csv_engine.CSVTable):
            self.results_text.insert(tk.END, result.to_text())
        else:
            self.results_text.insert(tk.END, str(result))
        self.status_var.set("Analysis complete.")

    def _save_results(self) -> None:
        if self.last_result is None:
            messagebox.showwarning("No Results", "Run an analysis first.")
            return
        default_ext = ".csv" if isinstance(self.last_result, (csv_engine.CSVTable,)) else ".txt"
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
            default_ext = ".csv"
        path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            filetypes=[("CSV Files", "*.csv"), ("TSV Files", "*.tsv"), ("Text Files", "*.txt")],
        )
        if not path:
            return
        try:
            if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
                self.last_result.to_csv(path, index=True)
            elif isinstance(self.last_result, csv_engine.CSVTable):
                if path.endswith(".tsv"):
                    self.last_result.to_tsv(path)
                else:
                    self.last_result.to_csv(path)
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
        if PANDAS_AVAILABLE and pd is not None and isinstance(self.last_result, pd.DataFrame):
            text = self.last_result.to_string()
        elif isinstance(self.last_result, csv_engine.CSVTable):
            text = self.last_result.to_text()
        else:
            text = str(self.last_result)
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
                data_table = load_data([str(csv_path)], "Single file", None)
                filtered = apply_filters(data_table, filter_rules)
                result = perform_operation(filtered, selected_columns, group_by, operation)
            except ValueError as exc:
                messagebox.showerror("Batch Error", f"{csv_path.name}: {exc}")
                return
            if PANDAS_AVAILABLE and pd is not None and isinstance(result, pd.DataFrame):
                prepared = result.reset_index()
                prepared.insert(0, "Source File", csv_path.name)
                rows.append(prepared)
            elif isinstance(result, csv_engine.CSVTable):
                for row in result.rows:
                    row["Source File"] = csv_path.name
                rows.append(result)
        if not rows:
            messagebox.showwarning("Batch Results", "No results produced for the selected folder.")
            return
        if PANDAS_AVAILABLE and pd is not None:
            aggregated = pd.concat(rows, ignore_index=True)
            self.last_result = aggregated
            self.results_text.delete("1.0", tk.END)
            self.results_text.insert(tk.END, aggregated.to_string(index=False))
            self.status_var.set(f"Batch run complete for {len(rows)} files.")
            self._update_chart_options(aggregated)
            self._render_chart()
        else:
            combined_rows: list[dict[str, str]] = []
            columns: list[str] = []
            for table in rows:
                if isinstance(table, csv_engine.CSVTable):
                    if "Source File" not in table.columns:
                        table.columns.append("Source File")
                    for col in table.columns:
                        if col not in columns:
                            columns.append(col)
                    combined_rows.extend(table.rows)
            combined = csv_engine.CSVTable(columns=columns, rows=combined_rows)
            self.last_result = combined
            self.results_text.delete("1.0", tk.END)
            self.results_text.insert(tk.END, combined.to_text())
            self.status_var.set(f"Batch run complete for {len(rows)} files.")

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

    def _drain_status_queue(self) -> None:
        try:
            while True:
                message = self._status_queue.get_nowait()
                self.status_var.set(message)
        except queue.Empty:
            pass
        self.after(500, self._drain_status_queue)

    def _set_empty_states(self) -> None:
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, "Load a CSV to begin.")
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, "Run an analysis to see results here.")
        self._set_analyze_state(False)
        missing = []
        if not PANDAS_AVAILABLE:
            missing.append("pandas")
        if not MATPLOTLIB_AVAILABLE:
            missing.append("matplotlib")
        if missing:
            self.warning_var.set(f"Optional features missing: {', '.join(missing)}.")

    def _set_analyze_state(self, enabled: bool) -> None:
        for widget in getattr(self, "_analysis_widgets", []):
            try:
                if isinstance(widget, ttk.Combobox) and enabled:
                    widget.configure(state="readonly")
                else:
                    widget.configure(state="normal" if enabled else "disabled")
            except tk.TclError:
                pass

    def _open_diagnostics(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Diagnostics")
        dialog.geometry("520x320")
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)

        info_frame = ttk.Frame(dialog, padding=(12, 12))
        info_frame.grid(row=0, column=0, sticky="nsew")
        info_frame.columnconfigure(1, weight=1)
        ttk.Label(info_frame, text="Optional Dependencies", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Label(info_frame, text=f"pandas: {'Available' if PANDAS_AVAILABLE else 'Missing'}").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(info_frame, text=f"matplotlib: {'Available' if MATPLOTLIB_AVAILABLE else 'Missing'}").grid(
            row=2, column=0, sticky="w"
        )
        if not PANDAS_AVAILABLE:
            ttk.Label(info_frame, text=f"{_PANDAS_MESSAGE}").grid(row=1, column=1, sticky="w")
        if not MATPLOTLIB_AVAILABLE:
            ttk.Label(info_frame, text=f"{_MATPLOTLIB_MESSAGE}").grid(row=2, column=1, sticky="w")

        ttk.Label(info_frame, text="Watchers", font=("Segoe UI", 11, "bold")).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 6)
        )
        watcher_status = "Safe mode" if self.safe_mode_var.get() else "Active"
        ttk.Label(info_frame, text=f"Status: {watcher_status}").grid(row=4, column=0, sticky="w")
        ttk.Label(info_frame, text=f"CSV auto-reload: {self.auto_reload_csv_var.get()}").grid(
            row=5, column=0, sticky="w"
        )
        ttk.Label(info_frame, text=f"Plugin auto-reload: {self.auto_reload_plugins_var.get()}").grid(
            row=6, column=0, sticky="w"
        )

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=1, column=0, pady=(0, 12))
        close_btn = ttk.Button(button_frame, text="Close", command=dialog.destroy)
        close_btn.grid(row=0, column=0)

    def _open_install_help(self) -> None:
        messagebox.showinfo(
            "Install Optional Features",
            "Install optional features with:\n\n"
            "python -m pip install -r requirements-optional.txt",
        )


def self_check() -> tuple[bool, str]:
    try:
        data = csv_engine.CSVTable(
            columns=["Shift", "Duration"],
            rows=[{"Shift": "A", "Duration": "5"}, {"Shift": "B", "Duration": "7"}],
        )
        result = csv_engine.group_count(data, ["Shift"], ["Duration"])
        if not result.rows:
            return False, "Self-check failed: COUNT result empty."
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
