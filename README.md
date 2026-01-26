# Manufacturing Operations Insight Toolkit (MOIT)

This repository contains small, practical tools and models for understanding throughput, downtime patterns, safety observations, and operational trade-offs in a high-volume manufacturing environment.

The goal is not automation for its own sake, but clarity: making operational constraints, risks, and improvement opportunities visible and measurable.

## Intended Audience
- Manufacturing operators and leads
- Operations and production supervisors
- Process improvement and reliability teams
- Anyone interested in how real-world production systems behave

## What This Repository Is
- Lightweight analytical tools
- Simple models grounded in plant-floor reality
- Read-only, offline analysis using representative or synthetic data
- Focused on safety, throughput, and consistency

## What This Repository Is Not
- Production software
- Connected to live plant systems
- A replacement for established MES, CMMS, or safety platforms
- A critique of any specific facility or organization

## Core Areas of Focus
- Downtime pattern recognition
- Throughput sensitivity and constraints
- Safety observation trends
- Shift-to-shift continuity and handoff clarity

## Safety and Data Notes
All example data used in this repository is synthetic or anonymized.  
No proprietary systems, processes, or confidential information are referenced or required.

## Repository Structure

/data - Example datasets (synthetic)
/tools - Small analysis scripts
/models - Simple throughput and constraint models
/docs - Assumptions, limitations, and future ideas

## Quick Start

Run a tool directly:

- Downtime Pattern Analyzer:
  - `python tools/downtime_analyzer.py data/sample_downtime.csv`
- Throughput Sensitivity Model:
  - `python tools/throughput_model.py --nominal-rate 120 --minor-stops-per-hour 3 --avg-minor-stop-min 2 --changeovers-per-shift 1 --changeover-min 25 --shift-length-hours 12`
- Safety Observation Trend Analyzer:
  - `python tools/safety_trend_analyzer.py data/sample_safety_observations.csv`
- Shift Handoff Validator:
  - `python tools/handoff_validator.py docs/sample_handoff.md`

Use the unified runner:

- `python tools/run.py downtime --csv data/sample_downtime.csv`
- `python tools/run.py throughput --nominal-rate 120 --minor-stops-per-hour 3 --avg-minor-stop-min 2 --changeovers-per-shift 1 --changeover-min 25 --shift-length-hours 12`
- `python tools/run.py safety --csv data/sample_safety_observations.csv`
- `python tools/run.py handoff-validate --file docs/sample_handoff.md`
- `python tools/run.py test`

Run tests:

- `python -m compileall .`
- `python -m unittest`

## Tools
- [Downtime Pattern Analyzer](docs/tool_downtime_analyzer.md)
- [Throughput Sensitivity Model](docs/tool_throughput_model.md)
- [Safety Observation Trend Analyzer](docs/tool_safety_trend_analyzer.md)
- [Shift Handoff Template + Validator](docs/tool_handoff_validator.md)

### Downtime Pattern Analyzer (example output)
```
Top causes by downtime minutes:
- Sensor fault: 96 min (30.8%)
- Material jam: 72 min (23.1%)
- Changeover: 60 min (19.2%)

Downtime minutes by shift:
- A: 88 min
- B: 140 min
- C: 84 min
```

### Throughput Sensitivity Model (example output)
```
Expected output per shift: 1,420 units
Downtime breakdown (minutes):
- Minor stops: 72.0
- Changeovers: 25.0

Sensitivity (+/-10% impact, units):
- nominal_rate: 142.0
- shift_length_hours: 142.0
- minor_stops_per_hour: 24.0
```

### Safety Observation Trend Analyzer (example output)
```
Counts by category and severity:
- Housekeeping / LOW: 14
- Guarding / MED: 9
- Ergonomics / LOW: 7

Near-miss rate: 18.0% (18 of 100)
Time-to-close (days): avg 4.6, median 4.0; open items: 7
```

### Shift Handoff Validator (example output)
```
Handoff validation: PASSED
Required sections found: 7
Open Actions entries: 2
```

## Design Philosophy
Manufacturing systems are complex, tightly coupled, and sensitive to small changes.  
These tools favor transparency and interpretability over complexity.

## Future Directions
Potential areas for exploration include:
- Predictive indicators for recurring downtime
- Read-only integration concepts for equipment signals
- Structured safety observation trend analysis
- Improved shift handoff standardization
