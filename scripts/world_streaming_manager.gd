## WorldStreamingManager
##
## Reads assets/world_cells/index.json and streams 512 m world cells in/out
## as the player moves.  Cells are placed in a shared Godot coordinate frame
## derived directly from canonical EPSG:25832 (UTM32N) origins — no hand-
## tuned offsets.
##
## Index contract (build_connected_corridor.py output):
##   world_origin  [easting, northing, height_m]  canonical UTM origin → Godot (0,0,0)
##   cells[].id
##   cells[].bbox         [minE, minN, maxE, maxN]
##   cells[].offset       [Δeasting, 0, -Δnorthing]  pre-computed Godot offset
##   cells[].terrain_render     path relative to INDEX_ASSET_BASE
##   cells[].terrain_collision  path relative to INDEX_ASSET_BASE
##   cells[].buildings          array of paths relative to INDEX_ASSET_BASE
##
## Godot convention: x = Δeasting, y = altitude − vertical_origin, z = −Δnorthing
##
## Android memory budget: keep LOAD_RADIUS_M ≤ 1024 m (≤ ~9 cells at 512 m).

extends Node3D
class_name WorldStreamingManager

signal cell_loaded(cell_id: String)
signal cell_unloaded(cell_id: String)
## Emitted when the first batch of terrain collision bodies has entered the
## physics world — main.gd uses this to trigger deferred spawn resolution.
signal collision_ready

## Path that indexes cells; this matches the pipeline output location.
const INDEX_PATH       := "res://assets/world_cells/index.json"
## All relative cell asset paths in the index are resolved under this prefix.
const INDEX_ASSET_BASE := "res://assets/world_cells"

## Player must be within this radius for a cell to load.
@export var load_radius_m:   float = 768.0
## Cell is freed when player exceeds this radius (hysteresis).
@export var unload_radius_m: float = 1152.0
## How often (seconds) streaming state is re-evaluated from _process.
@export var check_interval_s: float = 0.5

# ── parsed manifest ───────────────────────────────────────────────────────────
var _world_origin := Vector3.ZERO   # canonical UTM origin as Godot (0,0,0)
var _cells_meta: Array = []

# ── runtime state ─────────────────────────────────────────────────────────────
var _loaded_cells: Dictionary = {}  # cell_id → Node3D
var _collision_cells_loading := 0   # count of cells that still owe a physics frame
var _collision_ever_ready := false
var _check_timer := 0.0

## Assigned by main.gd after the player node is added to the scene.
var player_ref: Node3D = null

# ── spawn info ────────────────────────────────────────────────────────────────
## Godot XZ for the default player spawn (derived from Phoenix-West anchor).
## Falls back to (0,0) when the anchor cell is absent from the index.
var spawn_godot_xz := Vector2.ZERO

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

func load_index() -> bool:
	if not FileAccess.file_exists(INDEX_PATH):
		push_warning("WorldStreamingManager: index not found at %s" % INDEX_PATH)
		return false
	var file := FileAccess.open(INDEX_PATH, FileAccess.READ)
	if file == null:
		push_error("WorldStreamingManager: cannot open %s" % INDEX_PATH)
		return false
	var text := file.get_as_text()
	file.close()
	var parsed = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("WorldStreamingManager: index.json is malformed")
		return false
	var manifest: Dictionary = parsed as Dictionary

	# world_origin: [easting, northing, height_m]
	var wo: Array = manifest["world_origin"] as Array
	_world_origin = Vector3(float(wo[0]), float(wo[2]), float(wo[1]))

	_cells_meta = manifest["cells"] as Array

	# Derive default spawn from Phoenix-West anchor: UTM bbox [394744, 5705000, …]
	# Spawn point = centre of that cell, lifted 1.25 m above terrain (resolved later).
	var anchor_e := 394844.0   # bbox_min_e + 100 m  (interior reference point)
	var anchor_n := 5705080.0
	spawn_godot_xz = utm_to_godot_xz(anchor_e, anchor_n)

	print("WorldStreamingManager: loaded %d cells, world_origin=%s" % [
		_cells_meta.size(), wo])
	return true


## Convert UTM easting/northing to Godot XZ (y=0 plane).
func utm_to_godot_xz(easting: float, northing: float) -> Vector2:
	return Vector2(easting - _world_origin.x, -(northing - _world_origin.z))


## Trigger a streaming update immediately (e.g. on first frame).
func update_streaming(player_position: Vector3) -> void:
	for meta in _cells_meta:
		_evaluate_cell(meta, player_position)


# ─────────────────────────────────────────────────────────────────────────────
# Godot callbacks
# ─────────────────────────────────────────────────────────────────────────────

func _process(delta: float) -> void:
	if player_ref == null:
		return
	_check_timer += delta
	if _check_timer < check_interval_s:
		return
	_check_timer = 0.0
	update_streaming(player_ref.global_position)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

func _evaluate_cell(meta: Dictionary, player_pos: Vector3) -> void:
	var cid: String = meta["id"] as String
	var offset: Array = meta["offset"] as Array
	var ox := float(offset[0])
	var oz := float(offset[2])
	var dist := Vector2(player_pos.x - ox, player_pos.z - oz).length()

	if dist <= load_radius_m and not _loaded_cells.has(cid):
		_load_cell(meta)
	elif dist > unload_radius_m and _loaded_cells.has(cid):
		_unload_cell(cid)


