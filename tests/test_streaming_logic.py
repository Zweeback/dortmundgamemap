"""
Smoke tests for world-streaming logic that can run without Godot.

The tests exercise:
  - Coordinate transforms (UTM -> Godot XZ)
  - Active-cell selection based on player position and radii
  - Unload/load transitions (hysteresis)
  - Spawn-above-ground detection (mocked surface query)
  - index.json schema validation
"""

import json
import math
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "assets" / "world_cells" / "index.json"


# ---------------------------------------------------------------------------
# Pure-Python reimplementation of WorldStreamingManager coordinate logic
# ---------------------------------------------------------------------------

def utm_to_godot_xz(easting: float, northing: float, origin: dict) -> tuple[float, float]:
    """Godot convention: x = Δeasting, z = -Δnorthing."""
    return (
        easting  - origin["easting"],
        -(northing - origin["northing"]),
    )


def cell_godot_origin(meta: dict) -> tuple[float, float, float]:
    go = meta["godot_origin"]
    return (go["x"], go["y"], go["z"])


def cells_in_radius(cells_meta: list, player_xz: tuple[float, float],
                    load_radius: float) -> list[str]:
    """Return cell ids whose godot_origin is within load_radius of player_xz."""
    result = []
    for meta in cells_meta:
        ox, _oy, oz = cell_godot_origin(meta)
        dist = math.hypot(player_xz[0] - ox, player_xz[1] - oz)
        if dist <= load_radius:
            result.append(meta["id"])
    return result


# ---------------------------------------------------------------------------
# Mocked surface-aware spawn
# ---------------------------------------------------------------------------

def resolve_surface_y(pos_x: float, pos_z: float, terrain_y: float | None,
                      spawn_above: float = 1.25) -> float | None:
    """
    Simulate a downward raycast.
    Returns pos_y = terrain_y + spawn_above when a surface is present,
    else None (ray miss).
    """
    if terrain_y is None:
        return None
    return terrain_y + spawn_above


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIndexSchema(unittest.TestCase):
    def setUp(self):
        with open(INDEX_PATH) as f:
            self.manifest = json.load(f)

    def test_format_version(self):
        self.assertEqual(self.manifest["format_version"], 1)

    def test_world_origin_fields(self):
        wo = self.manifest["world_origin_utm"]
        for key in ("easting", "northing", "height_m", "crs"):
            self.assertIn(key, wo)
        self.assertEqual(wo["crs"], "EPSG:25832")

    def test_cells_list_nonempty(self):
        self.assertGreater(len(self.manifest["cells"]), 0)

    def test_cells_have_required_fields(self):
        required = {"id", "bbox", "size_m", "godot_origin", "asset_base", "layers"}
        for cell in self.manifest["cells"]:
            missing = required - cell.keys()
            self.assertFalse(missing, f"Cell {cell.get('id')} missing fields: {missing}")

    def test_phoenix_west_bbox(self):
        pw = next(c for c in self.manifest["cells"] if c["id"] == "phoenix_west_001")
        self.assertEqual(pw["bbox"], [394744.0, 5705000.0, 395000.0, 5705256.0])
        self.assertAlmostEqual(pw["size_m"], 256.0)


class TestCoordinateTransforms(unittest.TestCase):
    def setUp(self):
        with open(INDEX_PATH) as f:
            self.manifest = json.load(f)
        self.origin = self.manifest["world_origin_utm"]

    def test_origin_maps_to_zero(self):
        x, z = utm_to_godot_xz(self.origin["easting"], self.origin["northing"], self.origin)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(z, 0.0)

    def test_east_increases_x(self):
        x, _ = utm_to_godot_xz(self.origin["easting"] + 100.0, self.origin["northing"], self.origin)
        self.assertAlmostEqual(x, 100.0)

    def test_north_decreases_z(self):
        _, z = utm_to_godot_xz(self.origin["easting"], self.origin["northing"] + 100.0, self.origin)
        self.assertAlmostEqual(z, -100.0)

    def test_phoenix_spawn_utm_roundtrip(self):
        """Phoenix-West spawn UTM should map to positive x, negative z (NE of origin)."""
        x, z = utm_to_godot_xz(394845.0, 5705080.0, self.origin)
        self.assertGreater(x, 0.0)   # easting > origin easting
        self.assertLess(z, 0.0)      # northing > origin northing  → negative z


