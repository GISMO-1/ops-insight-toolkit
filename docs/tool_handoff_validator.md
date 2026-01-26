# Shift Handoff Validator

## Purpose
Validate that a shift handoff markdown file includes required sections and that the Open Actions section is not empty.

## Required Sections
- Safety Notes
- Quality Concerns
- Equipment Issues
- Downtime Summary
- Workarounds In Place
- Watchlist Next Shift
- Open Actions

## Example Command
```bash
python tools/handoff_validator.py docs/sample_handoff.md
```

## Example Output
```
Handoff validation: PASSED
Required sections found: 7
Open Actions entries: OK
```