func _load_cell(meta: Dictionary) -> void:
	var cid: String = meta["id"] as String
	var offset: Array = meta["offset"] as Array
	var cell_pos := Vector3(float(offset[0]), float(offset[1]), float(offset[2]))

	var cell_root := Node3D.new()
	cell_root.name = "Cell_" + cid
	cell_root.position = cell_pos
	add_child(cell_root)

	var any_loaded := false

	# ── terrain render ────────────────────────────────────────────────────────
	var tr_path: String = INDEX_ASSET_BASE + "/" + (meta["terrain_render"] as String)
	var render_node: Node3D = _load_glb_bundle(tr_path, cid + "_tr")
	if render_node != null:
		render_node.name = "terrain_render"
		_disable_shadows(render_node)
		cell_root.add_child(render_node)
		any_loaded = true

	# ── terrain collision (simplified mesh, NOT the full render mesh) ─────────
	var tc_path: String = INDEX_ASSET_BASE + "/" + (meta["terrain_collision"] as String)
	var col_node: Node3D = _load_glb_bundle(tc_path, cid + "_tc")
	if col_node != null:
		col_node.name = "terrain_collision"
		col_node.visible = false
		_collision_cells_loading += 1
		_attach_trimesh_collision(col_node, cid)
		cell_root.add_child(col_node)
		any_loaded = true

	# ── buildings (array of paths) ────────────────────────────────────────────
	var buildings: Array = meta.get("buildings", []) as Array
	for i in range(buildings.size()):
		var b_path: String = INDEX_ASSET_BASE + "/" + (buildings[i] as String)
		var b_node: Node3D = _load_glb_bundle(b_path, cid + "_b" + str(i))
		if b_node != null:
			b_node.name = "buildings_%d" % i
			_disable_shadows(b_node)
			cell_root.add_child(b_node)
			any_loaded = true

	if not any_loaded:
		cell_root.queue_free()
		return

	_loaded_cells[cid] = cell_root
	print("CELL_LOADED id=%s pos=%s" % [cid, cell_pos])
	cell_loaded.emit(cid)


func _unload_cell(cid: String) -> void:
	if not _loaded_cells.has(cid):
		return
	(_loaded_cells[cid] as Node3D).queue_free()
	_loaded_cells.erase(cid)
	print("CELL_UNLOADED id=%s" % cid)
	cell_unloaded.emit(cid)


## Attach StaticBody3D + trimesh CollisionShape3D to every MeshInstance3D
## in the subtree, then defer a check for collision_ready.
func _attach_trimesh_collision(node: Node, cell_id: String) -> void:
	if node is MeshInstance3D:
		var mi := node as MeshInstance3D
		if mi.mesh != null:
			var body := StaticBody3D.new()
			body.name = "_TrimeshBody"
			var col := CollisionShape3D.new()
			col.shape = mi.mesh.create_trimesh_shape()
			body.add_child(col)
			mi.add_child(body)
	for child in node.get_children():
		_attach_trimesh_collision(child, cell_id)
	# Deferred so the StaticBody3D enters the physics world before we signal.
	_notify_collision_loaded.call_deferred(cell_id)


func _notify_collision_loaded(_cell_id: String) -> void:
	_collision_cells_loading = maxi(_collision_cells_loading - 1, 0)
	if _collision_cells_loading == 0 and not _collision_ever_ready:
		_collision_ever_ready = true
		collision_ready.emit()


## Copy a .glbraw bundle to user:// as .glb and parse it.
func _load_glb_bundle(bundle_path: String, runtime_name: String) -> Node3D:
	if not FileAccess.file_exists(bundle_path):
		return null
	var runtime_path := _copy_to_runtime(bundle_path, runtime_name)
	if runtime_path.is_empty():
		return null
	var document := GLTFDocument.new()
	var state    := GLTFState.new()
	var err := document.append_from_file(runtime_path, state)
	if err != OK:
		push_error("WorldStreamingManager: GLB load failed %s err=%s" % [runtime_name, err])
		return null
	return document.generate_scene(state)


func _copy_to_runtime(bundle_path: String, runtime_name: String) -> String:
	var runtime_dir := "user://runtime_cells/_streaming"
	DirAccess.make_dir_recursive_absolute(
		ProjectSettings.globalize_path(runtime_dir))
	var safe_name := runtime_name.replace("/", "_")
	var runtime_path := runtime_dir + "/" + safe_name + ".glb"

	var src := FileAccess.open(bundle_path, FileAccess.READ)
	if src == null:
		return ""
	var source_size := src.get_length()

	if FileAccess.file_exists(runtime_path):
		var existing := FileAccess.open(runtime_path, FileAccess.READ)
		if existing != null and existing.get_length() == source_size:
			existing.close()
			src.close()
			return ProjectSettings.globalize_path(runtime_path)
		if existing != null:
			existing.close()

	var dst := FileAccess.open(runtime_path, FileAccess.WRITE)
	if dst == null:
		src.close()
		return ""
	const CHUNK := 4 * 1024 * 1024
	while src.get_position() < source_size:
		var remaining := source_size - src.get_position()
		dst.store_buffer(src.get_buffer(min(CHUNK, remaining)))
	src.close()
	dst.close()
	return ProjectSettings.globalize_path(runtime_path)


func _disable_shadows(node: Node) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for child in node.get_children():
		_disable_shadows(child)
