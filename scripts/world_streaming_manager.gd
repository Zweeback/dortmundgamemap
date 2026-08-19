## WorldStreamingManager
##
## Reads assets/world_cells/index.json and streams 512 m world cells in/out
## as the player moves. Cells are placed in a shared Godot coordinate frame
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
## Android memory budget: keep load radius ≤ 1024 m.

extends Node3D
class_name WorldStreamingManager

signal cell_loaded(cell_id: String)
signal cell_unloaded(cell_id: String)
signal collision_ready

const INDEX_PATH := "res://assets/world_cells/index.json"
const INDEX_ASSET_BASE := "res://assets/world_cells"

@export var load_radius_m: float = 768.0
@export var unload_radius_m: float = 1152.0
@export var check_interval_s: float = 0.5

var _world_origin := Vector3.ZERO
var _cells_meta: Array = []
var _loaded_cells: Dictionary = {}
var _collision_cells_loading := 0
var _collision_ever_ready := false
var _check_timer := 0.0

var player_ref: Node3D = null
var spawn_godot_xz := Vector2.ZERO

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

	var wo: Array = manifest["world_origin"] as Array
	_world_origin = Vector3(float(wo[0]), float(wo[2]), float(wo[1]))
	_cells_meta = manifest["cells"] as Array

	# Verified against the published 48-cell artifact: the previous anchor
	# E394844/N5705080 sat inside a LoD2 building shell. This nearby point has
	# terrain support and a sampled building-free clearance envelope.
	var anchor_e := 394820.0
	var anchor_n := 5705088.0
	spawn_godot_xz = utm_to_godot_xz(anchor_e, anchor_n)
	print("SPAWN_ANCHOR_UTM e=%.1f n=%.1f godot=%s" % [anchor_e, anchor_n, spawn_godot_xz])

	print("WorldStreamingManager: loaded %d cells, world_origin=%s" % [
		_cells_meta.size(), wo])
	return true

func utm_to_godot_xz(easting: float, northing: float) -> Vector2:
	return Vector2(easting - _world_origin.x, -(northing - _world_origin.z))

func update_streaming(player_position: Vector3) -> void:
	for meta in _cells_meta:
		_evaluate_cell(meta, player_position)

func _process(delta: float) -> void:
	if player_ref == null:
		return
	_check_timer += delta
	if _check_timer < check_interval_s:
		return
	_check_timer = 0.0
	update_streaming(player_ref.global_position)

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

	var tr_path: String = INDEX_ASSET_BASE + "/" + (meta["terrain_render"] as String)
	var render_node: Node3D = _load_glb_bundle(tr_path, cid + "_tr")
	if render_node != null:
		render_node.name = "terrain_render"
		_disable_shadows(render_node)
		cell_root.add_child(render_node)
		any_loaded = true

	var tc_path: String = INDEX_ASSET_BASE + "/" + (meta["terrain_collision"] as String)
	var col_node: Node3D = _load_glb_bundle(tc_path, cid + "_tc")
	if col_node != null:
		col_node.name = "terrain_collision"
		col_node.visible = false
		_collision_cells_loading += 1
		_attach_trimesh_collision(col_node)
		cell_root.add_child(col_node)
		var ready_timer := get_tree().create_timer(0.0, true, true)
		ready_timer.timeout.connect(_notify_collision_loaded.bind(cid), CONNECT_ONE_SHOT)
		any_loaded = true

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

func _attach_trimesh_collision(node: Node) -> void:
	if node is MeshInstance3D:
		var mi := node as MeshInstance3D
		if mi.mesh != null:
			var body := StaticBody3D.new()
			body.name = "_TrimeshBody"
			var col := CollisionShape3D.new()
			var terrain_shape := mi.mesh.create_trimesh_shape()
			if terrain_shape is ConcavePolygonShape3D:
				(terrain_shape as ConcavePolygonShape3D).backface_collision = true
				print("COLLISION_BACKFACE_ENABLED mesh=%s" % mi.name)
			col.shape = terrain_shape
			body.add_child(col)
			mi.add_child(body)
	for child in node.get_children():
		_attach_trimesh_collision(child)

func _notify_collision_loaded(cell_id: String) -> void:
	_collision_cells_loading = maxi(_collision_cells_loading - 1, 0)
	print("COLLISION_PHYSICS_READY cell=%s remaining=%d" % [cell_id, _collision_cells_loading])
	if _collision_cells_loading == 0 and not _collision_ever_ready:
		_collision_ever_ready = true
		print("COLLISION_BATCH_READY")
		collision_ready.emit()

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
	return document.generate_scene(state)

func _copy_to_runtime(bundle_path: String, runtime_name: String) -> String:
	var runtime_dir := "user://runtime_cells/_streaming"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(runtime_dir))
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