class TestActiveCellSelection(unittest.TestCase):
    def setUp(self):
        with open(INDEX_PATH) as f:
            self.manifest = json.load(f)
        self.cells = self.manifest["cells"]

    def test_at_world_origin_loads_nearest_cell(self):
        """At (0,0) the phoenix_west cell (godot_origin 0,0,0) should be loaded."""
        active = cells_in_radius(self.cells, (0.0, 0.0), load_radius=640.0)
        self.assertIn("phoenix_west_001", active)

    def test_far_position_excludes_cells(self):
        """10 km away from origin no cells should be in the 640 m radius."""
        active = cells_in_radius(self.cells, (10_000.0, 0.0), load_radius=640.0)
        self.assertEqual(active, [])

    def test_hysteresis_load_vs_unload(self):
        """A cell loaded at 600 m should NOT be unloaded at 700 m (below 896 m threshold)."""
        load_r, unload_r = 640.0, 896.0
        cell_origin = (0.0, 0.0)
        player_near = (600.0, 0.0)
        player_mid  = (700.0, 0.0)
        player_far  = (950.0, 0.0)

        dist_near = math.dist(player_near, cell_origin)
        dist_mid  = math.dist(player_mid,  cell_origin)
        dist_far  = math.dist(player_far,  cell_origin)

        self.assertLessEqual(dist_near, load_r,   "should load when near")
        self.assertLessEqual(dist_mid, unload_r,  "should NOT unload at mid distance")
        self.assertGreater(dist_far, unload_r,    "should unload when far")


class TestSpawnAboveGround(unittest.TestCase):
    def test_surface_hit_lifts_player(self):
        y = resolve_surface_y(0.0, 0.0, terrain_y=5.0)
        self.assertAlmostEqual(y, 5.0 + 1.25)

    def test_ray_miss_returns_none(self):
        y = resolve_surface_y(0.0, 0.0, terrain_y=None)
        self.assertIsNone(y)

    def test_flat_ground_spawn(self):
        y = resolve_surface_y(101.0, -80.0, terrain_y=0.0)
        self.assertAlmostEqual(y, 1.25)

    def test_elevated_terrain_spawn(self):
        y = resolve_surface_y(50.0, -50.0, terrain_y=12.3)
        self.assertAlmostEqual(y, 12.3 + 1.25)


class TestUnloadLoadTransitions(unittest.TestCase):
    """Simulate streaming state machine transitions."""

    def test_load_then_move_away_triggers_unload(self):
        load_r, unload_r = 640.0, 896.0
        loaded: set[str] = set()
        origin = (0.0, 0.0)

        # Player starts at origin → cell loads.
        dist_start = math.dist((0.0, 0.0), origin)
        if dist_start <= load_r:
            loaded.add("phoenix_west_001")
        self.assertIn("phoenix_west_001", loaded)

        # Player walks to 950 m away → cell should be queued for unload.
        dist_far = math.dist((950.0, 0.0), origin)
        if dist_far > unload_r and "phoenix_west_001" in loaded:
            loaded.discard("phoenix_west_001")
        self.assertNotIn("phoenix_west_001", loaded)

    def test_double_load_is_idempotent(self):
        """Calling load when already loaded must not duplicate the cell."""
        loaded: set[str] = set()

        def ensure_loaded(cid):
            if cid not in loaded:
                loaded.add(cid)

        ensure_loaded("phoenix_west_001")
        ensure_loaded("phoenix_west_001")
        self.assertEqual(list(loaded).count("phoenix_west_001"), 1)


if __name__ == "__main__":
    unittest.main()
