#!/usr/bin/env python3
"""Convert a clipped DGM1 GeoTIFF into Godot-oriented render/collision GLBs."""
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
        rows = np.arange(0, src.height, step, dtype=int)
        cols = np.arange(0, src.width, step, dtype=int)
        if rows[-1] != src.height - 1: rows = np.append(rows, src.height - 1)
        if cols[-1] != src.width - 1: cols = np.append(cols, src.width - 1)
        sampled = heights[np.ix_(rows, cols)]
        if not np.isfinite(sampled).all():
            sampled = np.nan_to_num(sampled, nan=float(np.nanmedian(sampled)))
        z0 = float(np.nanmin(sampled) if vertical_origin is None else vertical_origin)
        rr, cc = np.meshgrid(rows, cols, indexing="ij")
        xs, ys = rasterio.transform.xy(src.transform, rr, cc, offset="center")
        east, north = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
        vertices = np.column_stack([(east-origin_e).ravel(), (sampled-z0).ravel(), -(north-origin_n).ravel()])
        h, w = sampled.shape
        faces = []
        for r in range(h-1):
            base, nxt = r*w, (r+1)*w
            for c in range(w-1):
                a,b,c0,d = base+c,base+c+1,nxt+c,nxt+c+1
                faces.extend([(a,c0,b),(b,c0,d)])
        mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)
        mesh.remove_unreferenced_vertices()
        out.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out)
        return {"source":str(tif),"output":str(out),"step_pixels":step,"vertices":int(len(mesh.vertices)),"triangles":int(len(mesh.faces)),"vertical_origin_m":z0,"bounds_local":mesh.bounds.tolist()}


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("dgm_tif",type=Path); p.add_argument("--cell",type=Path,required=True); p.add_argument("--out",type=Path,default=Path("data/derived/terrain.glb")); p.add_argument("--step",type=int,default=2); p.add_argument("--vertical-origin",type=float); a=p.parse_args()
    cell=json.loads(a.cell.read_text(encoding="utf-8")); minx,miny,_,_=map(float,cell["bbox"])
    print(json.dumps(build_mesh(a.dgm_tif,a.out,a.step,minx,miny,a.vertical_origin),indent=2))

if __name__=="__main__": main()
