extends Node3D

const CITY_BUNDLE_PATH := "res://assets/dortmund.glbraw"
const CITY_RUNTIME_PATH := "user://dortmund.glb"
const PLAYER_SCRIPT := preload("res://scripts/player.gd")
const HUD_SCRIPT := preload("res://scripts/hud.gd")
const WORLD_CELL_SCRIPT := preload("res://scripts/world_cell_loader.gd")
const STREAMING_MANAGER_SCRIPT := preload("res://scripts/world_streaming_manager.gd")

var player
var hud
var map_camera: Camera3D
var map_mode := true
var city_root: Node3D
var city_size_xz := Vector2(1336.0, 1140.0)
var world_cell
var using_stream_cell := false
var streaming_manager: WorldStreamingManager = null
var _streaming_play_ready := false

func _ready() -> void:
	_build_environment()
	# Streaming manager is authoritative when the index is present;
	# legacy single-cell loader is only used as fallback when manager is absent.
	_try_start_streaming_manager()
	if streaming_manager == null:
		using_stream_cell = _build_stream_cell()
	if streaming_manager == null and not using_stream_cell:
		_build_ground()
		_build_city()
	_build_player()
	if streaming_manager != null:
		streaming_manager.player_ref = player
		streaming_manager.collision_ready.connect(_on_streaming_collision_ready)
		player.spawn_resolved.connect(_on_player_spawn_resolved)
		_apply_streaming_spawn()
		print("SPAWN_HANDSHAKE_ARMED position=%s" % player.global_position)
		streaming_manager.update_streaming(player.global_position)
	_build_map_camera()
	_build_hud()

func _process(_delta: float) -> void:
	if map_mode and map_camera and player:
		map_camera.global_position.x = player.global_position.x
		map_camera.global_position.z = player.global_position.z

func _try_start_streaming_manager() -> void:
	var mgr := STREAMING_MANAGER_SCRIPT.new()
	mgr.name = "WorldStreamingManager"
	if not mgr.load_index():
		mgr.free()
		return
	add_child(mgr)
	streaming_manager = mgr


func _apply_streaming_spawn() -> void:
	if streaming_manager == null or player == null:
		return
	var xz: Vector2 = streaming_manager.spawn_godot_xz
	if xz == Vector2.ZERO:
		return
	player.position = Vector3(xz.x, player.position.y, xz.y)


## Called when terrain-collision cells have entered the physics world.
## Triggers a deferred spawn Y re-resolution to fix the first-frame race.
func _on_streaming_collision_ready() -> void:
	if player != null:
		print("SPAWN_COLLISION_READY received")
		player.resolve_spawn_when_ready()

func _on_player_spawn_resolved(position_3d: Vector3) -> void:
	_streaming_play_ready = true
	print("SPAWN_READY_FOR_PLAY position=%s" % position_3d)
	_on_player_coordinates_changed(position_3d)
	if map_mode:
		toggle_map()

func _on_player_coordinates_changed(position_3d: Vector3) -> void:
	if hud == null:
		return
	var current_cell_id := ""
	var active_cell_count := 0
	if streaming_manager != null:
		current_cell_id = streaming_manager.get_current_cell_id(position_3d)
		active_cell_count = streaming_manager.get_active_cell_count()
	hud.update_runtime_metrics(position_3d, current_cell_id, active_cell_count)


func _build_stream_cell() -> bool:
	var candidate = WORLD_CELL_SCRIPT.new()
	candidate.name = "PhoenixWest001"
	if not candidate.has_packaged_cell():
		candidate.free()
		return false
	add_child(candidate)
	if not candidate.load_packaged_cell():
		candidate.queue_free()
		return false
	world_cell = candidate
	city_root = candidate
	city_size_xz = candidate.cell_size_xz
	return true

