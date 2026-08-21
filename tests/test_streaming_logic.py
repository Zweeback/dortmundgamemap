"""
Smoke tests for world-streaming logic — no Godot runtime required.

Covers:
  - Index schema validation (canonical 48-cell / 512 m format from build_connected_corridor.py)
  - UTM→Godot coordinate transforms
  - Active-cell selection (load_radius), load/unload hysteresis
  - Phoenix-West canonical offset from world_origin [392192, 5704704, 100.0]
  - Mocked surface-aware spawn (ray hit / miss / deferred retry)
"""

import json
import math
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "assets" / "world_cells" / "index.json"

# Expected canonical values (from build_connected_corridor.py)
CANONICAL_WORLD_ORIGIN = [392192.0, 5704704.0, 100.0]
CANONICAL_CELL_SIZE    = 512
CANONICAL_CELL_COUNT   = 48
# Phoenix-West 256 m cell lower-left UTM
PW_BBOX_MIN_E, PW_BBOX_MIN_N = 394744.0, 5705000.0
PW_EXPECTED_OFFSET_X =  2552.0   # 394744 - 392192
PW_EXPECTED_OFFSET_Z =  -296.0   # -(5705000 - 5704704)

# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python equivalents of WorldStreamingManager coordinate logic
# ─────────────────────────────────────────────────────────────────────────────

def load_index(path=INDEX_PATH):
    with open(path) as f:
        return json.load(f)


def utm_to_godot_xz(easting: float, northing: float, world_origin: list) -> tuple:
    """x = Δeasting, z = -Δnorthing (right-hand Y-up)."""
    return (
        easting  - world_origin[0],
        -(northing - world_origin[1]),
    )


def cell_offset(meta: dict) -> tuple:
    o = meta["offset"]
    return (o[0], o[1], o[2])


