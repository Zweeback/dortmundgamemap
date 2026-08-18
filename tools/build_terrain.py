#!/usr/bin/env python3
"""Convert a clipped DGM1 GeoTIFF into Godot-oriented render/collision GLBs with exact seam alignment."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np


def build_mesh(tif: Path, out: Path, step: int, origin_e: float, origin_n: float, vertical_origin: float | None) -> dict:
    try:
        import rasterio
        import trimesh
    except ImportError as exc:
        raise SystemExit("Install requirements-geodata.txt") from exc

    with rasterio.open(tif) as src:
        heights = src.read(1).astype(np.float64)
        if src.nodata is not None:
            heights[heights == src.nodata] = np.nan

        # Replace NaN if any
        if not np.isfinite(heights).all():
            heights = np.nan_to_num(heights, nan=float(np.nanmedian(heights)))

        # Bounding box of GeoTIFF in CRS
        left, bottom, right, top = src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top
        width_m = right - left
        height_m = top - bottom

        # Generate sample grid in cell-local coordinates [0, width_m] x [0, height_m]
        # Number of segments along width/height based on step
        num_x = int(round(width_m / step)) + 1
        num_y = int(round(height_m / step)) + 1

        # Local sample coordinates (relative to cell min Easting / min Northing)
        grid_x_local = np.linspace(0.0, width_m, num_x)
        grid_y_local = np.linspace(0.0, height_m, num_y)  # Northings from 0 to height_m

        # World coordinates for grid
        grid_e = left + grid_x_local  # Easting values (left to right)
        grid_n = bottom + grid_y_local  # Northing values (bottom to top)

        res_x = width_m / src.width
        res_y = height_m / src.height

        # Pixel center positions in Easting / Northing:
        pix_e = left + (np.arange(src.width) + 0.5) * res_x
        pix_n = top - (np.arange(src.height) + 0.5) * res_y

        # We flip heights along row axis so pix_n is strictly ascending:
        heights_asc_n = np.flipud(heights)
        pix_n_asc = pix_n[::-1]

        # Use scipy RegularGridInterpolator with fill_value=None (extrapolates linearly) if available
        try:
            from scipy.interpolate import RegularGridInterpolator
            interp = RegularGridInterpolator((pix_n_asc, pix_e), heights_asc_n, method="linear", bounds_error=False, fill_value=None)
            nn_mesh, ee_mesh = np.meshgrid(grid_n, grid_e, indexing="ij")
            sampled = interp((nn_mesh, ee_mesh))
        except ImportError:
            # Linear extrapolation fallback in pure numpy
            # For 1D array x, y, extrapolate linearly outside [x[0], x[-1]]
            def interp1d_extrap(x_new, x, y):
                y_new = np.interp(x_new, x, y)
                # Extrapolate left
                left_mask = x_new < x[0]
                if np.any(left_mask):
                    slope_left = (y[1] - y[0]) / (x[1] - x[0])
                    y_new[left_mask] = y[0] + slope_left * (x_new[left_mask] - x[0])
                # Extrapolate right
                right_mask = x_new > x[-1]
                if np.any(right_mask):
                    slope_right = (y[-1] - y[-2]) / (x[-1] - x[-2])
                    y_new[right_mask] = y[-1] + slope_right * (x_new[right_mask] - x[-1])
                return y_new

            tmp = np.empty((src.height, num_x), dtype=np.float64)
            for r in range(src.height):
                tmp[r, :] = interp1d_extrap(grid_e, pix_e, heights_asc_n[r, :])
            sampled = np.empty((num_y, num_x), dtype=np.float64)
            for c in range(num_x):
                sampled[:, c] = interp1d_extrap(grid_n, pix_n_asc, tmp[:, c])

        z0 = float(np.nanmin(sampled) if vertical_origin is None else vertical_origin)

        # Build vertices in Godot local space relative to (origin_e, origin_n)
        # Godot convention:
        # x = Easting - origin_e
        # y = height - z0
        # z = -(Northing - origin_n)
        ee_grid, nn_grid = np.meshgrid(grid_e, grid_n)  # shape (num_y, num_x)

        local_x = (ee_grid - origin_e).ravel()
        local_y = (sampled - z0).ravel()
        local_z = (-(nn_grid - origin_n)).ravel()

        vertices = np.column_stack([local_x, local_y, local_z])

        # Faces generation for grid of shape (num_y, num_x)
        faces = []
        w = num_x
        for r in range(num_y - 1):
            base = r * w
            nxt = (r + 1) * w
            for c in range(w - 1):
                a = base + c
                b = base + c + 1
                c0 = nxt + c
                d = nxt + c + 1
                faces.extend([(a, c0, b), (b, c0, d)])

        mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)
        mesh.remove_unreferenced_vertices()
        out.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out)
        return {
            "source": str(tif),
            "output": str(out),
            "step_pixels": step,
            "vertices": int(len(mesh.vertices)),
            "triangles": int(len(mesh.faces)),
            "vertical_origin_m": z0,
            "bounds_local": mesh.bounds.tolist(),
        }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dgm_tif", type=Path)
    p.add_argument("--cell", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("data/derived/terrain.glb"))
    p.add_argument("--step", type=int, default=4)
    p.add_argument("--vertical-origin", type=float)
    a = p.parse_args()
    cell = json.loads(a.cell.read_text(encoding="utf-8"))
    minx, miny, _, _ = map(float, cell["bbox"])
    print(json.dumps(build_mesh(a.dgm_tif, a.out, a.step, minx, miny, a.vertical_origin), indent=2))


if __name__ == "__main__":
    main()