func _build_environment() -> void:
	var world_environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.43, 0.67, 0.88)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.68, 0.76, 0.92)
	env.ambient_light_energy = 1.25
	env.fog_enabled = false
	world_environment.environment = env
	add_child(world_environment)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-48.0, -35.0, 0.0)
	sun.light_energy = 1.15
	sun.light_color = Color(1.0, 0.94, 0.83)
	sun.shadow_enabled = false
	add_child(sun)

func _build_ground() -> void:
	var ground := StaticBody3D.new()
	ground.name = "Ground"
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(1250.0, 0.2, 1250.0)
	shape.shape = box
	shape.position.y = -0.12
	ground.add_child(shape)
	var mesh_instance := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(1250.0, 1250.0)
	mesh_instance.mesh = plane
	mesh_instance.position.y = -0.01
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.12, 0.16, 0.18)
	mat.roughness = 1.0
	mesh_instance.material_override = mat
	ground.add_child(mesh_instance)
	add_child(ground)

func _build_city() -> void:
	var runtime_path := _prepare_runtime_city_file()
	if runtime_path.is_empty():
		push_warning("Dortmund runtime asset missing; running lightweight placeholder city.")
		_build_placeholder_city()
		return
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var err := document.append_from_file(runtime_path, state)
	if err != OK:
		push_error("GLB runtime load failed with error %s" % err)
		_build_placeholder_city()
		return
	var generated := document.generate_scene(state)
	if generated == null:
		push_error("GLB runtime scene generation failed")
		_build_placeholder_city()
		return
	city_root = generated
	city_root.name = "DortmundOriginalFullGeometry"
	add_child(city_root)
	_center_city_to_origin(city_root)

func _prepare_runtime_city_file() -> String:
	if not FileAccess.file_exists(CITY_BUNDLE_PATH):
		return ""
	var src := FileAccess.open(CITY_BUNDLE_PATH, FileAccess.READ)
	if src == null:
		return ""
	var source_size := src.get_length()
	if FileAccess.file_exists(CITY_RUNTIME_PATH):
		var existing := FileAccess.open(CITY_RUNTIME_PATH, FileAccess.READ)
		if existing != null and existing.get_length() == source_size:
			existing.close()
			src.close()
			return ProjectSettings.globalize_path(CITY_RUNTIME_PATH)
		if existing != null:
			existing.close()
	var dst := FileAccess.open(CITY_RUNTIME_PATH, FileAccess.WRITE)
	if dst == null:
		src.close()
		return ""
	const CHUNK_SIZE := 4 * 1024 * 1024
	while src.get_position() < source_size:
		var remaining := source_size - src.get_position()
		var chunk := src.get_buffer(min(CHUNK_SIZE, remaining))
		dst.store_buffer(chunk)
	src.close()
	dst.close()
	return ProjectSettings.globalize_path(CITY_RUNTIME_PATH)

func _build_placeholder_city() -> void:
	city_root = Node3D.new()
	city_root.name = "DortmundPlaceholder"
	add_child(city_root)
	var block_mat := StandardMaterial3D.new()
	block_mat.albedo_color = Color(0.46, 0.50, 0.56)
	block_mat.roughness = 0.95
	for x in range(-4, 5):
		for z in range(-4, 5):
			if (x + z) % 3 == 0:
				continue
			var mesh_instance := MeshInstance3D.new()
			var box := BoxMesh.new()
			var height := 7.0 + float(abs((x * 13 + z * 7) % 18))
			box.size = Vector3(8.0, height, 8.0)
			mesh_instance.mesh = box
			mesh_instance.position = Vector3(float(x) * 14.0, height * 0.5, float(z) * 14.0)
			mesh_instance.material_override = block_mat
			city_root.add_child(mesh_instance)

func _build_player() -> void:
	player = PLAYER_SCRIPT.new()
	player.name = "Player"
	if using_stream_cell and world_cell != null:
		player.position = world_cell.player_spawn
	elif streaming_manager != null:
		var xz: Vector2 = streaming_manager.spawn_godot_xz
		player.position = Vector3(xz.x, 1.25, xz.y)
	else:
		player.position = Vector3(0.0, 1.25, 0.0)
	add_child(player)

