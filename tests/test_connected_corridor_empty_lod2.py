import importlib.util
from pathlib import Path
import tempfile
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

    def test_zero_byte_cache_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "asset.glbraw"
            path.touch()
            self.assertFalse(mod.is_nonempty_file(path))
            path.write_bytes(b"glTF")
            self.assertTrue(mod.is_nonempty_file(path))

    def test_promote_never_clobbers_good_raw_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw = root / "asset.glbraw"
            glb = root / "asset.glb"
            raw.write_bytes(b"GOOD_RAW")
            glb.write_bytes(b"STALE_GLB")
            mod.promote_glb(glb, raw)
            self.assertEqual(raw.read_bytes(), b"GOOD_RAW")
            self.assertFalse(glb.exists())

    def test_promote_replaces_invalid_zero_byte_raw(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw = root / "asset.glbraw"
            glb = root / "asset.glb"
            raw.touch()
            glb.write_bytes(b"GOOD_GLB")
            mod.promote_glb(glb, raw)
            self.assertEqual(raw.read_bytes(), b"GOOD_GLB")
            self.assertFalse(glb.exists())


if __name__ == "__main__":
    unittest.main()
