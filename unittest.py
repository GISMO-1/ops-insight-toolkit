"""Shim to enable unittest discovery when running `python -m unittest`."""

from __future__ import annotations

import importlib.util
import os
import sys
import sysconfig
from types import ModuleType
from typing import Any


def _load_stdlib_unittest() -> ModuleType:
    stdlib_path = sysconfig.get_paths()["stdlib"]
    module_path = os.path.join(stdlib_path, "unittest", "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "_stdlib_unittest",
        module_path,
        submodule_search_locations=[os.path.join(stdlib_path, "unittest")],
    )
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load standard library unittest module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_stdlib_unittest = _load_stdlib_unittest()

for name, value in _stdlib_unittest.__dict__.items():
    if name.startswith("__") and name not in {"__all__", "__doc__"}:
        continue
    globals()[name] = value


def load_tests(loader: Any, tests: Any, pattern: str) -> Any:
    start_dir = os.path.dirname(__file__)
    return loader.discover(start_dir)


if __name__ == "__main__":
    _stdlib_unittest.main(module=None)