func _build_map_camera() -> void:
	map_camera = Camera3D.new()
	map_camera.name = "MapCamera"
	map_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	map_camera.keep_aspect = Camera3D.KEEP_HEIGHT
	map_camera.position = Vector3(0.0, 900.0, 0.0)
	map_camera.rotation_degrees = Vector3(-90.0, 0.0, 0.0)
	map_camera.cull_mask = 0xFFFFF
	add_child(map_camera)
	var viewport_size: Vector2 = get_viewport().get_visible_rect().size
	var aspect: float = viewport_size.x / maxf(viewport_size.y, 1.0)
	var required_height: float = maxf(city_size_xz.y, city_size_xz.x / maxf(aspect, 0.1))
	map_camera.size = required_height * 1.08
	map_camera.current = true
	if player:
		player.controls_enabled = false
		if player.camera:
			player.camera.current = false

func _build_hud() -> void:
	hud = HUD_SCRIPT.new()
	hud.name = "HUD"
	add_child(hud)
	hud.move_changed.connect(player.set_touch_move)
	hud.jump_pressed.connect(player.jump)
	hud.sprint_changed.connect(player.set_touch_sprint)
	hud.map_pressed.connect(toggle_map)
	hud.reset_pressed.connect(player.reset_to_spawn)
	player.coordinates_changed.connect(_on_player_coordinates_changed)
	hud.set_map_mode(map_mode)
	_on_player_coordinates_changed(player.global_position)

func toggle_map() -> void:
	if map_mode and streaming_manager != null and not _streaming_play_ready:
		print("PLAY_BLOCKED_WAITING_FOR_STREAM")
		return
	map_mode = not map_mode
	player.controls_enabled = not map_mode and (streaming_manager == null or _streaming_play_ready)
	player.set_touch_move(Vector2.ZERO)
	player.set_touch_sprint(false)
	if player.camera:
		player.camera.current = not map_mode
	if map_camera:
		map_camera.current = map_mode
	if hud:
		hud.set_map_mode(map_mode)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_M:
			toggle_map()
		elif event.keycode == KEY_R and player:
			player.reset_to_spawn()

func _center_city_to_origin(root: Node3D) -> void:
	var bounds := _collect_mesh_bounds(root)
	if bounds.size == Vector3.ZERO:
		return
	city_size_xz = Vector2(bounds.size.x, bounds.size.z)
	var center_xz := Vector3(bounds.position.x + bounds.size.x * 0.5, bounds.position.y, bounds.position.z + bounds.size.z * 0.5)
	root.global_position += Vector3(-center_xz.x, -bounds.position.y, -center_xz.z)

func _collect_mesh_bounds(root: Node3D) -> AABB:
	var found := false
	var combined := AABB()
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var node: Node = stack.pop_back() as Node
		if node is MeshInstance3D:
			var mi := node as MeshInstance3D
			if mi.mesh != null:
				var local_box: AABB = mi.get_aabb()
				var corners: Array[Vector3] = [
					local_box.position,
					local_box.position + Vector3(local_box.size.x, 0, 0),
					local_box.position + Vector3(0, local_box.size.y, 0),
					local_box.position + Vector3(0, 0, local_box.size.z),
					local_box.position + Vector3(local_box.size.x, local_box.size.y, 0),
					local_box.position + Vector3(local_box.size.x, 0, local_box.size.z),
					local_box.position + Vector3(0, local_box.size.y, local_box.size.z),
					local_box.position + local_box.size
				]
				for c: Vector3 in corners:
					var p: Vector3 = mi.global_transform * c
					if not found:
						combined = AABB(p, Vector3.ZERO)
						found = true
					else:
						combined = combined.expand(p)
		for child in node.get_children():
			stack.append(child)
	return combined
