extends Node3D
class_name DortmundWorldCell

const CELL_ID := "phoenix_west_001"
const BUNDLE_BASE := "res://assets/cells/phoenix_west_001"
const TERRAIN_RENDER_BUNDLE := BUNDLE_BASE + "/terrain_render.glbraw"
const TERRAIN_COLLISION_BUNDLE := BUNDLE_BASE + "/terrain_collision.glbraw"
const BUILDINGS_BUNDLE := BUNDLE_BASE + "/buildings_lod2.glbraw"

var cell_size_xz := Vector2(256.0, 256.0)
var player_spawn := Vector3(101.0, 9.0, -80.0)
var collision_mesh_count := 0
var loaded := false

func has_packaged_cell() -> bool:
	return (
		FileAccess.file_exists(TERRAIN_RENDER_BUNDLE)
		and FileAccess.file_exists(TERRAIN_COLLISION_BUNDLE)
		and FileAccess.file_exists(BUILDINGS_BUNDLE)
	)

func load_packaged_cell() -> bool:
	if not has_packaged_cell():
		return false

	var terrain := _load_glb(TERRAIN_RENDER_BUNDLE, "terrain_render")
	var buildings := _load_glb(BUILDINGS_BUNDLE, "buildings_lod2")
	var collision_source := _load_glb(TERRAIN_COLLISION_BUNDLE, "terrain_collision")
	if terrain == null or buildings == null or collision_source == null:
		if terrain != null:
			terrain.queue_free()
		if buildings != null:
			buildings.queue_free()
		if collision_source != null:
			collision_source.queue_free()
		return false

	terrain.name = "TerrainRender"
	buildings.name = "BuildingsLoD2"
	collision_source.name = "TerrainCollisionSource"
	add_child(terrain)
	add_child(buildings)
	add_child(collision_source)

	_disable_shadows(terrain)
	_disable_shadows(buildings)
	collision_source.visible = false
	collision_mesh_count = _attach_trimesh_collision(collision_source)
	if collision_mesh_count <= 0:
		push_error("Phoenix-West terrain collision contains no mesh")
		return false

	loaded = true
	print("CELL_LOADED %s collision_meshes=%d" % [CELL_ID, collision_mesh_count])
	return true

func _prepare_runtime_glb(bundle_path: String, runtime_name: String) -> String:
	if not FileAccess.file_exists(bundle_path):
		return ""

	var runtime_dir := "user://runtime_cells/%s" % CELL_ID
	var runtime_dir_abs := ProjectSettings.globalize_path(runtime_dir)
	DirAccess.make_dir_recursive_absolute(runtime_dir_abs)
	var runtime_path := runtime_dir + "/" + runtime_name + ".glb"

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

	const COPY_CHUNK := 4 * 1024 * 1024
	while src.get_position() < source_size:
		var remaining := source_size - src.get_position()
		var chunk := src.get_buffer(min(COPY_CHUNK, remaining))
		dst.store_buffer(chunk)
	src.close()
	dst.close()
	return ProjectSettings.globalize_path(runtime_path)

func _load_glb(bundle_path: String, runtime_name: String) -> Node3D:
	var runtime_path := _prepare_runtime_glb(bundle_path, runtime_name)
	if runtime_path.is_empty():
		return null
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var err := document.append_from_file(runtime_path, state)
	if err != OK:
		push_error("GLB runtime load failed for %s: %s" % [runtime_name, err])
		return null
	var generated := document.generate_scene(state)
	if generated == null:
		push_error("GLB scene generation failed for %s" % runtime_name)
		return null
	return generated

func _attach_trimesh_collision(node: Node) -> int:
	var count := 0
	if node is MeshInstance3D:
		var mesh_instance := node as MeshInstance3D
		if mesh_instance.mesh != null:
			var shape_data := mesh_instance.mesh.create_trimesh_shape()
			if shape_data != null:
				var body := StaticBody3D.new()
				body.name = "TerrainStaticBody"
				var collision := CollisionShape3D.new()
				collision.shape = shape_data
				body.add_child(collision)
				mesh_instance.add_child(body)
				count += 1
	for child in node.get_children():
		count += _attach_trimesh_collision(child)
	return count

func _disable_shadows(node: Node) -> void:
	if node is MeshInstance3D:
		(node as MeshInstance3D).cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for child in node.get_children():
		_disable_shadows(child)
