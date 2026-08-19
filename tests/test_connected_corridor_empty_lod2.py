import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_connected_corridor",
    ROOT / "tools" / "build_connected_corridor.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class EmptyLod2HandlingTest(unittest.TestCase):
    def test_known_empty_cell_is_benign(self):
        output = "RuntimeError: No LoD2 surfaces intersect the cell bbox"
        self.assertTrue(mod.is_empty_lod2_result(output))

    def test_unrelated_converter_error_is_not_benign(self):
        output = "RuntimeError: malformed CityGML geometry"
        self.assertFalse(mod.is_empty_lod2_result(output))


if __name__ == "__main__":
    unittest.main()
