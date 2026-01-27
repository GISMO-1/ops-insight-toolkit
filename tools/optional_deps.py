"""Optional dependency helpers for Tool Builder.

README
Purpose: Provide safe helpers to detect optional dependencies without raising import errors.
Inputs/Outputs: No inputs beyond the Python environment; outputs booleans, modules, and messages.
Example command: python -m tools.optional_deps --self-check
Self-check: python -m tools.optional_deps --self-check
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from typing import Any


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _try_import(module_name: str, disable_env: str) -> tuple[bool, Any | None, str | None]:
    if _env_flag(disable_env):
        return False, None, f"{module_name} disabled via {disable_env}."
    if importlib.util.find_spec(module_name) is None:
        return False, None, f"{module_name} is not installed."
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - never raise on optional deps
        return False, None, f"{module_name} import failed: {exc}"
    return True, module, None


def has_pandas() -> bool:
    ok, _, _ = try_import_pandas()
    return ok


def has_matplotlib() -> bool:
    ok, _, _ = try_import_matplotlib()
    return ok


def try_import_pandas() -> tuple[bool, Any | None, str | None]:
    return _try_import("pandas", "MOIT_DISABLE_PANDAS")


def try_import_matplotlib() -> tuple[bool, Any | None, str | None]:
    return _try_import("matplotlib", "MOIT_DISABLE_MATPLOTLIB")


def self_check() -> tuple[bool, str]:
    ok, _module, message = try_import_pandas()
    if ok:
        return True, "Optional dependency helpers available."
    return True, f"Optional dependency helpers available. ({message})"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder optional dependency utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick optional dependency self-check")
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