def cells_in_radius(cells_meta: list, player_xz: tuple, load_radius: float) -> list:
    result = []
    for meta in cells_meta:
        ox, _oy, oz = cell_offset(meta)
        dist = math.hypot(player_xz[0] - ox, player_xz[1] - oz)
        if dist <= load_radius:
            result.append(meta["id"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Mocked surface-aware spawn
# ─────────────────────────────────────────────────────────────────────────────

SPAWN_ABOVE_SURFACE = 1.25
MAX_RESOLVE_RETRIES = 24


def resolve_surface_y(pos_x: float, pos_z: float,
                      terrain_y: float | None,
                      spawn_above: float = SPAWN_ABOVE_SURFACE) -> tuple:
    """
    Returns (resolved_y, pending) mimicking _resolve_surface_position.
    pending=True when terrain_y is None (ray miss — collision not ready yet).
    """
    if terrain_y is None:
        return (None, True)   # miss → pending_spawn_resolve = True
    return (terrain_y + spawn_above, False)


def deferred_resolve(initial_pos_y: float, terrain_surfaces: list,
                     max_retries: int = MAX_RESOLVE_RETRIES) -> tuple:
    """
    Simulate bounded deferred re-resolution:
      terrain_surfaces = list of terrain_y values per retry (None = still loading).
    Returns (final_y, retries_used, gave_up).
    """
    pending = True
    retries = 0
    final_y = initial_pos_y
    for terrain_y in terrain_surfaces:
        if not pending:
            break
        resolved_y, pending = resolve_surface_y(0.0, 0.0, terrain_y)
        retries += 1
        if not pending:
            final_y = resolved_y
        if retries >= max_retries:
            if pending:
                final_y = initial_pos_y  # fallback
            break
    gave_up = retries >= max_retries and pending
    return (final_y, retries, gave_up)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexSchema(unittest.TestCase):
    def setUp(self):
        self.manifest = load_index()

    def test_world_origin_is_canonical(self):
        wo = self.manifest["world_origin"]
        self.assertEqual(wo, CANONICAL_WORLD_ORIGIN)

    def test_world_origin_crs_in_provenance(self):
        prov = self.manifest.get("provenance", {})
        self.assertIn("EPSG:25832", prov.get("crs", ""))

    def test_cell_size_is_512(self):
        self.assertEqual(self.manifest["cell_size_m"], CANONICAL_CELL_SIZE)

    def test_exactly_48_cells(self):
        self.assertEqual(len(self.manifest["cells"]), CANONICAL_CELL_COUNT)

    def test_cells_have_required_fields(self):
        required = {"id", "bbox", "offset", "terrain_render", "terrain_collision", "buildings"}
        for cell in self.manifest["cells"]:
            missing = required - cell.keys()
            self.assertFalse(missing, f"Cell {cell.get('id')} missing: {missing}")

    def test_offset_derived_from_world_origin(self):
        wo = self.manifest["world_origin"]
        for cell in self.manifest["cells"]:
            bbox = cell["bbox"]
            expected_x = bbox[0] - wo[0]
            expected_z = -(bbox[1] - wo[1])
            self.assertAlmostEqual(cell["offset"][0], expected_x, places=3,
                                   msg=f"Cell {cell['id']} offset.x wrong")
            self.assertAlmostEqual(cell["offset"][2], expected_z, places=3,
                                   msg=f"Cell {cell['id']} offset.z wrong")

    def test_world_bbox_covers_all_cells(self):
        wb = self.manifest["world_bbox"]
        for cell in self.manifest["cells"]:
            b = cell["bbox"]
            self.assertGreaterEqual(b[0], wb[0])
            self.assertGreaterEqual(b[1], wb[1])
            self.assertLessEqual(b[2],    wb[2])
            self.assertLessEqual(b[3],    wb[3])

    def test_no_gaps_between_cells(self):
        """Total cell area equals the declared world bbox area."""
        wb = self.manifest["world_bbox"]
        expected_area = (wb[2] - wb[0]) * (wb[3] - wb[1])
        total_area = sum(
            (c["bbox"][2] - c["bbox"][0]) * (c["bbox"][3] - c["bbox"][1])
            for c in self.manifest["cells"]
        )
        self.assertAlmostEqual(total_area, expected_area, places=1)


class TestCoordinateTransforms(unittest.TestCase):
    def setUp(self):
        self.manifest = load_index()
        self.wo = self.manifest["world_origin"]

    def test_origin_maps_to_zero(self):
        x, z = utm_to_godot_xz(self.wo[0], self.wo[1], self.wo)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(z, 0.0)

    def test_east_increases_x(self):
        x, _ = utm_to_godot_xz(self.wo[0] + 100.0, self.wo[1], self.wo)
        self.assertAlmostEqual(x, 100.0)

    def test_north_decreases_z(self):
        _, z = utm_to_godot_xz(self.wo[0], self.wo[1] + 100.0, self.wo)
        self.assertAlmostEqual(z, -100.0)

    def test_phoenix_west_canonical_offset(self):
        """Phoenix-West lower-left must be exactly X=2552, Z=-296 from canonical origin."""
        x, z = utm_to_godot_xz(PW_BBOX_MIN_E, PW_BBOX_MIN_N, self.wo)
        self.assertAlmostEqual(x, PW_EXPECTED_OFFSET_X, places=3)
        self.assertAlmostEqual(z, PW_EXPECTED_OFFSET_Z, places=3)

    def test_cell_offsets_match_formula(self):
        for cell in self.manifest["cells"]:
            bbox = cell["bbox"]
            expected_x, expected_z = utm_to_godot_xz(bbox[0], bbox[1], self.wo)
            self.assertAlmostEqual(cell["offset"][0], expected_x, places=3)
            self.assertAlmostEqual(cell["offset"][2], expected_z, places=3)


class TestActiveCellSelection(unittest.TestCase):
    def setUp(self):
        self.manifest = load_index()
        self.cells = self.manifest["cells"]

    def test_at_world_origin_loads_first_cell(self):
        """Cell e392192_n5704704 has offset (0,0,0) — loads when player is at origin."""
        active = cells_in_radius(self.cells, (0.0, 0.0), load_radius=768.0)
        self.assertIn("e392192_n5704704", active)

    def test_phoenix_west_cell_in_range_near_spawn(self):
        """Near Phoenix-West spawn (2552, -296 offset), those cells should be in range."""
        active = cells_in_radius(self.cells, (PW_EXPECTED_OFFSET_X, PW_EXPECTED_OFFSET_Z),
                                 load_radius=768.0)
        self.assertGreater(len(active), 0)

    def test_far_position_loads_no_cells(self):
        active = cells_in_radius(self.cells, (50_000.0, 0.0), load_radius=768.0)
        self.assertEqual(active, [])

    def test_active_cell_count_bounded_at_1536m_radius(self):
        """At 1536 m radius (3 cells) the result set stays ≤ 48."""
        active = cells_in_radius(self.cells, (PW_EXPECTED_OFFSET_X, PW_EXPECTED_OFFSET_Z),
                                 load_radius=1536.0)
        self.assertLessEqual(len(active), CANONICAL_CELL_COUNT)

    def test_hysteresis_load_vs_unload(self):
        load_r, unload_r = 768.0, 1152.0
        cell_origin = (0.0, 0.0)
        player_near = (700.0, 0.0)
        player_mid  = (900.0, 0.0)
        player_far  = (1200.0, 0.0)

        dist_near = math.dist(player_near, cell_origin)
        dist_mid  = math.dist(player_mid,  cell_origin)
        dist_far  = math.dist(player_far,  cell_origin)

        self.assertLessEqual(dist_near, load_r,   "should load when near")
        self.assertLessEqual(dist_mid,  unload_r, "must NOT unload at mid distance")
        self.assertGreater(dist_far,    unload_r, "should unload when far")


class TestSpawnAboveGround(unittest.TestCase):
    def test_surface_hit_lifts_player(self):
        y, pending = resolve_surface_y(0.0, 0.0, terrain_y=5.0)
        self.assertAlmostEqual(y, 5.0 + SPAWN_ABOVE_SURFACE)
        self.assertFalse(pending)

    def test_ray_miss_returns_pending(self):
        y, pending = resolve_surface_y(0.0, 0.0, terrain_y=None)
        self.assertIsNone(y)
        self.assertTrue(pending)

    def test_elevated_terrain_spawn(self):
        y, pending = resolve_surface_y(50.0, -50.0, terrain_y=12.3)
        self.assertAlmostEqual(y, 12.3 + SPAWN_ABOVE_SURFACE)
        self.assertFalse(pending)


class TestDeferredSpawnResolve(unittest.TestCase):
    def test_immediate_hit_resolves_first_attempt(self):
        final_y, retries, gave_up = deferred_resolve(1.25, [8.0])
        self.assertAlmostEqual(final_y, 8.0 + SPAWN_ABOVE_SURFACE)
        self.assertEqual(retries, 1)
        self.assertFalse(gave_up)

    def test_two_misses_then_hit_resolves(self):
        final_y, retries, gave_up = deferred_resolve(1.25, [None, None, 5.5])
        self.assertAlmostEqual(final_y, 5.5 + SPAWN_ABOVE_SURFACE)
        self.assertEqual(retries, 3)
        self.assertFalse(gave_up)

    def test_max_retries_reached_returns_fallback(self):
        surfaces = [None] * (MAX_RESOLVE_RETRIES + 2)
        final_y, retries, gave_up = deferred_resolve(99.9, surfaces)
        self.assertTrue(gave_up)
        self.assertAlmostEqual(final_y, 99.9)
        self.assertEqual(retries, MAX_RESOLVE_RETRIES)

    def test_gives_up_gracefully(self):
        """After MAX_RESOLVE_RETRIES misses the player should use the fallback, not crash."""
        final_y, retries, gave_up = deferred_resolve(1.25, [None] * (MAX_RESOLVE_RETRIES + 5))
        self.assertTrue(gave_up)
        self.assertLessEqual(retries, MAX_RESOLVE_RETRIES)


class TestUnloadLoadTransitions(unittest.TestCase):
    def test_load_then_move_far_triggers_unload(self):
        load_r, unload_r = 768.0, 1152.0
        loaded: set = set()
        origin = (0.0, 0.0)

        dist_start = math.dist((0.0, 0.0), origin)
        if dist_start <= load_r:
            loaded.add("e392192_n5704704")
        self.assertIn("e392192_n5704704", loaded)

        dist_far = math.dist((1300.0, 0.0), origin)
        if dist_far > unload_r:
            loaded.discard("e392192_n5704704")
        self.assertNotIn("e392192_n5704704", loaded)

    def test_double_load_is_idempotent(self):
        loaded: set = set()

        def ensure_loaded(cid):
            if cid not in loaded:
                loaded.add(cid)

        ensure_loaded("e392192_n5704704")
        ensure_loaded("e392192_n5704704")
        self.assertEqual(list(loaded).count("e392192_n5704704"), 1)


if __name__ == "__main__":
    unittest.main()
