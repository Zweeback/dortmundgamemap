# Architecture

## Coordinate model

Canonical source/world coordinates stay in `EPSG:25832` (ETRS89 / UTM zone 32N). Godot renders a local coordinate frame around a floating origin.

Suggested transform convention:

```text
Godot X = Easting - origin_easting
Godot Y = Height  - origin_height
Godot Z = -(Northing - origin_northing)
```

The exact sign convention must remain globally consistent once chunk streaming starts.

## World cells

Initial target: 256 × 256 m cells. Each cell should carry:
- global bounds in EPSG:25832
- source dataset IDs
- source timestamps
- licenses
- source/derived hashes
- render LOD assets
- separate collision asset
- optional road/nav graph
- optional semantic instances (trees, POIs, parking, construction)

## Runtime

The current monolithic full-geometry GLB is a reference/proof asset. The long-term runtime should stream nearby cells from a `world_manifest.json` instead of loading all Dortmund geometry at once.

## Mobile constraints

- no city-wide trimesh collision
- no monolithic 16K texture dependency
- prefer mobile texture compression + mipmaps
- instance repeated vegetation/props with MultiMesh
- use visibility range/HLOD/occlusion for distant city geometry
- preserve Android as a first-class target during every pipeline iteration
