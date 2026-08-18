import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds
import trimesh

ROOT = Path(__file__).resolve().parents[1]

# Load build_connected_corridor module
SPEC_CORRIDOR = importlib.util.spec_from_file_location("build_connected_corridor", ROOT / "tools" / "build_connected_corridor.py")
mod_corridor = importlib.util.module_from_spec(SPEC_CORRIDOR)
assert SPEC_CORRIDOR.loader
SPEC_CORRIDOR.loader.exec_module(mod_corridor)

# Load build_terrain module
SPEC_TERRAIN = importlib.util.spec_from_file_location("build_terrain", ROOT / "tools" / "build_terrain.py")
mod_terrain = importlib.util.module_from_spec(SPEC_TERRAIN)
assert SPEC_TERRAIN.loader
SPEC_TERRAIN.loader.exec_module(mod_terrain)


class ConnectedCorridorSeamTest(unittest.TestCase):
    def test_corridor_grid_layout_48_cells(self):
        min_e, min_n = mod_corridor.MIN_E, mod_corridor.MIN_N
        max_e, max_n = mod_corridor.MAX_E, mod_corridor.MAX_N
        cell_size = mod_corridor.CELL_SIZE

        cols = (max_e - min_e) // cell_size  # (395264 - 392192) / 512 = 6
        rows = (max_n - min_n) // cell_size  # (5708800 - 5704704) / 512 = 8
        self.assertEqual(cols * rows, 48)

        grid = {}
        for r in range(rows):
            for c in range(cols):
                e0 = min_e + c * cell_size
                n0 = min_n + r * cell_size
                grid[(e0, n0)] = (e0, n0, e0 + cell_size, n0 + cell_size)

        self.assertEqual(len(grid), 48)

    def test_no_gaps_or_overlaps_in_grid(self):
        min_e, min_n = mod_corridor.MIN_E, mod_corridor.MIN_N
        max_e, max_n = mod_corridor.MAX_E, mod_corridor.MAX_N
        cell_size = mod_corridor.CELL_SIZE

        cells_bbox = []
        for n in range(min_n, max_n, cell_size):
            for e in range(min_e, max_e, cell_size):
                cells_bbox.append([e, n, e + cell_size, n + cell_size])

        self.assertEqual(len(cells_bbox), 48)

        # Total coverage area check
        total_area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in cells_bbox)
        expected_area = (max_e - min_e) * (max_n - min_n)
        self.assertEqual(total_area, expected_area)

        # Check pairwise overlap/gap
        for i, b1 in enumerate(cells_bbox):
            for j, b2 in enumerate(cells_bbox):
                if i >= j:
                    continue
                # Overlap test: intersection area must be 0
                ix0, ix1 = max(b1[0], b2[0]), min(b1[2], b2[2])
                iy0, iy1 = max(b1[1], b2[1]), min(b1[3], b2[3])
                if ix0 < ix1 and iy0 < iy1:
                    overlap_area = (ix1 - ix0) * (iy1 - iy0)
                    self.assertEqual(overlap_area, 0, f"Cells {i} and {j} overlap!")

    def test_canonical_world_origin(self):
        origin = mod_corridor.CANONICAL_WORLD_ORIGIN
        self.assertEqual(origin, [392192, 5704704, 100.0])
        self.assertEqual(mod_corridor.CRS, "EPSG:25832")

    def test_phoenix_west_coexistence(self):
        # Phoenix West 256m cell bbox: [394744.0, 5705000.0, 395000.0, 5705256.0]
        pw_bbox = [394744.0, 5705000.0, 395000.0, 5705256.0]
        min_e, min_n = mod_corridor.MIN_E, mod_corridor.MIN_N
        max_e, max_n = mod_corridor.MAX_E, mod_corridor.MAX_N

        # Verify Phoenix West bbox is completely contained inside the 48-cell corridor world bounds
        self.assertGreaterEqual(pw_bbox[0], min_e)
        self.assertLessEqual(pw_bbox[2], max_e)
        self.assertGreaterEqual(pw_bbox[1], min_n)
        self.assertLessEqual(pw_bbox[3], max_n)

        # Verify exact offset from canonical origin without fake alignment constants
        origin_e, origin_n, _ = mod_corridor.CANONICAL_WORLD_ORIGIN
        pw_offset_x = pw_bbox[0] - origin_e
        pw_offset_z = -(pw_bbox[1] - origin_n)

        self.assertEqual(pw_offset_x, 2552.0)
        self.assertEqual(pw_offset_z, -296.0)

    def test_terrain_seam_numerical_continuity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create 2 neighboring 512m cells with continuous synthetic elevation: Z(e, n) = 0.005 * e + 0.002 * n
            # Cell A (West): [392192, 5704704, 392704, 5705216]
            # Cell B (East): [392704, 5704704, 393216, 5705216]
            def make_dgm(tif_path, e_min, n_min, e_max, n_max):
                w, h = 512, 512
                arr = np.zeros((h, w), dtype=np.float64)
                for r in range(h):
                    n = n_max - (r + 0.5)
                    for c in range(w):
                        e = e_min + (c + 0.5)
                        arr[r, c] = 0.005 * e + 0.002 * n
                transform = from_bounds(e_min, n_min, e_max, n_max, w, h)
                with rasterio.open(tif_path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float64", transform=transform, crs="EPSG:25832") as dst:
                    dst.write(arr, 1)

            tif_a = tmp / "a.tif"
            tif_b = tmp / "b.tif"
            make_dgm(tif_a, 392192, 5704704, 392704, 5705216)
            make_dgm(tif_b, 392704, 5704704, 393216, 5705216)

            glb_a = tmp / "a.glb"
            glb_b = tmp / "b.glb"

            mod_terrain.build_mesh(tif_a, glb_a, step=4, origin_e=392192, origin_n=5704704, vertical_origin=100.0)
            mod_terrain.build_mesh(tif_b, glb_b, step=4, origin_e=392704, origin_n=5704704, vertical_origin=100.0)

            scene_a = trimesh.load(glb_a, force="scene")
            scene_b = trimesh.load(glb_b, force="scene")

            mesh_a = trimesh.util.concatenate(list(scene_a.geometry.values()))
            mesh_b = trimesh.util.concatenate(list(scene_b.geometry.values()))

            # Edge vertices on shared boundary (Easting 392704)
            # In Cell A local space: x = 512
            # In Cell B local space: x = 0
            pts_a = mesh_a.vertices[np.isclose(mesh_a.vertices[:, 0], 512.0)]
            pts_b = mesh_b.vertices[np.isclose(mesh_b.vertices[:, 0], 0.0)]

            # Sort by Z coordinate
            pts_a = pts_a[np.argsort(pts_a[:, 2])]
            pts_b = pts_b[np.argsort(pts_b[:, 2])]

            self.assertEqual(len(pts_a), len(pts_b))

            max_z_diff = np.max(np.abs(pts_a[:, 2] - pts_b[:, 2]))
            max_y_diff = np.max(np.abs(pts_a[:, 1] - pts_b[:, 1]))

            # Discontinuity tolerance <= 1e-4 meters
            self.assertLess(max_z_diff, 1e-4)
            self.assertLess(max_y_diff, 1e-4)


if __name__ == "__main__":
    unittest.main()
