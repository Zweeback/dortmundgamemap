extends CharacterBody3D
class_name DortmundPlayer

signal coordinates_changed(position_3d: Vector3)

@export var walk_speed := 8.0
@export var sprint_speed := 15.0
@export var acceleration := 24.0
@export var air_acceleration := 8.0
@export var jump_velocity := 7.5
@export var gravity_strength := 22.0
@export var look_sensitivity := 0.0042

var touch_move := Vector2.ZERO
var touch_sprint := false
var controls_enabled := true
var _pitch := deg_to_rad(-18.0)
var _spawn := Vector3(0.0, 1.25, 0.0)
var _last_touch_look_id := -1

const SPAWN_ABOVE_SURFACE := 1.25
const SPAWN_RAY_LENGTH := 512.0
const MAX_RESOLVE_RETRIES := 24
const SPAWN_SEARCH_STEP := 4.0
const SPAWN_SEARCH_RINGS := 12
const SPAWN_CLEARANCE_RADIUS := 1.2
const SPAWN_MIN_GROUND_NORMAL_Y := 0.65
# Historical Android failure point from the screenshot/reproduction. CI must
# prove this X/Z is rejected because a loaded LoD2 building occupies it.
const HISTORIC_BAD_SPAWN_XZ := Vector2(2652.0, -376.0)

var _pending_spawn_resolve := false
var _resolve_retries := 0
var _spawn_resolve_active := false
var _spawn_building_bounds: Array[AABB] = []

var spring_arm: SpringArm3D
var camera: Camera3D

func _ready() -> void:
	_spawn = global_position
	_build_visuals()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _build_visuals() -> void:
	var collision := CollisionShape3D.new()
	var capsule_shape := CapsuleShape3D.new()
	capsule_shape.radius = 0.38
	capsule_shape.height = 1.8
	collision.shape = capsule_shape
	collision.position.y = 0.9
	add_child(collision)

	var body_mesh := MeshInstance3D.new()
	var capsule_mesh := CapsuleMesh.new()
	capsule_mesh.radius = 0.38
	capsule_mesh.height = 1.8
	body_mesh.mesh = capsule_mesh
	body_mesh.position.y = 0.9
	var body_mat := StandardMaterial3D.new()
	body_mat.albedo_color = Color(1.0, 0.76, 0.15)
	body_mat.metallic = 0.12
	body_mat.roughness = 0.55
	body_mesh.material_override = body_mat
	add_child(body_mesh)

	var head := MeshInstance3D.new()
	var head_mesh := SphereMesh.new()
	head_mesh.radius = 0.34
	head_mesh.height = 0.68
	head.mesh = head_mesh
	head.position = Vector3(0.0, 1.88, 0.0)
	head.material_override = body_mat
	add_child(head)

	spring_arm = SpringArm3D.new()
	spring_arm.spring_length = 6.5
	spring_arm.margin = 0.15
	spring_arm.position = Vector3(0.0, 1.55, 0.0)
	spring_arm.rotation.x = _pitch
	add_child(spring_arm)

	camera = Camera3D.new()
	camera.current = true
	camera.fov = 72.0
	camera.position = Vector3.ZERO
	spring_arm.add_child(camera)

func _physics_process(delta: float) -> void:
	if not controls_enabled:
		velocity = Vector3.ZERO
		return

	var keyboard := Vector2(
		float(Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT)) - float(Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT)),
		float(Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN)) - float(Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP))
	)
	var input_vec := touch_move if touch_move.length() > keyboard.length() else keyboard
	if input_vec.length() > 1.0:
		input_vec = input_vec.normalized()

	var local_dir := Vector3(input_vec.x, 0.0, input_vec.y)
	var world_dir := (Basis(Vector3.UP, rotation.y) * local_dir).normalized()
	var is_sprinting := Input.is_key_pressed(KEY_SHIFT) or touch_sprint
	var speed := sprint_speed if is_sprinting else walk_speed
	var target_xz := world_dir * speed
	var accel := acceleration if is_on_floor() else air_acceleration

	velocity.x = move_toward(velocity.x, target_xz.x, accel * delta)
	velocity.z = move_toward(velocity.z, target_xz.z, accel * delta)

	if not is_on_floor():
		velocity.y -= gravity_strength * delta

	move_and_slide()
	coordinates_changed.emit(global_position)

	if global_position.y < -25.0:
		reset_to_spawn()

func _unhandled_input(event: InputEvent) -> void:
	if not controls_enabled:
		return

	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_apply_look(event.relative)
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event is InputEventKey and event.pressed:
		if event.keycode == KEY_ESCAPE:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		elif event.keycode == KEY_SPACE and is_on_floor():
			velocity.y = jump_velocity
	elif event is InputEventScreenTouch:
		if event.pressed and event.position.x > get_viewport().get_visible_rect().size.x * 0.42 and _last_touch_look_id == -1:
			_last_touch_look_id = event.index
		elif not event.pressed and event.index == _last_touch_look_id:
			_last_touch_look_id = -1
	elif event is InputEventScreenDrag and event.index == _last_touch_look_id:
		_apply_look(event.relative * 1.55)

