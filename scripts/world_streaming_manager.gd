## WorldStreamingManager
##
## Reads assets/world_cells/index.json, streams world cells in/out as the
## player moves, and places every cell in a shared EPSG:25832-derived local
## world space using canonical UTM origins from the manifest — no hand-tuned
## offsets.
##
## Contract (index.json format_version = 1):
##   world_origin_utm  – UTM32N easting/northing/height that maps to Godot (0,0,0)
##   cells[]           – list of cell descriptors (see index.json)
##     .godot_origin   – pre-computed Godot offset = (bbox_min - world_origin_utm)
##                       in (x=Δeasting, y=0, z=-Δnorthing) convention
##     .asset_base     – res:// or user:// path prefix
##     .layers         – dict of layer_name -> filename relative to asset_base
##     .spawn_utm      – optional {easting, northing} for surface-aware spawn
##
## Memory budget: LOAD_RADIUS controls how many 256-m cells stay resident.
## On Android keep LOAD_RADIUS ≤ 2 (≤ 25 cells).

extends Node3D
class_name WorldStreamingManager

signal cell_loaded(cell_id: String)
signal cell_unloaded(cell_id: String)

const INDEX_PATH := "res://assets/world_cells/index.json"

## Cells whose Godot-origin is within this distance (metres) of the player stay loaded.
@export var load_radius_m: float = 640.0
## Cells outside this radius get freed (hysteresis avoids thrash at the boundary).
@export var unload_radius_m: float = 896.0

# Parsed manifest data
var _world_origin_utm := {"easting": 0.0, "northing": 0.0, "height_m": 0.0}
var _cells_meta: Array = []           # Array of Dicts, one per index.json entry
var _loaded_cells: Dictionary = {}    # cell_id -> Node3D

# Spawn info for the nearest anchor cell
var default_spawn_utm: Dictionary = {}  # {easting, northing} or empty

# Set by main.gd after player is added so we can query its position.
var player_ref: Node3D = null

# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

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
	if manifest.get("format_version", 0) != 1:
		push_error("WorldStreamingManager: unsupported index format_version")
		return false
	_world_origin_utm = manifest["world_origin_utm"]
	_cells_meta = manifest["cells"] as Array

	# Pick default spawn from the first anchor cell that has spawn_utm.
	for meta in _cells_meta:
		if meta.get("spawn_utm") != null:
			default_spawn_utm = meta["spawn_utm"] as Dictionary
			break

	print("WorldStreamingManager: loaded index with %d cells" % _cells_meta.size())
	return true


## Convert a UTM (easting, northing) pair to a Godot XZ position at y=0.
## Godot convention: x = Δeasting, z = -Δnorthing (right-hand, Y-up).
func utm_to_godot_xz(easting: float, northing: float) -> Vector2:
	return Vector2(
		easting  - _world_origin_utm["easting"],
		-(northing - _world_origin_utm["northing"])
	)


## Godot world position of a cell's south-west corner (bbox minimum).
func cell_godot_origin(meta: Dictionary) -> Vector3:
	var go: Dictionary = meta["godot_origin"] as Dictionary
	return Vector3(go["x"], go["y"], go["z"])


## Update streaming: call every second or from _process with throttle.
func update_streaming(player_position: Vector3) -> void:
	for meta in _cells_meta:
		var cid: String = meta["id"] as String
		var origin: Vector3 = cell_godot_origin(meta)
		var dist: float = Vector2(player_position.x - origin.x,
								  player_position.z - origin.z).length()

		if dist <= load_radius_m and not _loaded_cells.has(cid):
			_load_cell(meta)
		elif dist > unload_radius_m and _loaded_cells.has(cid):
			_unload_cell(cid)


## Returns a Godot XZ position (y=0) for the default spawn UTM.
func spawn_godot_xz() -> Vector2:
	if default_spawn_utm.is_empty():
		return Vector2.ZERO
	return utm_to_godot_xz(
		default_spawn_utm["easting"],
		default_spawn_utm["northing"]
	)

# -------------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------------

func _process(_delta: float) -> void:
	if player_ref == null:
		return
	update_streaming(player_ref.global_position)


func _load_cell(meta: Dictionary) -> void:
	var cid: String = meta["id"] as String
	var asset_base: String = meta["asset_base"] as String
	var layers: Dictionary = meta["layers"] as Dictionary
	var origin: Vector3 = cell_godot_origin(meta)

	var cell_root := Node3D.new()
	cell_root.name = "Cell_" + cid
	cell_root.position = origin
	add_child(cell_root)

	var any_loaded := false
	for layer_name in layers:
		var filename: String = layers[layer_name] as String
		var bundle_path: String = asset_base + "/" + filename
		var node: Node3D = _load_glb_bundle(bundle_path, cid + "_" + layer_name)
		if node == null:
			continue
		node.name = layer_name
		cell_root.add_child(node)
		_disable_shadows(node)
		if layer_name == "terrain_collision" or layer_name == "full_model":
			node.visible = false
			_attach_trimesh_collision(node)
		any_loaded = true

	if not any_loaded:
		cell_root.queue_free()
		return

	_loaded_cells[cid] = cell_root
	print("CELL_LOADED id=%s origin=%s" % [cid, origin])
	cell_loaded.emit(cid)


func _unload_cell(cid: String) -> void:
	if not _loaded_cells.has(cid):
		return
	var node: Node3D = _loaded_cells[cid] as Node3D
	node.queue_free()
	_loaded_cells.erase(cid)
	print("CELL_UNLOADED id=%s" % cid)
	cell_unloaded.emit(cid)


## Copy a .glbraw bundle to user:// as .glb, then load it.
func _load_glb_bundle(bundle_path: String, runtime_name: String) -> Node3D:
	if not FileAccess.file_exists(bundle_path):
		return null
	var runtime_path := _copy_to_runtime(bundle_path, runtime_name)
	if runtime_path.is_empty():
		return null
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var err := document.append_from_file(runtime_path, state)
	if err != OK:
		push_error("WorldStreamingManager: GLB load failed %s err=%s" % [runtime_name, err])
		return null
	var generated := document.generate_scene(state)
	if generated == null:
		push_error("WorldStreamingManager: GLB scene gen failed %s" % runtime_name)
	return generated


func _copy_to_runtime(bundle_path: String, runtime_name: String) -> String:
	var runtime_dir := "user://runtime_cells/_streaming"
	DirAccess.make_dir_recursive_absolute(
		ProjectSettings.globalize_path(runtime_dir))
	var runtime_path := runtime_dir + "/" + runtime_name.replace("/", "_") + ".glb"

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


func _attach_trimesh_collision(node: Node) -> void:
	if node is MeshInstance3D:
		var mi := node as MeshInstance3D
		if mi.mesh != null:
			var shape_data := mi.mesh.create_trimesh_shape()
			if shape_data != null:
				var body := StaticBody3D.new()
				body.name = "_TrimeshBody"
				var col := CollisionShape3D.new()
				col.shape = shape_data
				body.add_child(col)
				mi.add_child(body)
	for child in node.get_children():
		_attach_trimesh_collision(child)


func _disable_shadows(node: Node) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for child in node.get_children():
		_disable_shadows(child)
