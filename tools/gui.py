"""Simple GUI wrapper for MOIT tools (Tkinter, no external dependencies).

Run:
  python -m tools.gui
or:
  python tools/gui.py

This GUI shells out to the unified runner (tools/run.py) and displays stdout/stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk


# Allow running as a script from repo root: `python tools/gui.py ...`
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _python_cmd() -> list[str]:
    # Always prefer module invocation (most reliable for imports)
    return [sys.executable, "-m", "tools.run"]


class MOITGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MOIT — Manufacturing Operations Insight Toolkit")
        self.geometry("980x640")
        self.minsize(900, 600)

        self.tool_var = tk.StringVar(value="downtime")

        # Common file inputs
        self.csv_path_var = tk.StringVar(value=os.path.join("data", "sample_downtime.csv"))
        self.handoff_path_var = tk.StringVar(value=os.path.join("docs", "sample_handoff.md"))

        # Throughput inputs (defaults align with README examples)
        self.nominal_rate_var = tk.StringVar(value="120")
        self.minor_stops_per_hour_var = tk.StringVar(value="3")
        self.avg_minor_stop_min_var = tk.StringVar(value="2")
        self.changeovers_per_shift_var = tk.StringVar(value="1")
        self.changeover_min_var = tk.StringVar(value="25")
        self.shift_length_hours_var = tk.StringVar(value="12")
        self.staffing_factor_var = tk.StringVar(value="1.0")

        self._build_ui()
        self._refresh_visible_inputs()

    def _build_ui(self) -> None:
        # Top frame: tool selection
        top = ttk.Frame(self, padding=12)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Tool:", font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        tool_combo = ttk.Combobox(
            top,
            textvariable=self.tool_var,
            values=["downtime", "throughput", "safety", "handoff-validate", "test"],
            state="readonly",
            width=18,
        )
        tool_combo.pack(side=tk.LEFT, padx=(8, 16))
        tool_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_visible_inputs())

        run_btn = ttk.Button(top, text="Run", command=self._run_selected)
        run_btn.pack(side=tk.LEFT)

        clear_btn = ttk.Button(top, text="Clear Output", command=self._clear_output)
        clear_btn.pack(side=tk.LEFT, padx=(8, 0))

        save_btn = ttk.Button(top, text="Save Results…", command=self._save_output)
        save_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Inputs frame
        inputs = ttk.LabelFrame(self, text="Inputs", padding=12)
        inputs.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 12))
        self.inputs_frame = inputs

        # CSV row
        self.csv_row = ttk.Frame(inputs)
        ttk.Label(self.csv_row, text="CSV file:").pack(side=tk.LEFT)
        self.csv_entry = ttk.Entry(self.csv_row, textvariable=self.csv_path_var, width=80)
        self.csv_entry.pack(side=tk.LEFT, padx=8)
        ttk.Button(self.csv_row, text="Browse…", command=self._browse_csv).pack(side=tk.LEFT)

        # Handoff row
        self.handoff_row = ttk.Frame(inputs)
        ttk.Label(self.handoff_row, text="Handoff file:").pack(side=tk.LEFT)
        self.handoff_entry = ttk.Entry(self.handoff_row, textvariable=self.handoff_path_var, width=80)
        self.handoff_entry.pack(side=tk.LEFT, padx=8)
        ttk.Button(self.handoff_row, text="Browse…", command=self._browse_handoff).pack(side=tk.LEFT)

        # Throughput grid
        self.throughput_grid = ttk.Frame(inputs)

        def add_field(row: int, col: int, label: str, var: tk.StringVar) -> None:
            ttk.Label(self.throughput_grid, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(self.throughput_grid, textvariable=var, width=16).grid(
                row=row, column=col + 1, sticky="w", padx=(0, 16), pady=4
            )

        add_field(0, 0, "Nominal rate:", self.nominal_rate_var)
        add_field(0, 2, "Shift hours:", self.shift_length_hours_var)
        add_field(0, 4, "Staffing factor:", self.staffing_factor_var)

        add_field(1, 0, "Minor stops/hr:", self.minor_stops_per_hour_var)
        add_field(1, 2, "Avg stop (min):", self.avg_minor_stop_min_var)
        add_field(1, 4, "Changeovers/shift:", self.changeovers_per_shift_var)

        add_field(2, 0, "Changeover (min):", self.changeover_min_var)

        # Output frame
        out = ttk.LabelFrame(self, text="Output", padding=0)
        out.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self.output_text = tk.Text(out, wrap="none", font=("Consolas", 10))
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(out, orient="vertical", command=self.output_text.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.configure(yscrollcommand=yscroll.set)

        # Status frame
        status_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

    def _refresh_visible_inputs(self) -> None:
        # Hide all input sections first
        for w in (self.csv_row, self.handoff_row, self.throughput_grid):
            w.pack_forget()

        tool = self.tool_var.get()

        if tool in ("downtime", "safety"):
            self.csv_row.pack(side=tk.TOP, fill=tk.X, pady=4)
        elif tool == "handoff-validate":
            self.handoff_row.pack(side=tk.TOP, fill=tk.X, pady=4)
        elif tool == "throughput":
            self.throughput_grid.pack(side=tk.TOP, fill=tk.X, pady=4)
        elif tool == "test":
            # no inputs
            pass

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=REPO_ROOT,
        )
        if path:
            self.csv_path_var.set(self._rel_or_abs(path))

    def _browse_handoff(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Markdown file",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
            initialdir=REPO_ROOT,
        )
        if path:
            self.handoff_path_var.set(self._rel_or_abs(path))

    def _rel_or_abs(self, path: str) -> str:
        try:
            return os.path.relpath(path, REPO_ROOT)
        except Exception:
            return path

    def _clear_output(self) -> None:
        self.output_text.delete("1.0", tk.END)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.update_idletasks()

    def _append_output(self, text: str) -> None:
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)

    def _save_output(self) -> None:
        output = self.output_text.get("1.0", tk.END).strip()
        if not output:
            messagebox.showwarning("No output", "Run a tool to generate output before saving.")
            self._set_status("Error: No output to save")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        tool = self.tool_var.get()
        initial_name = f"{tool}_report_{timestamp}.txt"

        path = filedialog.asksaveasfilename(
            title="Save results",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=initial_name,
            initialdir=REPO_ROOT,
        )
        if not path:
            self._set_status("Save canceled")
            return

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(output + "\n")
        except OSError as exc:
            messagebox.showerror("Save failed", f"Could not save results:\n{exc}")
            self._set_status("Error: Save failed")
            return

        self._set_status(f"Saved results to {self._rel_or_abs(path)}")

    def _validate_required(self, value: str, label: str) -> bool:
        if not value.strip():
            messagebox.showwarning("Missing input", f"Please provide a value for {label}.")
            self._set_status(f"Error: Missing {label}")
            return False
        return True

    def _run_selected(self) -> None:
        tool = self.tool_var.get()

        cmd = _python_cmd()

        if tool == "downtime":
            csv_path = self.csv_path_var.get()
            if not self._validate_required(csv_path, "CSV file"):
                return
            cmd += ["downtime", "--csv", csv_path.strip()]
        elif tool == "safety":
            csv_path = self.csv_path_var.get()
            if not self._validate_required(csv_path, "CSV file"):
                return
            cmd += ["safety", "--csv", csv_path.strip()]
        elif tool == "handoff-validate":
            handoff_path = self.handoff_path_var.get()
            if not self._validate_required(handoff_path, "handoff file"):
                return
            cmd += ["handoff-validate", "--file", handoff_path.strip()]
        elif tool == "throughput":
            try:
                # Validate numeric inputs early so we can give a clean message
                if not self._validate_required(self.nominal_rate_var.get(), "nominal rate"):
                    return
                if not self._validate_required(self.minor_stops_per_hour_var.get(), "minor stops per hour"):
                    return
                if not self._validate_required(self.avg_minor_stop_min_var.get(), "average minor stop minutes"):
                    return
                if not self._validate_required(self.changeovers_per_shift_var.get(), "changeovers per shift"):
                    return
                if not self._validate_required(self.changeover_min_var.get(), "changeover minutes"):
                    return
                if not self._validate_required(self.shift_length_hours_var.get(), "shift length hours"):
                    return
                if not self._validate_required(self.staffing_factor_var.get(), "staffing factor"):
                    return
                float(self.nominal_rate_var.get())
                float(self.minor_stops_per_hour_var.get())
                float(self.avg_minor_stop_min_var.get())
                float(self.changeovers_per_shift_var.get())
                float(self.changeover_min_var.get())
                float(self.shift_length_hours_var.get())
                float(self.staffing_factor_var.get())
            except ValueError:
                messagebox.showerror("Invalid input", "Throughput fields must be numeric.")
                self._set_status("Error: Invalid numeric input")
                return

            cmd += [
                "throughput",
                "--nominal-rate",
                self.nominal_rate_var.get().strip(),
                "--minor-stops-per-hour",
                self.minor_stops_per_hour_var.get().strip(),
                "--avg-minor-stop-min",
                self.avg_minor_stop_min_var.get().strip(),
                "--changeovers-per-shift",
                self.changeovers_per_shift_var.get().strip(),
                "--changeover-min",
                self.changeover_min_var.get().strip(),
                "--shift-length-hours",
                self.shift_length_hours_var.get().strip(),
                "--staffing-factor",
                self.staffing_factor_var.get().strip(),
            ]
        elif tool == "test":
            cmd += ["test"]
        else:
            messagebox.showerror("Unknown tool", f"Unknown tool: {tool}")
            self._set_status("Error: Unknown tool")
            return

        self._set_status("Running...")
        self._append_output(f"$ {' '.join(cmd)}\n\n")

        try:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )
        except Exception as exc:
            self._append_output(f"ERROR: failed to run command: {exc}\n")
            self._set_status("Error: Failed to run command")
            return

        if proc.stdout:
            self._append_output(proc.stdout)
            if not proc.stdout.endswith("\n"):
                self._append_output("\n")

        if proc.stderr:
            self._append_output("\n[stderr]\n")
            self._append_output(proc.stderr)
            if not proc.stderr.endswith("\n"):
                self._append_output("\n")

        self._append_output(f"\n(exit code: {proc.returncode})\n\n")
        self._set_status("Complete" if proc.returncode == 0 else f"Error: Exit code {proc.returncode}")


def main() -> None:
    app = MOITGui()
    app.mainloop()


if __name__ == "__main__":
    main()
