# Phoenix-West cell 001

First authoritative streaming cell for `DORTMUND WALKABLE v0.1`.

- CRS: EPSG:25832 (ETRS89 / UTM zone 32N)
- BBox: `394744,5705000,395000,5705256`
- Size: 256 x 256 m
- Reference: Hochofenwerk Phoenix-West at approx. `394845 / 5705080`
- Dortmund LoD2 source tile: `lod2_do_20251103_ul_394000_5705000.gml` (November 2025)

## Layers

1. `DGM1`: terrain height and dedicated terrain collision.
2. `DOP10 RGB`: optional terrain imagery; kept separate from geometry and downscaled per target device.
3. `Dortmund LoD2 CityGML`: render buildings, converted to cell-local GLB.
4. `Dortmund ALKIS Gebäude/Bauwerke`: authoritative footprints and QA/collision source.
5. `Dortmund Baumkataster`: vegetation instances with height/crown metadata.
6. `OpenStreetMap`: roads, paths, traffic semantics and POIs; ODbL provenance remains isolated.

## Reproduce

```bash
python -m pip install -r requirements-geodata.txt
python tools/fetch_cell.py cells/phoenix_west_001.json --include-dop --dop-scale 0.5 --include-osm
python tools/build_cell.py cells/phoenix_west_001.json
```

Raw and derived files are ignored by Git. Every fetch writes `manifest.json` with source URLs, timestamps, byte sizes and SHA-256 hashes.

## Godot axis convention

`x = E - cell_min_easting`, `z = -(N - cell_min_northing)`, `y = H - vertical_origin`.

The authoritative UTM coordinates are never discarded; local coordinates are only a runtime representation.
