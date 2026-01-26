# MOIT GUI Wrapper

## Purpose
Provide a desktop interface (Tkinter) that runs the MOIT command-line tools and displays their output in a single window.

## Inputs
- Tool selection: downtime, throughput, safety, handoff validation, or tests.
- File paths for CSV or Markdown inputs where required.
- Numeric parameters for throughput modeling.

## Outputs
- The CLI output displayed in the GUI output panel.
- Optional exported results saved from the most recent run to a `.txt` or `.csv` file using **Save Results…**.
- Status feedback at the bottom of the window (ready, running, complete, or error).
- **Help → About** menu with version and repository link.

## Example command
```bash
python -m tools.gui
```

## Self-check
- Launch the GUI and run a tool against the sample data.
  - Example: select **Downtime** and run with `data/sample_downtime.csv`.
- Confirm the output appears in the GUI and **Save Results…** writes a file.
- Change a throughput input to an invalid value to confirm the status label reports the error.
