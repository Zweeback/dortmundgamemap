#!/usr/bin/env python3
"""Fetch authoritative source data for one DortmundGameMap cell.

Raw downloads are intentionally written below data/raw/ and are not committed.
The cell config is EPSG:25832; all requests preserve that CRS where supported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

UA = "DortmundGameMap/0.1 (+https://github.com/Zweeback/dortmundgamemap)"
ODS = "https://open-data.dortmund.de/api/explore/v2.1/catalog/datasets"
ALKIS_WFS = "https://geoweb1.digistadtdo.de/doris_gdi/geoserver/ALKIS_ADV/ows"
DGM_WCS = "https://www.wcs.nrw.de/geobasis/wcs_nw_dgm"
DOP_WCS = "https://www.wcs.nrw.de/geobasis/wcs_nw_dop"
OVERPASS = "https://overpass-api.de/api/interpreter"


def load_cell(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("crs") != "EPSG:25832":
        raise ValueError("Cell CRS must be EPSG:25832")
    minx, miny, maxx, maxy = map(float, data["bbox"])
    if maxx <= minx or maxy <= miny:
        raise ValueError("Invalid bbox")
    if abs((maxx - minx) - float(data["size_m"])) > 1e-6:
        raise ValueError("bbox width does not match size_m")
    if abs((maxy - miny) - float(data["size_m"])) > 1e-6:
        raise ValueError("bbox height does not match size_m")
    return data


def url(base: str, params: dict[str, object]) -> str:
    return base + "?" + urllib.parse.urlencode(params, doseq=True, safe=",():")


def request_bytes(target: str, *, data: bytes | None = None, timeout: int = 120) -> bytes:
    req = urllib.request.Request(target, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def request_json(target: str, *, timeout: int = 120) -> dict:
    return json.loads(request_bytes(target, timeout=timeout).decode("utf-8"))


def write_bytes(path: Path, payload: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def write_json(path: Path, payload: object) -> dict:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return write_bytes(path, raw)


def lod2_catalog_url(offset: int = 0, limit: int = 100) -> str:
    return url(f"{ODS}/3d-stadtmodell-gml-format/records", {"limit": limit, "offset": offset})


def find_lod2_files(expected: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    offset = 0
    while True:
        payload = request_json(lod2_catalog_url(offset=offset))
        for record in payload.get("results", []):
            info = record.get("file") or {}
            filename = info.get("filename")
            if filename in expected and info.get("url"):
                found[filename] = info["url"]
        total = int(payload.get("total_count", 0))
        offset += len(payload.get("results", []))
        if expected.issubset(found) or offset >= total or not payload.get("results"):
            break
    missing = expected - set(found)
    if missing:
        raise RuntimeError(f"LoD2 tile(s) not found in Dortmund catalog: {sorted(missing)}")
    return found


def alkis_url(cell: dict) -> str:
    minx, miny, maxx, maxy = cell["bbox"]
    return url(ALKIS_WFS, {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": cell["sources"]["alkis_type_name"], "outputFormat": "application/json", "srsName": "EPSG:25832", "bbox": f"{minx},{miny},{maxx},{maxy},EPSG:25832"})


def tree_url(cell: dict, *, offset: int = 0, limit: int = 100) -> str:
    minx, miny, maxx, maxy = cell["bbox"]
    where = f"ostwert >= {minx} and ostwert < {maxx} and hochwert >= {miny} and hochwert < {maxy}"
    return url(f"{ODS}/baumkataster/records", {"limit": limit, "offset": offset, "where": where})


def dgm_url(cell: dict) -> str:
    minx, miny, maxx, maxy = cell["bbox"]
    return url(DGM_WCS, {"SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "GetCoverage", "COVERAGEID": cell["sources"]["dgm_coverage_id"], "FORMAT": "image/tiff", "SUBSET": [f"x({minx},{maxx})", f"y({miny},{maxy})"]})


def dop_url(cell: dict, scale_factor: float = 1.0) -> str:
    minx, miny, maxx, maxy = cell["bbox"]
    params: dict[str, object] = {"SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "GetCoverage", "COVERAGEID": cell["sources"]["dop_coverage_id"], "FORMAT": "image/tiff", "SUBSET": [f"x({minx},{maxx})", f"y({miny},{maxy})"], "RANGESUBSET": "1,2,3"}
    if scale_factor != 1.0:
        params["SCALEFACTOR"] = scale_factor
    return url(DOP_WCS, params)


def overpass_query_wgs84(cell: dict) -> str:
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError("pyproj is required for OSM fetches") from exc
    minx, miny, maxx, maxy = cell["bbox"]
    t = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    west, south = t.transform(minx, miny)
    east, north = t.transform(maxx, maxy)
    return f"""[out:json][timeout:60];
