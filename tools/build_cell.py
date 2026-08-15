#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import rasterio


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def dgm_vertical_origin(path: Path) -> float:
    with rasterio.open(path) as src:
        band = src.read(1, masked=True)
        if band.count() == 0:
            raise RuntimeError(f"DGM contains no valid height samples: {path}")
        return float(band.min())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cell", type=Path)
    p.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    p.add_argument("--derived-root", type=Path, default=Path("data/derived"))
    args = p.parse_args()

    cell = json.loads(args.cell.read_text(encoding="utf-8"))
    raw = args.raw_root / cell["id"]
    derived = args.derived_root / cell["id"]
    derived.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    dgm = raw / "dgm1.tif"
    vertical_origin = dgm_vertical_origin(dgm)
    vertical = f"{vertical_origin:.6f}"

    run([py, "tools/build_terrain.py", str(dgm), "--cell", str(args.cell), "--out", str(derived / "terrain_render.glb"), "--step", "2", "--vertical-origin", vertical])
    run([py, "tools/build_terrain.py", str(dgm), "--cell", str(args.cell), "--out", str(derived / "terrain_collision.glb"), "--step", "4", "--vertical-origin", vertical])

    for tile in cell["sources"]["lod2_tiles"]:
        run([
            py,
            "tools/citygml_to_glb.py",
            str(raw / "lod2" / tile),
            "--cell",
            str(args.cell),
            "--out",
            str(derived / (Path(tile).stem + ".glb")),
            "--vertical-origin",
            vertical,
        ])

    meta = {
        "cell_id": cell["id"],
        "crs": cell["crs"],
        "bbox": cell["bbox"],
        "vertical_origin_m": vertical_origin,
    }
    (derived / "cell_build_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
