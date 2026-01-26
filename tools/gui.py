"""Simple GUI wrapper for MOIT tools (Tkinter, no external dependencies).

Run:
  python -m tools.gui
or:
  python tools/gui.py

This GUI dynamically loads tool modules from the tools/ directory and displays results.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import tkinter as tk


# Allow running as a script from repo root: `python tools/gui.py ...`
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

APP_NAME = "MOIT"
APP_VERSION = "1.2.0"
SAMPLE_FILES = (
    ("data", "sample_downtime.csv"),
    ("data", "sample_safety_observations.csv"),
    ("docs", "sample_handoff.md"),
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


@dataclass(frozen=True)
class ToolInfo:
    module_name: str
    display_name: str
    description: str
    input_type: str
    module: object
    path: str


def _resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", REPO_ROOT)
    return os.path.join(base, *parts)


def _user_config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or os.path.expanduser("~")
    else:
        base = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def _default_output_dir() -> str:
    home = os.path.expanduser("~")
    desktop = os.path.join(home, "Desktop")
    base = desktop if os.path.isdir(desktop) else home
    return os.path.join(base, f"{APP_NAME}_Reports")


def _config_path() -> str:
    return os.path.join(_user_config_dir(), "moit_config.json")


def _log_path() -> str:
    return os.path.join(_user_config_dir(), "moit.log")


def _sample_dir() -> str:
    return os.path.join(_user_config_dir(), "samples")


def _load_config() -> dict[str, str | bool]:
    config = {
        "output_dir": _default_output_dir(),
        "log_to_file": True,
        "sample_dir": _sample_dir(),
        "tool_dev_mode": False,
    }
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            config.update({k: v for k, v in loaded.items() if k in config})
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        # Ignore malformed config; fall back to defaults
        pass
    return config


def _save_config(config: dict[str, str | bool]) -> None:
    os.makedirs(_user_config_dir(), exist_ok=True)
    path = _config_path()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)


def _open_path(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def _discover_tools() -> tuple[list[ToolInfo], list[str]]:
    tools_dir = os.path.join(REPO_ROOT, "tools")
    errors: list[str] = []
    candidates: list[tuple[str, str]] = []
    for filename in os.listdir(tools_dir):
        if not filename.endswith(".py"):
            continue
        module_name = filename[:-3]
        if module_name.startswith("_") or module_name in {"__init__", "gui", "run"}:
            continue
        path = os.path.join(tools_dir, filename)
        candidates.append((module_name, path))

    tools: list[ToolInfo] = []
    importlib.invalidate_caches()
    for module_name, path in sorted(candidates):
        try:
            module = importlib.import_module(f"tools.{module_name}")
        except Exception as exc:
            errors.append(f"Failed to import tools.{module_name}: {exc}")
            continue
        if not hasattr(module, "run_analysis"):
            continue
        metadata: dict = {}
        if hasattr(module, "get_tool_metadata"):
            try:
                metadata = module.get_tool_metadata() or {}
            except Exception as exc:
                errors.append(f"Failed to read metadata for tools.{module_name}: {exc}")
        display_name = metadata.get("name") or module_name.replace("_", " ").title()
        description = metadata.get("description") or ""
        input_type = metadata.get("input_type") or "csv"
        tools.append(
            ToolInfo(
                module_name=module_name,
                display_name=display_name,
                description=description,
                input_type=input_type,
                module=module,
                path=path,
            )
        )

    name_counts: dict[str, int] = {}
    for tool in tools:
        name_counts[tool.display_name] = name_counts.get(tool.display_name, 0) + 1
    updated_tools: list[ToolInfo] = []
    for tool in tools:
        display_name = tool.display_name
        if name_counts.get(display_name, 0) > 1:
            display_name = f"{display_name} ({tool.module_name})"
        updated_tools.append(
            ToolInfo(
                module_name=tool.module_name,
                display_name=display_name,
                description=tool.description,
                input_type=tool.input_type,
                module=tool.module,
                path=tool.path,
            )
        )

    return sorted(updated_tools, key=lambda t: t.display_name.lower()), errors


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
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(
            tw,
            text=self.text,
            background="#111827",
            foreground="#f9fafb",
            relief=tk.SOLID,
            borderwidth=1,
            padding=(6, 4),
        )
        label.pack()

    def _hide(self, _event: tk.Event) -> None:
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class MOITGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MOIT — Manufacturing Operations Insight Toolkit")
        self.geometry("980x640")
        self.minsize(900, 600)

        self.config_data = _load_config()
        self.tools: list[ToolInfo] = []
        self.tools_by_display: dict[str, ToolInfo] = {}
        self.tool_var = tk.StringVar()
        self.tool_desc_var = tk.StringVar()
        self.tool_dev_mode_var = tk.BooleanVar(value=bool(self.config_data.get("tool_dev_mode", False)))
        self.last_run_output = ""
        self.last_run_time = None

        self.output_dir_var = tk.StringVar(value=str(self.config_data.get("output_dir")))

        # Common file inputs
        self.csv_path_var = tk.StringVar()
        self.handoff_path_var = tk.StringVar()

        # Throughput inputs (defaults align with README examples)
        self.nominal_rate_var = tk.StringVar(value="120")
        self.minor_stops_per_hour_var = tk.StringVar(value="3")
        self.avg_minor_stop_min_var = tk.StringVar(value="2")
        self.changeovers_per_shift_var = tk.StringVar(value="1")
        self.changeover_min_var = tk.StringVar(value="25")
        self.shift_length_hours_var = tk.StringVar(value="12")
        self.staffing_factor_var = tk.StringVar(value="1.0")

        self._ensure_sample_files()
        self._load_tools(log_errors=False)
        self._build_ui()
        self._persist_output_dir()
        self._refresh_visible_inputs()
        self._update_sample_defaults()
        self._refresh_diagnostics()

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="User Guide", command=self._open_user_guide)
        help_menu.add_command(label="Open Output Folder", command=self._open_output_folder)
        help_menu.add_separator()
        help_menu.add_command(label="Contact / Support", command=self._show_support)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

        # Top frame: tool selection
        top = ttk.Frame(self, padding=12)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Tool:", font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        tool_combo = ttk.Combobox(
            top,
            textvariable=self.tool_var,
            values=self._tool_display_names(),
            state="readonly",
            width=28,
        )
        self.tool_combo = tool_combo
        tool_combo.pack(side=tk.LEFT, padx=(8, 16))
        tool_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_tool_selected())

        run_btn = ttk.Button(top, text="Run", command=self._run_selected)
        run_btn.pack(side=tk.LEFT)

        clear_btn = ttk.Button(top, text="Clear Output", command=self._clear_output)
        clear_btn.pack(side=tk.LEFT, padx=(8, 0))

        save_btn = ttk.Button(top, text="Save Results…", command=self._save_output)
        save_btn.pack(side=tk.LEFT, padx=(8, 0))

        dev_toggle = ttk.Checkbutton(
            top,
            text="Tool Dev Mode",
            variable=self.tool_dev_mode_var,
            command=self._toggle_dev_mode,
        )
        dev_toggle.pack(side=tk.RIGHT)

        desc_row = ttk.Frame(self, padding=(12, 0, 12, 6))
        desc_row.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(desc_row, text="Description:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.tool_desc_label = ttk.Label(
            desc_row,
            textvariable=self.tool_desc_var,
            wraplength=720,
            foreground="#4b5563",
        )
        self.tool_desc_label.pack(side=tk.LEFT, padx=(8, 0))

        self.dev_row = ttk.Frame(self, padding=(12, 0, 12, 8))
        self.dev_reload_btn = ttk.Button(self.dev_row, text="Reload Tools", command=self._reload_tools)
        self.dev_reload_btn.pack(side=tk.LEFT)
        self.dev_open_btn = ttk.Button(self.dev_row, text="Open Tool Source", command=self._open_tool_source)
        self.dev_open_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.dev_validate_btn = ttk.Button(
            self.dev_row, text="Validate run_analysis()", command=self._validate_tool_signature
        )
        self.dev_validate_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Inputs frame
        inputs = ttk.LabelFrame(self, text="Inputs", padding=12)
        inputs.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 12))
        self.inputs_frame = inputs

        # Output folder row
        self.output_row = ttk.Frame(inputs)
        ttk.Label(self.output_row, text="Output folder:").pack(side=tk.LEFT)
        self.output_entry = ttk.Entry(self.output_row, textvariable=self.output_dir_var, width=78)
        self.output_entry.pack(side=tk.LEFT, padx=8)
        self.output_entry.bind("<Return>", lambda _e: self._persist_output_dir())
        self.output_entry.bind("<FocusOut>", lambda _e: self._persist_output_dir())
        self.output_browse_btn = ttk.Button(self.output_row, text="Browse…", command=self._browse_output)
        self.output_browse_btn.pack(side=tk.LEFT)
        self.output_row.pack(side=tk.TOP, fill=tk.X, pady=4)

        # CSV row
        self.csv_row = ttk.Frame(inputs)
        ttk.Label(self.csv_row, text="CSV file:").pack(side=tk.LEFT)
        self.csv_entry = ttk.Entry(self.csv_row, textvariable=self.csv_path_var, width=80)
        self.csv_entry.pack(side=tk.LEFT, padx=8)
        self.csv_browse_btn = ttk.Button(self.csv_row, text="Browse…", command=self._browse_csv)
        self.csv_browse_btn.pack(side=tk.LEFT)

        # Handoff row
        self.handoff_row = ttk.Frame(inputs)
        ttk.Label(self.handoff_row, text="Handoff file:").pack(side=tk.LEFT)
        self.handoff_entry = ttk.Entry(self.handoff_row, textvariable=self.handoff_path_var, width=80)
        self.handoff_entry.pack(side=tk.LEFT, padx=8)
        self.handoff_browse_btn = ttk.Button(self.handoff_row, text="Browse…", command=self._browse_handoff)
        self.handoff_browse_btn.pack(side=tk.LEFT)

        # Throughput grid
        self.throughput_grid = ttk.Frame(inputs)

        def add_field(row: int, col: int, label: str, var: tk.StringVar) -> ttk.Entry:
            ttk.Label(self.throughput_grid, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
            entry = ttk.Entry(self.throughput_grid, textvariable=var, width=16)
            entry.grid(
                row=row, column=col + 1, sticky="w", padx=(0, 16), pady=4
            )
            return entry

        self.nominal_rate_entry = add_field(0, 0, "Nominal rate:", self.nominal_rate_var)
        self.shift_length_entry = add_field(0, 2, "Shift hours:", self.shift_length_hours_var)
        self.staffing_factor_entry = add_field(0, 4, "Staffing factor:", self.staffing_factor_var)

        self.minor_stops_entry = add_field(1, 0, "Minor stops/hr:", self.minor_stops_per_hour_var)
        self.avg_minor_stop_entry = add_field(1, 2, "Avg stop (min):", self.avg_minor_stop_min_var)
        self.changeovers_entry = add_field(1, 4, "Changeovers/shift:", self.changeovers_per_shift_var)

        self.changeover_entry = add_field(2, 0, "Changeover (min):", self.changeover_min_var)

        # Output/logs/diagnostics notebook
        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        output_frame = ttk.Frame(notebook)
        logs_frame = ttk.Frame(notebook)
        diagnostics_frame = ttk.Frame(notebook)

        notebook.add(output_frame, text="Output")
        notebook.add(logs_frame, text="Logs")
        notebook.add(diagnostics_frame, text="Diagnostics")

        self.output_text = tk.Text(output_frame, wrap="none", font=("Consolas", 10))
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output_text.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.configure(yscrollcommand=yscroll.set)

        self.log_text = tk.Text(logs_frame, wrap="none", font=("Consolas", 9), state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll = ttk.Scrollbar(logs_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.diagnostics_text = tk.Text(diagnostics_frame, wrap="word", font=("Consolas", 9), state=tk.DISABLED)
        self.diagnostics_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        diag_scroll = ttk.Scrollbar(diagnostics_frame, orient="vertical", command=self.diagnostics_text.yview)
        diag_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.diagnostics_text.configure(yscrollcommand=diag_scroll.set)

        # Status frame
        status_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        self._status_style = ttk.Style(self)
        self._status_style.configure("Status.Ready.TLabel", foreground="#6b7280")
        self._status_style.configure("Status.Running.TLabel", foreground="#2563eb")
        self._status_style.configure("Status.Complete.TLabel", foreground="#16a34a")
        self._status_style.configure("Status.Error.TLabel", foreground="#dc2626")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style="Status.Ready.TLabel")
        self.status_label.pack(side=tk.LEFT)
        self.last_run_var = tk.StringVar(value="Last run: —")
        self.last_run_label = ttk.Label(status_frame, textvariable=self.last_run_var, foreground="#6b7280")
        self.last_run_label.pack(side=tk.RIGHT)

        self._attach_tooltips(
            tool_combo,
            run_btn,
            clear_btn,
            save_btn,
        )

        self._toggle_dev_mode()
        self._on_tool_selected()

    def _tool_display_names(self) -> list[str]:
        return [tool.display_name for tool in self.tools]

    def _load_tools(self, log_errors: bool = True) -> None:
        tools, errors = _discover_tools()
        self.tools = tools
        self.tools_by_display = {tool.display_name: tool for tool in tools}
        if not self.tool_var.get() and self.tools:
            self.tool_var.set(self.tools[0].display_name)
        if self.tool_var.get() not in self.tools_by_display and self.tools:
            self.tool_var.set(self.tools[0].display_name)
        if log_errors:
            if not self.tools:
                self._log("No tools discovered in the tools directory.", level="warning")
            for error in errors:
                self._log(error, level="error")

    def _reload_tools(self) -> None:
        self._load_tools(log_errors=True)
        if hasattr(self, "tool_combo"):
            self.tool_combo["values"] = self._tool_display_names()
        self._on_tool_selected()
        self._log("Reloaded tools from tools directory.")

    def _selected_tool(self) -> ToolInfo | None:
        return self.tools_by_display.get(self.tool_var.get())

    def _on_tool_selected(self) -> None:
        self._refresh_tool_description()
        self._refresh_visible_inputs()

    def _refresh_tool_description(self) -> None:
        tool = self._selected_tool()
        if tool:
            self.tool_desc_var.set(tool.description or "No description provided.")
        else:
            self.tool_desc_var.set("No tool selected.")

    def _toggle_dev_mode(self) -> None:
        enabled = bool(self.tool_dev_mode_var.get())
        self.config_data["tool_dev_mode"] = enabled
        _save_config(self.config_data)
        if enabled:
            self.dev_row.pack(side=tk.TOP, fill=tk.X)
        else:
            self.dev_row.pack_forget()

    def _open_tool_source(self) -> None:
        tool = self._selected_tool()
        if not tool:
            messagebox.showwarning("No tool selected", "Select a tool to open its source file.")
            return
        if not os.path.isfile(tool.path):
            messagebox.showerror("Missing source file", f"Tool source not found:\n{tool.path}")
            return
        try:
            _open_path(tool.path)
            self._log(f"Opened tool source: {tool.path}")
        except OSError as exc:
            messagebox.showerror("Open failed", f"Could not open the tool source:\n{exc}")
            self._log(f"Failed to open tool source: {exc}", level="error")

    def _validate_tool_signature(self) -> None:
        tool = self._selected_tool()
        if not tool:
            messagebox.showwarning("No tool selected", "Select a tool to validate.")
            return
        issues: list[str] = []
        if not hasattr(tool.module, "run_analysis"):
            issues.append("Missing run_analysis() function.")
        else:
            sig = inspect.signature(tool.module.run_analysis)
            params = list(sig.parameters.values())
            if len(params) != 1 or params[0].name != "input_path":
                issues.append("run_analysis() must accept exactly one parameter named input_path.")
            if sig.return_annotation not in (inspect.Signature.empty, str):
                issues.append("run_analysis() should return a str.")
        if issues:
            self._append_output("Signature validation issues:\n")
            for issue in issues:
                self._append_output(f"- {issue}\n")
            self._set_status("Signature check failed", state="error")
            self._log(f"Signature validation failed for {tool.module_name}: {issues}", level="error")
        else:
            self._append_output("Signature validation passed.\n")
            self._set_status("Signature check passed", state="complete")
            self._log(f"Signature validation passed for {tool.module_name}.")

    def _refresh_visible_inputs(self) -> None:
        # Hide all input sections first
        for w in (self.csv_row, self.handoff_row, self.throughput_grid):
            w.pack_forget()

        tool = self._selected_tool()
        if not tool:
            return

        if tool.input_type == "csv":
            self.csv_row.pack(side=tk.TOP, fill=tk.X, pady=4)
        elif tool.input_type == "handoff":
            self.handoff_row.pack(side=tk.TOP, fill=tk.X, pady=4)
        elif tool.input_type == "throughput":
            self.throughput_grid.pack(side=tk.TOP, fill=tk.X, pady=4)

    def _attach_tooltips(self, tool_combo: ttk.Combobox, run_btn: ttk.Button, clear_btn: ttk.Button, save_btn: ttk.Button) -> None:
        Tooltip(tool_combo, "Select which analysis tool to run.")
        Tooltip(run_btn, "Run the selected tool with the current inputs.")
        Tooltip(clear_btn, "Clear the output panel and reset the status.")
        Tooltip(save_btn, "Save the most recent output to a report file.")
        Tooltip(self.tool_desc_label, "Tool description from metadata, when available.")
        Tooltip(self.dev_reload_btn, "Reload tools from the tools directory.")
        Tooltip(self.dev_open_btn, "Open the selected tool's source file in the default editor.")
        Tooltip(self.dev_validate_btn, "Validate the selected tool's run_analysis() signature.")
        Tooltip(self.output_entry, "Reports will be saved here by default.")
        Tooltip(self.output_browse_btn, "Choose a folder for exported reports.")
        Tooltip(self.csv_entry, "CSV input file for downtime or safety analysis.")
        Tooltip(self.csv_browse_btn, "Browse for a CSV input file.")
        Tooltip(self.handoff_entry, "Markdown handoff file to validate.")
        Tooltip(self.handoff_browse_btn, "Browse for a handoff Markdown file.")
        Tooltip(self.nominal_rate_entry, "Nominal rate in units per hour.")
        Tooltip(self.shift_length_entry, "Shift length in hours.")
        Tooltip(self.staffing_factor_entry, "Staffing adjustment factor (e.g., 1.0 = nominal).")
        Tooltip(self.minor_stops_entry, "Average minor stops per hour.")
        Tooltip(self.avg_minor_stop_entry, "Average minor stop duration in minutes.")
        Tooltip(self.changeovers_entry, "Changeovers per shift.")
        Tooltip(self.changeover_entry, "Changeover duration in minutes.")
        Tooltip(self.output_text, "Tool output appears here.")
        Tooltip(self.log_text, "Diagnostics and error logs for troubleshooting.")
        Tooltip(self.diagnostics_text, "System and configuration details.")

    def _ensure_sample_files(self) -> None:
        sample_dir = str(self.config_data.get("sample_dir"))
        os.makedirs(sample_dir, exist_ok=True)
        for folder, filename in SAMPLE_FILES:
            src = _resource_path(folder, filename)
            dst = os.path.join(sample_dir, filename)
            if os.path.isfile(dst):
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
            except OSError:
                continue

    def _update_sample_defaults(self) -> None:
        sample_dir = str(self.config_data.get("sample_dir"))
        downtime_sample = os.path.join(sample_dir, "sample_downtime.csv")
        handoff_sample = os.path.join(sample_dir, "sample_handoff.md")
        if os.path.isfile(downtime_sample):
            self.csv_path_var.set(downtime_sample)
        else:
            self.csv_path_var.set(os.path.join("data", "sample_downtime.csv"))
        if os.path.isfile(handoff_sample):
            self.handoff_path_var.set(handoff_sample)
        else:
            self.handoff_path_var.set(os.path.join("docs", "sample_handoff.md"))

    def _open_user_guide(self) -> None:
        guide_path = _resource_path("README.md")
        if not os.path.isfile(guide_path):
            messagebox.showwarning("User guide missing", "Could not locate the README guide.")
            self._log("User guide not found.", level="warning")
            return
        webbrowser.open(f"file://{guide_path}")
        self._log(f"Opened user guide: {guide_path}")

    def _show_support(self) -> None:
        message = (
            "Support Contact Placeholder\n\n"
            "Email: support@example.com\n"
            "Phone: +1 (555) 010-0000\n\n"
            "Provide your site, tool name, and a brief description of the issue."
        )
        messagebox.showinfo("Contact / Support", message)
        self._log("Opened contact/support placeholder.")

    def _open_output_folder(self) -> None:
        path = self.output_dir_var.get().strip() or _default_output_dir()
        try:
            os.makedirs(path, exist_ok=True)
            _open_path(path)
            self._log(f"Opened output folder: {path}")
        except OSError as exc:
            messagebox.showerror("Open folder failed", f"Could not open the output folder:\n{exc}")
            self._log(f"Failed to open output folder: {exc}", level="error")

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder", initialdir=self.output_dir_var.get())
        if path:
            self.output_dir_var.set(path)
            self._persist_output_dir()
            self._refresh_diagnostics()

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=os.path.dirname(self.csv_path_var.get() or REPO_ROOT),
        )
        if path:
            self.csv_path_var.set(self._rel_or_abs(path))

    def _browse_handoff(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Markdown file",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
            initialdir=os.path.dirname(self.handoff_path_var.get() or REPO_ROOT),
        )
        if path:
            self.handoff_path_var.set(self._rel_or_abs(path))

    def _persist_output_dir(self) -> None:
        output_dir = self.output_dir_var.get().strip() or _default_output_dir()
        self.output_dir_var.set(output_dir)
        self.config_data["output_dir"] = output_dir
        _save_config(self.config_data)
        self._log(f"Saved output folder preference: {output_dir}")
        self._refresh_diagnostics()

    def _log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{level.upper()}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, entry)
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see(tk.END)

        if self.config_data.get("log_to_file"):
            try:
                os.makedirs(_user_config_dir(), exist_ok=True)
                with open(_log_path(), "a", encoding="utf-8") as handle:
                    handle.write(entry)
            except OSError:
                pass

    def _refresh_diagnostics(self) -> None:
        output_dir = self.output_dir_var.get().strip() or _default_output_dir()
        config_path = _config_path()
        config_dir = _user_config_dir()
        sample_dir = str(self.config_data.get("sample_dir"))
        writable_output = os.access(output_dir, os.W_OK) if os.path.exists(output_dir) else False
        writable_config = os.access(config_dir, os.W_OK) if os.path.exists(config_dir) else False
        diagnostics = (
            f"App version: {APP_VERSION}\n"
            f"Python: {platform.python_version()}\n"
            f"Platform: {platform.platform()}\n"
            f"Executable: {sys.executable}\n"
            f"Repo/Bundle root: {REPO_ROOT}\n"
            f"Config file: {config_path}\n"
            f"Config dir writable: {writable_config}\n"
            f"Sample data dir: {sample_dir}\n"
            f"Output dir: {output_dir}\n"
            f"Output dir writable: {writable_output}\n"
            f"Tool dev mode: {self.tool_dev_mode_var.get()}\n"
            f"Discovered tools: {len(self.tools)}\n"
        )
        self.diagnostics_text.configure(state=tk.NORMAL)
        self.diagnostics_text.delete("1.0", tk.END)
        self.diagnostics_text.insert(tk.END, diagnostics)
        self.diagnostics_text.configure(state=tk.DISABLED)

    def _rel_or_abs(self, path: str) -> str:
        try:
            common = os.path.commonpath([REPO_ROOT, os.path.abspath(path)])
            if common == os.path.abspath(REPO_ROOT):
                return os.path.relpath(path, REPO_ROOT)
            return path
        except Exception:
            return path

    def _clear_output(self) -> None:
        self.output_text.delete("1.0", tk.END)
        self.last_run_output = ""
        self._set_status("Ready", state="ready")
        self._log("Cleared output panel.")

    def _set_status(self, text: str, state: str = "ready") -> None:
        self.status_var.set(text)
        style_map = {
            "ready": "Status.Ready.TLabel",
            "running": "Status.Running.TLabel",
            "complete": "Status.Complete.TLabel",
            "error": "Status.Error.TLabel",
        }
        self.status_label.configure(style=style_map.get(state, "Status.Ready.TLabel"))
        self.update_idletasks()

    def _set_last_run_time(self) -> None:
        self.last_run_time = datetime.now()
        self.last_run_var.set(f"Last run: {self.last_run_time:%Y-%m-%d %H:%M:%S}")

    def _append_output(self, text: str) -> None:
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)

    def _save_output(self) -> None:
        output = self.last_run_output.strip()
        if not output:
            messagebox.showwarning("No output", "Run a tool to generate output before saving.")
            self._set_status("Error: No output to save", state="error")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        tool = self._selected_tool()
        tool_name = tool.module_name if tool else "tool"
        initial_name = f"{tool_name}_results_{timestamp}.txt"

        output_dir = self.output_dir_var.get().strip() or _default_output_dir()
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Output folder error", f"Could not create output folder:\n{exc}")
            self._set_status("Error: Output folder unavailable", state="error")
            self._log(f"Failed to create output folder: {exc}", level="error")
            return

        path = filedialog.asksaveasfilename(
            title="Save results",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=initial_name,
            initialdir=output_dir,
        )
        if not path:
            self._set_status("Ready", state="ready")
            return

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(output + "\n")
        except OSError as exc:
            messagebox.showerror("Save failed", f"Could not save results:\n{exc}")
            self._set_status("Error: Save failed", state="error")
            self._log(f"Failed to save results: {exc}", level="error")
            return

        self._set_status(f"Saved results to {self._rel_or_abs(path)}", state="complete")
        self._log(f"Saved results to {path}")

    def _show_about(self) -> None:
        message = (
            "Manufacturing Operations Insight Toolkit (MOIT)\n"
            f"Version: {APP_VERSION}\n\n"
            "MOIT provides offline, read-only analysis tools for downtime, throughput, "
            "safety trends, and shift handoffs.\n\n"
            "GitHub: https://github.com/placeholder/moit"
        )
        messagebox.showinfo("About MOIT", message)
        self._log("Opened About dialog.")

    def _validate_required(self, value: str, label: str) -> bool:
        if not value.strip():
            messagebox.showwarning("Missing input", f"Please provide a value for {label}.")
            self._set_status(f"Error: Missing {label}", state="error")
            return False
        return True

    def _resolve_path(self, path: str) -> str:
        path = path.strip()
        if not path:
            return path
        if os.path.isabs(path):
            return path
        return os.path.join(REPO_ROOT, path)

    def _validate_file(self, path: str, label: str, expected_ext: str | None = None) -> bool:
        if not self._validate_required(path, label):
            return False
        resolved = self._resolve_path(path)
        if not os.path.isfile(resolved):
            messagebox.showerror("Missing file", f"Could not find {label}:\n{path}")
            self._set_status(f"Error: {label} not found", state="error")
            self._log(f"Missing file for {label}: {path}", level="error")
            return False
        if expected_ext and not resolved.lower().endswith(expected_ext):
            messagebox.showerror("Invalid file", f"{label} must be a {expected_ext} file.")
            self._set_status(f"Error: Invalid {label}", state="error")
            self._log(f"Invalid file extension for {label}: {path}", level="error")
            return False
        return True

    def _validate_numeric_range(
        self,
        value: str,
        label: str,
        min_value: float,
        max_value: float,
    ) -> float | None:
        if not self._validate_required(value, label):
            return None
        try:
            numeric = float(value)
        except ValueError:
            messagebox.showerror("Invalid input", f"{label} must be numeric.")
            self._set_status(f"Error: Invalid {label}", state="error")
            self._log(f"Invalid numeric input for {label}: {value}", level="error")
            return None
        if not (min_value <= numeric <= max_value):
            messagebox.showerror(
                "Out of range",
                f"{label} must be between {min_value:g} and {max_value:g}.",
            )
            self._set_status(f"Error: {label} out of range", state="error")
            self._log(f"{label} out of range: {value}", level="error")
            return None
        return numeric

    def _run_selected(self) -> None:
        tool = self._selected_tool()
        if not tool:
            messagebox.showerror("No tool selected", "Select a tool to run.")
            self._set_status("Error: No tool selected", state="error")
            return

        self._persist_output_dir()
        self._refresh_diagnostics()

        input_path = ""
        temp_path: str | None = None

        if tool.input_type == "csv":
            csv_path = self.csv_path_var.get()
            if not self._validate_file(csv_path, "CSV file", expected_ext=".csv"):
                return
            input_path = self._resolve_path(csv_path.strip())
        elif tool.input_type == "handoff":
            handoff_path = self.handoff_path_var.get()
            if not self._validate_file(handoff_path, "handoff file"):
                return
            input_path = self._resolve_path(handoff_path.strip())
        elif tool.input_type == "throughput":
            nominal_rate = self._validate_numeric_range(self.nominal_rate_var.get(), "Nominal rate", 1, 10000)
            minor_stops = self._validate_numeric_range(
                self.minor_stops_per_hour_var.get(), "Minor stops per hour", 0, 60
            )
            avg_minor_stop = self._validate_numeric_range(
                self.avg_minor_stop_min_var.get(), "Average minor stop minutes", 0, 60
            )
            changeovers = self._validate_numeric_range(
                self.changeovers_per_shift_var.get(), "Changeovers per shift", 0, 20
            )
            changeover_min = self._validate_numeric_range(self.changeover_min_var.get(), "Changeover minutes", 0, 240)
            shift_length = self._validate_numeric_range(self.shift_length_hours_var.get(), "Shift length hours", 1, 24)
            staffing_factor = self._validate_numeric_range(self.staffing_factor_var.get(), "Staffing factor", 0.1, 5)

            if None in (
                nominal_rate,
                minor_stops,
                avg_minor_stop,
                changeovers,
                changeover_min,
                shift_length,
                staffing_factor,
            ):
                return

            payload = {
                "nominal_rate": nominal_rate,
                "minor_stops_per_hour": minor_stops,
                "avg_minor_stop_min": avg_minor_stop,
                "changeovers_per_shift": changeovers,
                "changeover_min": changeover_min,
                "shift_length_hours": shift_length,
                "staffing_factor": staffing_factor,
            }
            try:
                with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as handle:
                    json.dump(payload, handle)
                    temp_path = handle.name
                input_path = temp_path
            except OSError as exc:
                messagebox.showerror("Temp file error", f"Could not create temp file:\n{exc}")
                self._set_status("Error: Temp file error", state="error")
                self._log(f"Failed to create temp file: {exc}", level="error")
                return

        self._set_status("Running analysis...", state="running")
        input_label = input_path if input_path else "no input"
        self._append_output(f"$ {tool.module_name} ({input_label})\n\n")
        self._log(f"Running tool: {tool.module_name}")

        run_output_parts: list[str] = []
        try:
            result = tool.module.run_analysis(input_path)
            output_text = result if isinstance(result, str) else str(result)
            self._append_output(output_text)
            run_output_parts.append(output_text)
            if output_text and not output_text.endswith("\n"):
                self._append_output("\n")
                run_output_parts.append("\n")
            self.last_run_output = "".join(run_output_parts).strip()
            self._set_status("Analysis complete", state="complete")
            self._log("Analysis completed successfully.")
        except Exception:
            trace = traceback.format_exc()
            self._append_output("ERROR: Tool execution failed.\n\n")
            self._append_output(trace)
            if not trace.endswith("\n"):
                self._append_output("\n")
            self.last_run_output = f"ERROR: Tool execution failed.\n\n{trace}".strip()
            self._set_status("Error: Tool execution failed", state="error")
            self._log("Tool execution failed. See output for traceback.", level="error")
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self._set_last_run_time()


def main() -> None:
    app = MOITGui()
    app.mainloop()


if __name__ == "__main__":
    main()
