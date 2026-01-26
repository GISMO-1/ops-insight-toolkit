# Downtime Pattern Analyzer

## Purpose
The Downtime Pattern Analyzer summarizes downtime events from a CSV file, highlighting the most common causes, the most impacted equipment, shift-level impacts, and hot hours by total downtime minutes.

## Inputs
Required columns (header names are flexible; the tool matches common aliases case-insensitively):
- `event_id` (aliases: event id, downtime_id)
- `start_time` (ISO 8601, e.g., `2026-01-03T14:22:00`; aliases: start time, start timestamp)
- `end_time` (ISO 8601; aliases: end time, end timestamp)
- `duration_min` (integer minutes, must match timestamps; aliases: duration minutes, duration)
- `area` (aliases: line area, department)
- `equipment` (aliases: machine, asset, work center)
- `category` (aliases: type)
- `cause` (aliases: reason, root cause)
- `shift` (aliases: shift label, crew)
- `notes` (aliases: comments, details)

## Outputs
- Text report summarizing downtime minutes by cause, equipment, shift label, and hour.

## Example command
```bash
python tools/downtime_analyzer.py data/sample_downtime.csv
```

For stress-testing or demo walkthroughs:
```bash
python tools/downtime_analyzer.py data/sample_downtime_large.csv
```

## Example output (snippet)
```
Top causes by downtime minutes:
- Guard reset: 571 min (12.3%)
- Material shortage: 543 min (11.7%)

Top equipment by downtime minutes:
- Filler-02: 645 min (13.8%)

Downtime minutes by shift:
- Shift-Alpha: 914 min
- Shift-Beta: 1111 min
- Shift-Zeta: 695 min
```

## Self-check
```bash
python tools/downtime_analyzer.py data/sample_downtime.csv
```
