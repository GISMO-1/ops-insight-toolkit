# Downtime Pattern Analyzer

## Purpose
The Downtime Pattern Analyzer summarizes downtime events from a CSV file, highlighting the most common causes, the most impacted equipment, shift-level impacts, and hot hours by total downtime minutes.

## Input schema
Required columns:
- `event_id`
- `start_time` (ISO 8601, e.g., `2026-01-03T14:22:00`)
- `end_time` (ISO 8601)
- `duration_min` (integer minutes, must match timestamps)
- `area`
- `equipment`
- `category`
- `cause`
- `shift`
- `notes`

## Example command
```bash
python tools/downtime_analyzer.py data/sample_downtime.csv
```

## Example output (snippet)
```
Top causes by downtime minutes:
- Belt misalignment: 180 min (12.6%)
- Sensor fault: 165 min (11.5%)

Top equipment by downtime minutes:
- Conveyor-01: 210 min (14.7%)

Downtime minutes by shift:
- A: 465 min
- B: 420 min
- C: 475 min
```
