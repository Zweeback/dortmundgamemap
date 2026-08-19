#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from pyproj import Transformer

CRS = "EPSG:25832"
CELL_SIZE = 512
MIN_E, MIN_N = 392192, 5704704
MAX_E, MAX_N = 395264, 5708800
VERTICAL_ORIGIN = 100.0
CANONICAL_WORLD_ORIGIN = [MIN_E, MIN_N, VERTICAL_ORIGIN]
LOD2_CATALOG = "https://open-data.dortmund.de/api/explore/v2.1/catalog/datasets/3d-stadtmodell-gml-format/records?limit=100"
DGM_WCS = "https://www.wcs.nrw.de/geobasis/wcs_nw_dgm"
UA = "DortmundGameMap/connected-world"
NO_LOD2_SURFACES = "No LoD2 surfaces intersect the cell bbox"


def req(url: str, timeout: int = 180) -> bytes:
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.read()


def catalog() -> dict[tuple[int, int], str]:
    out: dict[tuple[int, int], str] = {}
    offset = 0
    total = 1
    rx = re.compile(r"lod2_do_\d+_ul_(\d+)_(\d+)\.gml$")
    while offset < total:
        data = json.loads(req(LOD2_CATALOG + f"&offset={offset}").decode("utf-8"))
        rows = data.get("results", [])
        total = int(data.get("total_count", 0))
        for row in rows:
            f = row.get("file") or {}
            m = rx.match(f.get("filename", ""))
            if m and f.get("url"):
                out[(int(m.group(1)), int(m.group(2)))] = f["url"]
        if not rows:
            break
        offset += len(rows)
    return out


def tiles_for_bbox(bbox: list[float]) -> list[tuple[int, int]]:
    minx, miny, maxx, maxy = bbox
    xs = range(int(math.floor(minx / 1000) * 1000), int(math.floor((maxx - 1e-6) / 1000) * 1000) + 1, 1000)
    ys = range(int(math.floor(miny / 1000) * 1000), int(math.floor((maxy - 1e-6) / 1000) * 1000) + 1, 1000)
    return [(x, y) for x in xs for y in ys]


