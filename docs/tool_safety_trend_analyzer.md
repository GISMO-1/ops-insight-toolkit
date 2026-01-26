# Safety Observation Trend Analyzer

## Purpose
Summarize safety observations by category and severity, highlight near-miss rate, estimate time-to-close performance, and show weekly trend volume.

## Inputs
- CSV file with columns: obs_id, date, area, category, severity, near_miss, corrective_action, closed_date, notes.
  - Header names are flexible; common aliases are accepted (e.g., `observation id`, `line area`, `risk level`, `near miss`).
- Dates must be ISO format (YYYY-MM-DD).
- Severity values: LOW, MED, HIGH.
- Near miss values: TRUE, FALSE.

## Outputs
- Text report with counts by category/severity, near-miss rate, time-to-close stats, and weekly trend counts.

## Example Command
```bash
python tools/safety_trend_analyzer.py data/sample_safety_observations.csv
```

## Example Output
```
Counts by category and severity:
- Housekeeping / LOW: 14
- Housekeeping / MED: 6
- PPE / LOW: 9

Near-miss rate: 18.0% (18 of 100)
Time-to-close (days): avg 4.6, median 4.0; open items: 7

Weekly trend (ISO week):
- 2026-W02: 12
- 2026-W03: 11
- 2026-W04: 14
```

## Self-check
```bash
python tools/safety_trend_analyzer.py data/sample_safety_observations.csv
```
