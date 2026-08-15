# Dortmund full-geometry asset

`dortmund.glbraw` is a binary GLB stored under a non-imported extension so the Godot editor does not spend minutes reimporting it on every workspace start.

At runtime `scripts/main.gd` streams this file to `user://dortmund.glb` and loads it with `GLTFDocument` / `GLTFState`.

Geometry is unchanged from the canonical `dortmund.glb`:
- 704,915 triangles
- 2,114,612 vertices
- geometry binary prefix SHA-256: `a0075cd1ab85832d12b6b999de2811c311af372cc45491fc825492da8f8131d4`

Mobile texture variant:
- original embedded JPEG: 16,384 × 16,384
- bundled JPEG: 4,096 × 4,096
- no polygon/mesh decimation
