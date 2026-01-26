# MOIT GUI Wrapper

## Purpose
Provide a desktop interface (Tkinter) that runs the MOIT command-line tools and displays their output in a single window.

## Inputs
- Tool selection: downtime, throughput, safety, handoff validation, or tests.
- File paths for CSV or Markdown inputs where required.
- Numeric parameters for throughput modeling.
- Output folder location (default is `Desktop/MOIT_Reports`, persisted in the local config file).

## Outputs
- The CLI output displayed in the GUI output panel.
- Optional exported results saved from the most recent run to a `.txt` or `.csv` file using **Save Results…**.
- Status feedback at the bottom of the window (ready, running, complete, or error), plus last run time.
- Logs tab for troubleshooting messages and optional file logging in the local config folder.
- Diagnostics tab with Python/runtime details and config paths.
- **Help → User Guide**, **Contact / Support**, and **Open Output Folder** menu items.
- Default output folder set to `Desktop/MOIT_Reports` (configurable and persisted between runs).
- Sample input files are copied to the local config folder on first launch for easy onboarding.

## Example command
```bash
python -m tools.gui
```

## Self-check
- Launch the GUI and run a tool against the sample data.
  - Example: select **Downtime** and run with `data/sample_downtime.csv`.
- Confirm the output appears in the GUI and **Save Results…** writes a file.
- Change a throughput input to an invalid value to confirm the status label reports the error.
- Use **Help → Open Output Folder** to confirm the configured directory opens.
