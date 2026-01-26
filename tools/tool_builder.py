"""Tool Builder Wizard: build simple CSV analyses without coding.

README
Purpose: Provide a GUI wizard for loading CSV files and running common analysis steps.
Inputs/Outputs: CSV input path; outputs results in the GUI and can export to CSV/TXT.
Example command: python tools/tool_builder.py
Self-check: python tools/tool_builder.py --self-check
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


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

        self.csv_path_var = tk.StringVar(value=initial_csv or "")
        self.operation_var = tk.StringVar(value=OPERATIONS[0])
        self.filter_column_var = tk.StringVar()
        self.filter_operator_var = tk.StringVar(value=FILTER_OPERATORS[0])
        self.filter_value_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Load a CSV to begin.")

        self._build_layout()
        if initial_csv:
            self._load_csv(initial_csv)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)

        header = ttk.Label(self, text="Tool Builder Wizard", font=("Segoe UI", 18, "bold"))
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        subtitle = ttk.Label(self, text="Build quick CSV analyses using simple form inputs.")
        subtitle.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        file_frame = ttk.LabelFrame(self, text="1) Load CSV File")
        file_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="CSV Path:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        csv_entry = ttk.Entry(file_frame, textvariable=self.csv_path_var)
        csv_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        browse_btn = ttk.Button(file_frame, text="Browse", command=self._browse_csv)
        browse_btn.grid(row=0, column=2, sticky="ew", padx=8, pady=8)
        load_btn = ttk.Button(file_frame, text="Load", command=self._load_csv_from_entry)
        load_btn.grid(row=0, column=3, sticky="ew", padx=8, pady=8)

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
        recipe_save_btn = ttk.Button(action_frame, text="Save Recipe", command=self._save_recipe)
        recipe_save_btn.grid(row=0, column=2, sticky="w", padx=4)
        recipe_load_btn = ttk.Button(action_frame, text="Load Recipe", command=self._load_recipe)
        recipe_load_btn.grid(row=0, column=3, sticky="w", padx=4)
        clear_btn = ttk.Button(action_frame, text="Clear Results", command=self._clear_results)
        clear_btn.grid(row=0, column=4, sticky="w", padx=4)

        result_frame = ttk.LabelFrame(self, text="4) Results")
        result_frame.grid(row=7, column=0, sticky="nsew", padx=16, pady=6)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.results_text = tk.Text(result_frame, wrap="none")
        results_scroll = ttk.Scrollbar(result_frame, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        results_scroll.grid(row=0, column=1, sticky="ns", pady=8)

        status_frame = ttk.Frame(self)
        status_frame.grid(row=8, column=0, sticky="ew", padx=16, pady=(4, 12))
        status_label = ttk.Label(status_frame, textvariable=self.status_var)
        status_label.pack(anchor="w")

        Tooltip(browse_btn, "Browse for a CSV file.")
        Tooltip(load_btn, "Load the selected CSV file.")
        Tooltip(self.column_listbox, "Choose one or more columns to analyze.")
        Tooltip(self.group_listbox, "Optional: group results by these columns.")
        Tooltip(operation_combo, "Select the analysis operation to run.")
        Tooltip(self.filter_column_combo, "Optional: filter rows by a column.")
        Tooltip(operator_combo, "Comparison operator for filters.")
        Tooltip(value_entry, "Value to compare against the filter column.")
        Tooltip(run_btn, "Run the configured analysis.")
        Tooltip(save_btn, "Save results to CSV or TXT.")
        Tooltip(recipe_save_btn, "Save current configuration as a recipe JSON.")
        Tooltip(recipe_load_btn, "Load a saved recipe JSON.")

        self.rowconfigure(7, weight=1)

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path:
            self.csv_path_var.set(path)

    def _load_csv_from_entry(self) -> None:
        path = self.csv_path_var.get().strip()
        if not path:
            messagebox.showwarning("Missing CSV", "Please choose a CSV file.")
            return
        self._load_csv(path)

    def _load_csv(self, path: str) -> None:
        try:
            self.df = load_dataframe(path)
        except (FileNotFoundError, ValueError) as exc:
            messagebox.showerror("CSV Load Error", str(exc))
            self.status_var.set(f"Error: {exc}")
            return
        self.csv_path_var.set(path)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert(tk.END, preview_dataframe(self.df))
        self._populate_columns()
        self.status_var.set(f"Loaded {len(self.df)} rows and {len(self.df.columns)} columns.")

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

    def _save_recipe(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        recipe = {
            "csv_path": self.csv_path_var.get(),
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
        csv_path = data.get("csv_path") or ""
        if csv_path:
            self._load_csv(csv_path)
        self.operation_var.set(data.get("operation", OPERATIONS[0]))
        self._set_listbox_selection(self.column_listbox, data.get("selected_columns", []))
        self._set_listbox_selection(self.group_listbox, data.get("group_by", []))
        filter_data = data.get("filter", {})
        self.filter_column_var.set(filter_data.get("column", ""))
        self.filter_operator_var.set(filter_data.get("operator", FILTER_OPERATORS[0]))
        self.filter_value_var.set(filter_data.get("value", ""))
        self.status_var.set(f"Loaded recipe from {path}.")

    def _set_listbox_selection(self, listbox: tk.Listbox, values: list[str]) -> None:
        listbox.selection_clear(0, tk.END)
        options = listbox.get(0, tk.END)
        for idx, option in enumerate(options):
            if option in values:
                listbox.selection_set(idx)

    def _clear_filter(self) -> None:
        self.filter_value_var.set("")
        self.status_var.set("Filter cleared.")

    def _clear_results(self) -> None:
        self.results_text.delete("1.0", tk.END)
        self.last_result = None
        self.status_var.set("Results cleared.")


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
