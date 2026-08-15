# Data workspace

Raw and derived geodata are intentionally not committed to Git.

Expected local layout:

```text
data/
  raw/       # downloaded source datasets
  cache/     # temporary conversion/cache files
  derived/   # generated world cells, manifests, collision and textures
  source_registry.json
```

Every derived asset should retain source IDs, source timestamps, license metadata and hashes.
