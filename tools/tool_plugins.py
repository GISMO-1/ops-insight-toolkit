"""Tool Builder Plugins: discover and run custom plugin tools.

README
Purpose: Load Python plugin files that expose a run_plugin(df) callable for additional analysis steps.
Inputs/Outputs: Inputs are a plugins folder path and a data table; outputs plugin results or errors.
Example command: python -m tools.tool_plugins --self-check
Self-check: python -m tools.tool_plugins --self-check
"""

from __future__ import annotations

import argparse
import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from tools import optional_deps


@dataclass
class PluginTool:
    name: str
    path: Path
    module: ModuleType
    runner: Callable[[Any], Any]
    requires_pandas: bool = True


@dataclass
class PluginStatus:
    enabled: bool
    message: str


def load_plugins(folder: str | Path) -> tuple[list[PluginTool], list[str]]:
    path = Path(folder)
    if not path.exists():
        return [], [f"Plugins folder not found: {path}"]
    plugins: list[PluginTool] = []
    errors: list[str] = []
    for plugin_path in sorted(path.glob("*.py")):
        if plugin_path.name.startswith("_"):
            continue
        module_name = f"tool_builder_plugin_{plugin_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            errors.append(f"Unable to load plugin: {plugin_path.name}")
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - surface plugin errors
            errors.append(f"{plugin_path.name}: {exc}")
            continue
        runner = getattr(module, "run_plugin", None)
        if not callable(runner):
            errors.append(f"{plugin_path.name}: missing run_plugin(df) function")
            continue
        plugins.append(
            PluginTool(
                name=plugin_path.stem,
                path=plugin_path,
                module=module,
                runner=runner,
            )
        )
    return plugins, errors


def plugin_status() -> PluginStatus:
    available = optional_deps.has_pandas()
    if available:
        return PluginStatus(enabled=True, message="Ready")
    return PluginStatus(
        enabled=False,
        message="Requires pandas. Install optional dependencies to enable plugins.",
    )


def run_plugin_safe(plugin: PluginTool, df: Any) -> tuple[bool, Any, str]:
    status = plugin_status()
    if not status.enabled:
        return False, None, status.message
    try:
        return True, plugin.runner(df), ""
    except Exception as exc:  # noqa: BLE001 - plugin errors should not crash GUI
        return False, None, f"{exc}\n{traceback.format_exc()}"


def self_check() -> tuple[bool, str]:
    tmp_dir = Path(".tool_plugins_tmp")
    try:
        tmp_dir.mkdir(exist_ok=True)
        plugin_path = tmp_dir / "sample_plugin.py"
        plugin_path.write_text(
            "def run_plugin(df):\n    return df\n",
            encoding="utf-8",
        )
        plugins, errors = load_plugins(tmp_dir)
        if errors:
            return False, f"Unexpected plugin errors: {errors}"
        if not plugins:
            return False, "Plugin load failed."
        status = plugin_status()
        if not status.enabled:
            return True, f"Plugin load ok; {status.message}"
        ok, result, error = run_plugin_safe(plugins[0], {"sample": 1})
        if not ok:
            return False, f"Plugin runner failed: {error}"
        if result is None:
            return False, "Plugin runner returned no result."
        return True, "Tool plugins self-check passed."
    finally:
        if tmp_dir.exists():
            for file in tmp_dir.glob("*"):
                file.unlink()
            tmp_dir.rmdir()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder plugin utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick plugin self-check")
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