def dgm_url(bbox: list[float]) -> str:
    import urllib.parse
    minx, miny, maxx, maxy = bbox
    params = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"), ("COVERAGEID", "nw_dgm"), ("FORMAT", "image/tiff"), ("SUBSET", f"x({minx},{maxx})"), ("SUBSET", f"y({miny},{maxy})")]
    return DGM_WCS + "?" + urllib.parse.urlencode(params, safe=",()")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def is_empty_lod2_result(output: str) -> bool:
    """Return True for the known, valid case where a source tile has no surfaces in this cell."""
    return NO_LOD2_SURFACES in output


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("connected_world"))
    args = ap.parse_args()
    out = args.out
    raw = out / "raw"
    derived = out / "assets" / "world_cells"
    specs = out / "cells"
    raw.mkdir(parents=True, exist_ok=True)
    derived.mkdir(parents=True, exist_ok=True)
    specs.mkdir(parents=True, exist_ok=True)
    cat = catalog()
    transformer = Transformer.from_crs(25832, 4326, always_xy=True)
    cells = []
    required_tiles: set[tuple[int, int]] = set()
    for n in range(MIN_N, MAX_N, CELL_SIZE):
        for e in range(MIN_E, MAX_E, CELL_SIZE):
            bbox = [float(e), float(n), float(e + CELL_SIZE), float(n + CELL_SIZE)]
            west, south = transformer.transform(e, n)
            east, north = transformer.transform(e + CELL_SIZE, n + CELL_SIZE)
            cid = f"e{e}_n{n}"
            ts = tiles_for_bbox(bbox)
            required_tiles.update(ts)
            spec = {"id": cid, "crs": CRS, "size_m": CELL_SIZE, "bbox": bbox, "bbox_wgs84": [west, south, east, north], "sources": {"lod2_tiles": [], "dgm_coverage_id": "nw_dgm", "dop_coverage_id": "nw_dop", "alkis_type_name": "ALKIS_ADV:ALKIS_ADV_GebaeudeBauwerk"}}
            sp = specs / f"{cid}.json"
            sp.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
            cells.append((cid, bbox, sp, ts))
    lod_dir = raw / "lod2"
    lod_dir.mkdir(exist_ok=True)
    tile_paths = {}
    for key in sorted(required_tiles):
        if key not in cat:
            print(f"WARN no Dortmund LoD2 tile for {key}")
            continue
        target = lod_dir / f"lod2_{key[0]}_{key[1]}.gml"
        if not target.exists() or target.stat().st_size == 0:
            target.write_bytes(req(cat[key]))
        tile_paths[key] = target
    index = {
        "crs": CRS,
        "cell_size_m": CELL_SIZE,
        "world_bbox": [MIN_E, MIN_N, MAX_E, MAX_N],
        "world_origin": CANONICAL_WORLD_ORIGIN,
        "provenance": {
            "lod2": "Stadt Dortmund 3D-Stadtmodell (DL-DE-Zero-2.0)",
            "dgm": "Geobasis NRW DGM1 (DL-DE-Zero-2.0)",
            "crs": "EPSG:25832 (ETRS89 / UTM zone 32N)"
        },
        "cells": []
    }
    py = sys.executable
    for i, (cid, bbox, spec_path, ts) in enumerate(cells, 1):
        print(f"CELL {i}/{len(cells)} {cid}", flush=True)
        c_raw = raw / cid
        c_out = derived / cid
        c_raw.mkdir(exist_ok=True)
        c_out.mkdir(exist_ok=True)
        dgm = c_raw / "dgm1.tif"
        if not dgm.exists() or dgm.stat().st_size == 0:
            dgm.write_bytes(req(dgm_url(bbox)))

        tr_raw = c_out / "terrain_render.glbraw"
        tc_raw = c_out / "terrain_collision.glbraw"

        if not tr_raw.exists():
            tr_glb = c_out / "terrain_render.glb"
            if not tr_glb.exists():
                run([py, "tools/build_terrain.py", str(dgm), "--cell", str(spec_path), "--out", str(tr_glb), "--step", "4", "--vertical-origin", str(VERTICAL_ORIGIN)])
            tr_glb.rename(tr_raw)

        if not tc_raw.exists():
            tc_glb = c_out / "terrain_collision.glb"
            if not tc_glb.exists():
                run([py, "tools/build_terrain.py", str(dgm), "--cell", str(spec_path), "--out", str(tc_glb), "--step", "8", "--vertical-origin", str(VERTICAL_ORIGIN)])
            tc_glb.rename(tc_raw)

        building_files = []
        for ti, key in enumerate(ts):
            src = tile_paths.get(key)
            if not src:
                continue
            dst_raw = c_out / f"buildings_{ti}.glbraw"
            dst_glb = c_out / f"buildings_{ti}.glb"
            if dst_raw.exists():
                building_files.append(dst_raw.name)
            else:
                proc = subprocess.run([py, "tools/citygml_to_glb.py", str(src), "--cell", str(spec_path), "--out", str(dst_glb), "--vertical-origin", str(VERTICAL_ORIGIN)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                print(proc.stdout)
                if proc.returncode != 0:
                    if is_empty_lod2_result(proc.stdout):
                        print(f"INFO no LoD2 surfaces for tile {key} in cell {cid}; continuing with no building mesh", flush=True)
                        if dst_glb.exists():
                            dst_glb.unlink()
                        continue
                    raise RuntimeError(f"citygml_to_glb failed for tile {key} in cell {cid}:\n{proc.stdout}")
                if dst_glb.exists():
                    dst_glb.rename(dst_raw)
                    building_files.append(dst_raw.name)

        index["cells"].append({
            "id": cid,
            "bbox": bbox,
            "offset": [bbox[0] - CANONICAL_WORLD_ORIGIN[0], 0.0, -(bbox[1] - CANONICAL_WORLD_ORIGIN[1])],
            "terrain_render": f"{cid}/terrain_render.glbraw",
            "terrain_collision": f"{cid}/terrain_collision.glbraw",
            "buildings": [f"{cid}/{x}" for x in building_files]
        })
    for p in derived.rglob("*.glb"):
        p.rename(p.with_suffix(".glbraw"))
    (derived / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"BUILT {len(index['cells'])} connected cells")


if __name__ == "__main__":
    main()