func _apply_look(relative: Vector2) -> void:
	rotation.y -= relative.x * look_sensitivity
	_pitch = clamp(_pitch - relative.y * look_sensitivity, deg_to_rad(-72.0), deg_to_rad(36.0))
	if spring_arm:
		spring_arm.rotation.x = _pitch

func set_touch_move(value: Vector2) -> void:
	touch_move = value

func set_touch_sprint(enabled: bool) -> void:
	touch_sprint = enabled

func jump() -> void:
	if controls_enabled and is_on_floor():
		velocity.y = jump_velocity

func reset_to_spawn() -> void:
	var resolved := _resolve_surface_position(_spawn)
	global_position = resolved
	velocity = Vector3.ZERO

func teleport_to(world_xz: Vector2) -> void:
	var candidate := Vector3(world_xz.x, _spawn.y, world_xz.y)
	var safe := _find_safe_spawn(candidate)
	if bool(safe.get("ok", false)):
		var resolved: Vector3 = safe["position"] as Vector3
		global_position = resolved
		velocity = Vector3.ZERO
		_spawn = resolved
		return
	var fallback := _resolve_surface_position(candidate)
	global_position = fallback
	velocity = Vector3.ZERO
	_spawn = global_position

## Called once the streaming manager confirms that the initial collision batch
## has crossed a physics-frame boundary. A spawn is accepted only if terrain is
## present AND the loaded building render geometry leaves free X/Z clearance.
func resolve_spawn_when_ready() -> void:
	_resolve_retries = 0
	_pending_spawn_resolve = true
	_spawn_resolve_active = true
	_refresh_spawn_building_bounds()
	_validate_historic_bad_spawn()
	print("SPAWN_RESOLVE_ARMED xz=(%.3f, %.3f)" % [_spawn.x, _spawn.z])
	_schedule_spawn_resolve()

func _schedule_spawn_resolve() -> void:
	if not _spawn_resolve_active or not is_inside_tree():
		return
	var retry_timer := get_tree().create_timer(0.0, true, true)
	retry_timer.timeout.connect(_attempt_spawn_resolve, CONNECT_ONE_SHOT)

func _attempt_spawn_resolve() -> void:
	if not _spawn_resolve_active or not is_inside_tree():
		return
	_resolve_retries += 1
	var safe := _find_safe_spawn(_spawn)
	if bool(safe.get("ok", false)):
		var resolved: Vector3 = safe["position"] as Vector3
		global_position = resolved
		velocity = Vector3.ZERO
		_spawn = resolved
		_pending_spawn_resolve = false
		_spawn_resolve_active = false
		print("SPAWN_SAFE_RESOLVED position=%s attempts=%d building_bounds=%d" % [
			resolved, _resolve_retries, _spawn_building_bounds.size()])
		return

	_pending_spawn_resolve = true
	print("SPAWN_SAFE_SEARCH_RETRY attempt=%d preferred_xz=(%.3f, %.3f)" % [
		_resolve_retries, _spawn.x, _spawn.z])
	if _resolve_retries >= MAX_RESOLVE_RETRIES:
		_spawn_resolve_active = false
		push_error("SPAWN_SAFE_RESOLVE_FAILED after %d attempts at preferred_xz=(%.3f, %.3f)" % [
			_resolve_retries, _spawn.x, _spawn.z])
		return

	_refresh_spawn_building_bounds()
	_schedule_spawn_resolve()

func _find_safe_spawn(preferred: Vector3) -> Dictionary:
	var offsets := _spawn_candidate_offsets()
	for offset: Vector2 in offsets:
		var probe := Vector3(preferred.x + offset.x, preferred.y, preferred.z + offset.y)
		var hit := _surface_hit(probe)
		if hit.is_empty():
			continue
		var normal: Vector3 = hit.get("normal", Vector3.UP) as Vector3
		if normal.y < SPAWN_MIN_GROUND_NORMAL_Y:
			continue
		var ground: Vector3 = hit["position"] as Vector3
		if not _is_ground_clear_of_buildings(ground):
			print("SPAWN_CANDIDATE_BLOCKED xz=(%.3f, %.3f) ground_y=%.3f" % [
				probe.x, probe.z, ground.y])
			continue
		return {
			"ok": true,
			"position": Vector3(probe.x, ground.y + SPAWN_ABOVE_SURFACE, probe.z),
			"ground": ground,
			"offset": offset,
		}
	return {"ok": false}

func _spawn_candidate_offsets() -> Array[Vector2]:
	var result: Array[Vector2] = [Vector2.ZERO]
	for ring in range(1, SPAWN_SEARCH_RINGS + 1):
		for ix in range(-ring, ring + 1):
			result.append(Vector2(float(ix) * SPAWN_SEARCH_STEP, -float(ring) * SPAWN_SEARCH_STEP))
			result.append(Vector2(float(ix) * SPAWN_SEARCH_STEP, float(ring) * SPAWN_SEARCH_STEP))
		for iz in range(-ring + 1, ring):
			result.append(Vector2(-float(ring) * SPAWN_SEARCH_STEP, float(iz) * SPAWN_SEARCH_STEP))
			result.append(Vector2(float(ring) * SPAWN_SEARCH_STEP, float(iz) * SPAWN_SEARCH_STEP))
	return result

