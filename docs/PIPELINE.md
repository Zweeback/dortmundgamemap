# Geodaten → Godot Pipeline

## Ziel

`DORTMUND WALKABLE v0.1`

Amtliche georeferenzierte Daten werden in kleine, streamingfähige Zellen überführt. Der bestehende 1.3 × 1.1 km Full-Geometry-Build bleibt Referenz, wird aber nicht die endgültige Weltstruktur.

## Pipeline

1. **Source inventory**
   - Datensatz-ID, Lizenz, Stand, CRS und Hash erfassen.
2. **Acquire**
   - Dortmund OpenData API / WFS / Download, Geobasis NRW, OSM-Extract.
3. **Normalize CRS**
   - intern EPSG:25832.
4. **Tile**
   - Zielraster zunächst 256 × 256 m.
5. **Terrain**
   - DGM1 → Heightfield / vereinfachtes Collision Mesh.
6. **Buildings**
   - CityGML LoD2 → GLB pro Zelle.
   - ALKIS-Footprints als Collision-/QA-Ebene.
7. **Road graph**
   - OSM + optional ATKIS → Fahr-/Fuß-/Radgraph.
8. **Textures**
   - Orthophoto → Kacheln → Mipmaps → KTX2/BasisU für Mobile.
9. **Vegetation**
   - Baumkataster → MultiMesh-Instanzen mit species/height/crown Parametern.
10. **Runtime manifest**
   - `world_manifest.json` mit Bounds, Source-Provenienz, LODs und Hashes.
11. **Godot streaming**
   - Radius-basierter ChunkLoader, Visibility ranges, HLOD/Occlusion.
12. **Collision/Nav**
   - Terrain und Straßen separat; niemals 700k+ Render-Triangles als eine Trimesh-Collision.

## Erstes Gebiet

Empfohlene Reihenfolge:
1. Hörde / Phoenix West
2. Phoenixsee
3. Innenstadt
4. Aplerbeck

## Qualitäts-Gates

- Geokoordinatenverlust: 0
- sichtbare Spalten zwischen Chunks: 0
- Player fällt nicht durch Terrain
- 30 s Walk-Test stabil
- Android: Ziel zunächst 30 FPS, danach Optimierung Richtung 60 FPS
- jede generierte Zelle hat Source-/License-Metadaten
