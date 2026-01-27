"""Tool Builder Watchdog: detect file and plugin changes for live reload.

README
Purpose: Monitor files or directories for changes and invoke callbacks without blocking the GUI.
Inputs/Outputs: Inputs are file paths/directories and callbacks; outputs are callback invocations on changes.
Example command: python -m tools.tool_watchdog --self-check
Self-check: python -m tools.tool_watchdog --self-check
"""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


def compute_file_signature(paths: Iterable[Path]) -> dict[Path, float | None]:
    signature: dict[Path, float | None] = {}
    for path in paths:
        try:
            signature[path] = path.stat().st_mtime
        except FileNotFoundError:
            signature[path] = None
    return signature


def compute_directory_signature(folder: Path, pattern: str = "*.py") -> dict[str, float]:
    if not folder.exists():
        return {}
    signature: dict[str, float] = {}
    for path in folder.glob(pattern):
        if path.name.startswith("_"):
            continue
        signature[path.name] = path.stat().st_mtime
    return signature


@dataclass
class DirectoryChange:
    added: set[str]
    removed: set[str]
    modified: set[str]


class FileChangeWatcher:
    def __init__(
        self,
        paths: Iterable[Path],
        interval: float,
        on_change: Callable[[list[Path]], None],
    ) -> None:
        self._paths = list(paths)
        self._interval = interval
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._signature = compute_file_signature(self._paths)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._interval * 2)

    def update_paths(self, paths: Iterable[Path]) -> None:
        with self._lock:
            self._paths = list(paths)
            self._signature = compute_file_signature(self._paths)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            with self._lock:
                paths = list(self._paths)
            new_signature = compute_file_signature(paths)
            changed = [
                path
                for path, mtime in new_signature.items()
                if self._signature.get(path) != mtime
            ]
            if changed:
                self._signature = new_signature
                self._on_change(changed)


class DirectoryWatcher:
    def __init__(
        self,
        folder: Path,
        interval: float,
        on_change: Callable[[DirectoryChange], None],
    ) -> None:
        self._folder = folder
        self._interval = interval
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._signature = compute_directory_signature(folder)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._interval * 2)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            new_signature = compute_directory_signature(self._folder)
            added = set(new_signature) - set(self._signature)
            removed = set(self._signature) - set(new_signature)
            modified = {
                name
                for name, mtime in new_signature.items()
                if name in self._signature and self._signature[name] != mtime
            }
            if added or removed or modified:
                self._signature = new_signature
                self._on_change(DirectoryChange(added=added, removed=removed, modified=modified))


def self_check() -> tuple[bool, str]:
    temp_dir = Path(".tool_watchdog_test")
    temp_dir.mkdir(exist_ok=True)
    sample_file = temp_dir / "sample.py"
    sample_file.write_text("print('one')\n", encoding="utf-8")
    signature_1 = compute_directory_signature(temp_dir)
    time.sleep(0.01)
    sample_file.write_text("print('two')\n", encoding="utf-8")
    signature_2 = compute_directory_signature(temp_dir)
    for path in temp_dir.glob("*"):
        path.unlink()
    temp_dir.rmdir()
    if signature_1 == signature_2:
        return False, "Watchdog self-check failed: signature did not update."
    return True, "Tool watchdog self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder watchdog utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick watchdog self-check")
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
