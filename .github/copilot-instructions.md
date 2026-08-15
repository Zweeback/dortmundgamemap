# Copilot instructions — DortmundGameMap

This repository is a Godot 4.7.1 geospatial game/simulation project.

## Non-negotiable rules
- Preserve canonical world coordinates in ETRS89 / UTM32N (`EPSG:25832`).
- Do not replace the canonical Dortmund model with LoD2 placeholders while presenting it as the same asset.
- Do not commit large raw geodata, generated GLB/GLBRAW assets, `.godot/`, APKs or build caches.
- Render around a local/floating origin; keep source easting/northing/height in metadata.
- Visual meshes and collision meshes are separate products.
- Never create full-resolution trimesh collision from an entire city render mesh.
- Prefer 256 m world cells initially; make the size configurable.
- Every generated chunk must retain source IDs, license, source timestamp and hashes.
- Keep OSM-derived data provenance separate because OSM is ODbL 1.0.
- Dortmund/Geobasis NRW DL-DE-Zero sources may be freely transformed and combined, but still retain provenance for reproducibility.

## Current milestone
`DORTMUND WALKABLE v0.1`

Definition of done:
1. Accurate terrain in EPSG:25832.
2. Player spawns at known real-world coordinates.
3. Ground collision works for a 30-second walk without falling through.
4. Current Dortmund visual reference asset loads at runtime.
5. Streaming manifest supports chunked expansion.
6. Android build remains viable.

## Preferred architecture
- `data/source_registry.json`: source catalog.
- `data/raw/`: downloaded source files (ignored by Git).
- `data/derived/`: generated chunk assets (ignored by Git).
- `tools/`: offline conversion pipeline.
- `scripts/`: Godot/runtime scripts and lightweight validators.
- `docs/SOURCES.md`: human-readable source and licensing notes.
- `docs/PIPELINE.md`: source-to-runtime pipeline.

When proposing a geodata import, always state CRS, units, source license, expected output, and whether geometry, collision, textures or semantics are affected.
