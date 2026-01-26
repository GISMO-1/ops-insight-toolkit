"""Shift handoff markdown validator."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_HEADINGS = [
    "Safety Notes",
    "Quality Concerns",
    "Equipment Issues",
    "Downtime Summary",
    "Workarounds In Place",
    "Watchlist Next Shift",
    "Open Actions",
]

HEADING_PATTERN = re.compile(r"^\s*#+\s+(.*)\s*$")


class HandoffValidationError(ValueError):
    """Raised when a handoff document is invalid."""


def _extract_headings(lines: list[str]) -> list[str]:
    headings = []
    for line in lines:
        match = HEADING_PATTERN.match(line)
        if match:
            headings.append(match.group(1).strip())
    return headings


def _open_actions_content(lines: list[str]) -> list[str]:
    content: list[str] = []
    in_open_actions = False
    for line in lines:
        match = HEADING_PATTERN.match(line)
        if match:
            heading = match.group(1).strip()
            if heading == "Open Actions":
                in_open_actions = True
                continue
            if in_open_actions:
                break
        if in_open_actions:
            content.append(line.rstrip())
    return content


def validate_handoff(path: str | Path) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise HandoffValidationError(f"File not found: {file_path}")

    lines = file_path.read_text(encoding="utf-8").splitlines()
    headings = _extract_headings(lines)

    errors = []
    for required in REQUIRED_HEADINGS:
        if required not in headings:
            errors.append(f"Missing required heading: {required}")

    open_actions_lines = _open_actions_content(lines)
    open_actions_content = [line.strip() for line in open_actions_lines if line.strip()]
    if not open_actions_content:
        errors.append("Open Actions section must contain at least one item.")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python tools/handoff_validator.py <path/to/handoff.md>")
        return 1

    try:
        errors = validate_handoff(argv[1])
    except (HandoffValidationError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    if errors:
        print("Handoff validation: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Handoff validation: PASSED")
    print(f"Required sections found: {len(REQUIRED_HEADINGS)}")
    print("Open Actions entries: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