func _refresh_spawn_building_bounds() -> void:
	_spawn_building_bounds.clear()
	var root: Node = get_tree().current_scene
	if root == null:
		root = get_tree().root
	_collect_building_bounds(root, false)
	print("BUILDING_BOUNDS_CACHED count=%d" % _spawn_building_bounds.size())

func _collect_building_bounds(node: Node, inside_building: bool) -> void:
	var now_inside := inside_building or String(node.name).begins_with("buildings_")
	if now_inside and node is MeshInstance3D:
		var mi := node as MeshInstance3D
		if mi.mesh != null:
			_spawn_building_bounds.append(_global_mesh_aabb(mi))
	for child in node.get_children():
		_collect_building_bounds(child, now_inside)

func _global_mesh_aabb(mi: MeshInstance3D) -> AABB:
	var local_box := mi.get_aabb()
	var corners: Array[Vector3] = [
		local_box.position,
		local_box.position + Vector3(local_box.size.x, 0.0, 0.0),
		local_box.position + Vector3(0.0, local_box.size.y, 0.0),
		local_box.position + Vector3(0.0, 0.0, local_box.size.z),
		local_box.position + Vector3(local_box.size.x, local_box.size.y, 0.0),
		local_box.position + Vector3(local_box.size.x, 0.0, local_box.size.z),
		local_box.position + Vector3(0.0, local_box.size.y, local_box.size.z),
		local_box.position + local_box.size,
	]
	var first: Vector3 = mi.global_transform * corners[0]
	var result := AABB(first, Vector3.ZERO)
	for i in range(1, corners.size()):
		result = result.expand(mi.global_transform * corners[i])
	return result

func _is_ground_clear_of_buildings(ground: Vector3) -> bool:
	var min_x := ground.x - SPAWN_CLEARANCE_RADIUS
	var max_x := ground.x + SPAWN_CLEARANCE_RADIUS
	var min_z := ground.z - SPAWN_CLEARANCE_RADIUS
	var max_z := ground.z + SPAWN_CLEARANCE_RADIUS
	for box: AABB in _spawn_building_bounds:
		var box_end := box.position + box.size
		var overlaps_x := box_end.x >= min_x and box.position.x <= max_x
		var overlaps_z := box_end.z >= min_z and box.position.z <= max_z
		# Reject being inside OR underneath a building shell. The screenshot bug
		# was exactly this case: valid terrain existed below a LoD2 roof/walls.
		var structure_above_ground := box_end.y > ground.y + 0.5
		if overlaps_x and overlaps_z and structure_above_ground:
			return false
	return true

func _validate_historic_bad_spawn() -> void:
	var probe := Vector3(HISTORIC_BAD_SPAWN_XZ.x, _spawn.y, HISTORIC_BAD_SPAWN_XZ.y)
	var hit := _surface_hit(probe)
	if hit.is_empty():
		push_error("SPAWN_REGRESSION_GUARD_FAILED: historic point has no terrain hit")
		return
	var ground: Vector3 = hit["position"] as Vector3
	if _is_ground_clear_of_buildings(ground):
		push_error("SPAWN_REGRESSION_GUARD_FAILED: historic in-building point was accepted")
		return
	print("SPAWN_REGRESSION_BLOCKED_OK xz=(%.3f, %.3f) ground_y=%.3f" % [
		HISTORIC_BAD_SPAWN_XZ.x, HISTORIC_BAD_SPAWN_XZ.y, ground.y])

func _surface_hit(pos: Vector3) -> Dictionary:
	var space_state := get_world_3d().direct_space_state
	if space_state == null:
		return {}
	var ray_from := Vector3(pos.x, pos.y + SPAWN_RAY_LENGTH * 0.5, pos.z)
	var ray_to := Vector3(pos.x, pos.y - SPAWN_RAY_LENGTH, pos.z)
	var query := PhysicsRayQueryParameters3D.create(ray_from, ray_to)
	query.exclude = [self]
	# The current terrain artifact has reversed triangle winding. The runtime
	# collider is deliberately two-sided; make the spawn query intent explicit.
	query.hit_back_faces = true
	return space_state.intersect_ray(query)

func _resolve_surface_position(pos: Vector3) -> Vector3:
	var result := _surface_hit(pos)
	if result.is_empty():
		_pending_spawn_resolve = true
		return pos
	_pending_spawn_resolve = false
	print("SPAWN_RAY_HIT y=%.3f collider=%s" % [float(result["position"].y), result["collider"]])
	return Vector3(pos.x, float(result["position"].y) + SPAWN_ABOVE_SURFACE, pos.z)
