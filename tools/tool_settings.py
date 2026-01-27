"""Tool Builder Settings: persist user preferences for live updates and sessions.

README
Purpose: Store user-configurable preferences (auto-reload, session restore, update checks) on disk.
Inputs/Outputs: Reads/writes a JSON settings file; returns ToolBuilderSettings dataclass instances.
Example command: python -m tools.tool_settings --self-check
Self-check: python -m tools.tool_settings --self-check
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolBuilderSettings:
    restore_last_session: bool = True
    auto_save_session: bool = True
    auto_reload_csv: bool = False
    silent_csv_reload: bool = False
    auto_reload_plugins: bool = False
    check_updates_on_launch: bool = False
    safe_mode: bool = False
    csv_poll_interval: float = 5.0


def default_settings_path() -> Path:
    return Path.home() / ".moit_tool_builder_settings.json"


def load_settings(path: str | Path) -> ToolBuilderSettings:
    settings_path = Path(path)
    if not settings_path.exists():
        return ToolBuilderSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ToolBuilderSettings()
    return ToolBuilderSettings(
        restore_last_session=bool(payload.get("restore_last_session", True)),
        auto_save_session=bool(payload.get("auto_save_session", True)),
        auto_reload_csv=bool(payload.get("auto_reload_csv", False)),
        silent_csv_reload=bool(payload.get("silent_csv_reload", False)),
        auto_reload_plugins=bool(payload.get("auto_reload_plugins", False)),
        check_updates_on_launch=bool(payload.get("check_updates_on_launch", False)),
        safe_mode=bool(payload.get("safe_mode", False)),
        csv_poll_interval=float(payload.get("csv_poll_interval", 5.0)),
    )


def save_settings(path: str | Path, settings: ToolBuilderSettings) -> None:
    settings_path = Path(path)
    settings_path.write_text(
        json.dumps(
            {
                "restore_last_session": settings.restore_last_session,
                "auto_save_session": settings.auto_save_session,
                "auto_reload_csv": settings.auto_reload_csv,
                "silent_csv_reload": settings.silent_csv_reload,
                "auto_reload_plugins": settings.auto_reload_plugins,
                "check_updates_on_launch": settings.check_updates_on_launch,
                "safe_mode": settings.safe_mode,
                "csv_poll_interval": settings.csv_poll_interval,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def self_check() -> tuple[bool, str]:
    temp_path = Path(".tool_builder_settings_test.json")
    try:
        original = ToolBuilderSettings(
            restore_last_session=False,
            auto_save_session=False,
            auto_reload_csv=False,
            silent_csv_reload=True,
            auto_reload_plugins=False,
            check_updates_on_launch=True,
            safe_mode=True,
            csv_poll_interval=3.5,
        )
        save_settings(temp_path, original)
        loaded = load_settings(temp_path)
        if loaded != original:
            return False, "Settings round-trip failed."
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True, "Tool settings self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder settings utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick settings self-check")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1
    print("Run with --self-check for a quick validation.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