(
  way[highway]({south},{west},{north},{east});
  node[highway]({south},{west},{north},{east});
  node[amenity]({south},{west},{north},{east});
  node[public_transport]({south},{west},{north},{east});
);
out body geom;"""


def fetch_trees(cell: dict) -> dict:
    all_rows: list[dict] = []
    offset = 0
    while True:
        payload = request_json(tree_url(cell, offset=offset))
        rows = payload.get("results", [])
        all_rows.extend(rows)
        offset += len(rows)
        if offset >= int(payload.get("total_count", 0)) or not rows:
            break
    return {"total_count": len(all_rows), "results": all_rows}


def dry_run(cell: dict, include_dop: bool, dop_scale: float, include_osm: bool) -> dict:
    result = {"lod2_catalog": lod2_catalog_url(), "alkis": alkis_url(cell), "trees": tree_url(cell), "dgm": dgm_url(cell)}
    if include_dop:
        result["dop"] = dop_url(cell, dop_scale)
    if include_osm:
        result["overpass_endpoint"] = OVERPASS
        result["overpass_query"] = overpass_query_wgs84(cell)
    return result


def run(cell_path: Path, out_root: Path, include_dop: bool, dop_scale: float, include_osm: bool) -> None:
    cell = load_cell(cell_path)
    out = out_root / cell["id"]
    out.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict] = []
    source_urls: dict[str, object] = {}

    expected = set(cell["sources"].get("lod2_tiles", []))
    lod2 = find_lod2_files(expected)
    source_urls["lod2"] = lod2
    for filename, target in lod2.items():
        artifacts.append(write_bytes(out / "lod2" / filename, request_bytes(target)))

    aurl = alkis_url(cell)
    source_urls["alkis"] = aurl
    artifacts.append(write_bytes(out / "alkis_buildings.geojson", request_bytes(aurl)))

    source_urls["trees"] = tree_url(cell)
    artifacts.append(write_json(out / "trees.json", fetch_trees(cell)))

    dgurl = dgm_url(cell)
    source_urls["dgm"] = dgurl
    artifacts.append(write_bytes(out / "dgm1.tif", request_bytes(dgurl)))

    if include_dop:
        dourl = dop_url(cell, dop_scale)
        source_urls["dop"] = dourl
        artifacts.append(write_bytes(out / "dop_rgb.tif", request_bytes(dourl, timeout=300)))

    if include_osm:
        query = overpass_query_wgs84(cell)
        source_urls["osm"] = OVERPASS
        body = urllib.parse.urlencode({"data": query}).encode("utf-8")
        artifacts.append(write_bytes(out / "osm.json", request_bytes(OVERPASS, data=body)))

    manifest = {"cell": cell, "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "sources": source_urls, "artifacts": artifacts}
    write_json(out / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cell", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    parser.add_argument("--include-dop", action="store_true")
    parser.add_argument("--dop-scale", type=float, default=1.0)
    parser.add_argument("--include-osm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cell = load_cell(args.cell)
    if args.dry_run:
        print(json.dumps(dry_run(cell, args.include_dop, args.dop_scale, args.include_osm), indent=2))
        return
    run(args.cell, args.out, args.include_dop, args.dop_scale, args.include_osm)


if __name__ == "__main__":
    main()
