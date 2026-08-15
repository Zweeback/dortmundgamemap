# DortmundGameMap Roadmap

## DORTMUND WALKABLE v0.1

Goal: turn the current full-model Android proof into the first georeferenced, collision-safe, streamable Dortmund gameplay cell.

### Phase 1 — Hörde / Phoenix West pilot
- preserve canonical EPSG:25832 coordinates
- acquire DGM1 terrain
- acquire Dortmund LoD2 buildings
- acquire ALKIS building footprints
- acquire OSM road/footway graph
- acquire orthophoto tiles
- generate one 256 × 256 m world cell
- generate simplified terrain/road collision separately from render geometry
- spawn player at a known real-world coordinate
- run 30-second walk test
- export Android build and measure FPS/RAM/load time

### Phase 2 — streaming
- world_manifest.json
- chunk loader
- neighboring-cell prefetch
- visibility ranges / HLOD
- mobile texture pipeline (KTX2/BasisU or equivalent)

### Phase 3 — living Dortmund
- Baumkataster MultiMesh vegetation
- parking occupancy
- construction sites / road closures
- transit stops and mission anchors

## Quality gates
- no loss of canonical geocoordinates
- no full-city trimesh collision
- no invisible placeholder presented as the real city
- every derived asset keeps source/license/hash metadata
- Android remains a first-class target
