import tempfile
import unittest
from pathlib import Path

from tools import handoff_validator


class TestHandoffValidator(unittest.TestCase):
    def test_sample_handoff_valid(self):
        errors = handoff_validator.validate_handoff("docs/sample_handoff.md")
        self.assertEqual(errors, [])

    def test_missing_heading(self):
        content = """
# Shift Handoff

## Safety Notes
- OK

## Open Actions
- Follow up
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "handoff.md"
            path.write_text(content, encoding="utf-8")

            errors = handoff_validator.validate_handoff(path)
            self.assertTrue(any("Missing required heading" in error for error in errors))

    def test_open_actions_empty(self):
        content = """
# Shift Handoff

## Safety Notes
- OK

## Quality Concerns
- None

## Equipment Issues
- None

## Downtime Summary
- None

## Workarounds In Place
- None

## Watchlist Next Shift
- None

## Open Actions

"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "handoff.md"
            path.write_text(content, encoding="utf-8")

            errors = handoff_validator.validate_handoff(path)
            self.assertIn("Open Actions section must contain at least one item.", errors)


if __name__ == "__main__":
    unittest.main()
