# Packaging MOIT as a Standalone Windows Executable

## Purpose
Create a standalone `MOIT.exe` with the Tkinter GUI launcher and bundled read-only reference data so non-technical users can run the toolkit without installing Python.

## Inputs
- Python 3.11+
- PyInstaller
- MOIT repository (this repo)

## Outputs
- `dist/MOIT.exe` (single-file executable)
- `build/` (PyInstaller build artifacts)

## Build command (Windows, one-file)
```bash
py -3.11 -m pip install --upgrade pyinstaller
py -3.11 -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name MOIT ^
  --add-data "data;data" ^
  --add-data "docs;docs" ^
  tools/gui.py
```

## Notes
- The `--add-data` flags bundle the `data/` and `docs/` directories so sample inputs and reference docs are available offline.
- If you need a console window for troubleshooting, replace `--windowed` with `--console`.

## Validation checklist (clean Windows machine)
1. Copy `dist/MOIT.exe` to a Windows system without Python.
2. Launch the executable and confirm the GUI opens.
3. Run each tool using sample data:
   - Downtime: `data/sample_downtime.csv`
   - Safety: `data/sample_safety_observations.csv`
   - Handoff: `docs/sample_handoff.md`
4. Use **Save Results…** to export output to a `.txt` file.
5. Enter a bad path or invalid numeric input to confirm the status label shows a clear error.

## Self-check
- Run the build command above and confirm `dist/MOIT.exe` exists.
