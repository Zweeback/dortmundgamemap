#!/usr/bin/env python3
"""Static registry validator. Network acquisition is intentionally separate."""
from __future__ import annotations
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
registry = json.loads((root / "data/source_registry.json").read_text(encoding="utf-8"))
assert registry["crs"] == "EPSG:25832"
ids = set()
for src in registry["sources"]:
    assert src["id"] not in ids, f"duplicate source id: {src['id']}"
    ids.add(src["id"])
    assert src.get("provider")
    assert src.get("type")
print(f"OK: {len(ids)} sources, CRS={registry['crs']}")
