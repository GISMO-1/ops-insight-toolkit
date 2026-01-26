"""Shift handoff markdown validator.

README
Purpose: Validate shift handoff Markdown files for required sections and entries.
Inputs/Outputs: Markdown input path; returns a text validation report string.
Example command: python tools/handoff_validator.py docs/sample_handoff.md
Self-check: python tools/handoff_validator.py --self-check
"""

from __future__ import annotations

import argparse
import os
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


def get_tool_metadata() -> dict:
    return {
        "name": "Shift Handoff Validator",
        "description": "Checks handoff Markdown for required sections and open actions.",
        "input_type": "handoff",
    }


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


def run_analysis(input_path: str) -> str:
    errors = validate_handoff(input_path)
    if errors:
        lines = ["Handoff validation: FAILED"]
        lines.extend(f"- {error}" for error in errors)
        return "\n".join(lines)
    return "\n".join(
        [
            "Handoff validation: PASSED",
            f"Required sections found: {len(REQUIRED_HEADINGS)}",
            "Open Actions entries: OK",
        ]
    )


def self_check() -> tuple[bool, str]:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sample_path = os.path.join(repo_root, "docs", "sample_handoff.md")
    try:
        report = run_analysis(sample_path)
    except (HandoffValidationError, OSError) as exc:
        return False, f"Self-check failed: {exc}"
    if "FAILED" in report:
        return False, "Self-check failed: sample handoff did not validate."
    return True, "Self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a shift handoff Markdown file.")
    parser.add_argument("file", nargs="?", help="Path to handoff markdown")
    parser.add_argument("--self-check", action="store_true", help="Run a quick self-check")
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1

    if not args.file:
        parser.print_usage()
        return 1

    try:
        report = run_analysis(args.file)
    except (HandoffValidationError, OSError) as exc:
        print(f"Error: {exc}")
        return 1

    print(report)
    return 0 if "FAILED" not in report else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
