import os
import unittest

from tools import optional_deps


class OptionalDepsTests(unittest.TestCase):
    def test_try_import_pandas_respects_env_flag(self) -> None:
        original = os.environ.get("MOIT_DISABLE_PANDAS")
        os.environ["MOIT_DISABLE_PANDAS"] = "1"
        try:
            ok, module, message = optional_deps.try_import_pandas()
            self.assertFalse(ok)
            self.assertIsNone(module)
            self.assertIn("disabled", message or "")
        finally:
            if original is None:
                os.environ.pop("MOIT_DISABLE_PANDAS", None)
            else:
                os.environ["MOIT_DISABLE_PANDAS"] = original

    def test_try_import_matplotlib_respects_env_flag(self) -> None:
        original = os.environ.get("MOIT_DISABLE_MATPLOTLIB")
        os.environ["MOIT_DISABLE_MATPLOTLIB"] = "1"
        try:
            ok, module, message = optional_deps.try_import_matplotlib()
            self.assertFalse(ok)
            self.assertIsNone(module)
            self.assertIn("disabled", message or "")
        finally:
            if original is None:
                os.environ.pop("MOIT_DISABLE_MATPLOTLIB", None)
            else:
                os.environ["MOIT_DISABLE_MATPLOTLIB"] = original


if __name__ == "__main__":
    unittest.main()
