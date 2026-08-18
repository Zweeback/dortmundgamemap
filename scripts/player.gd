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

var _pending_spawn_resolve := false
var _resolve_retries := 0
var _spawn_resolve_active := false

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
	var resolved := _resolve_surface_position(candidate)
	global_position = resolved
	velocity = Vector3.ZERO
	_spawn = global_position

## Called once the streaming manager confirms that the initial collision batch
## has crossed a physics-frame boundary. The first ray is intentionally delayed
## to a fresh physics tick so it never runs inside the manager's ready signal.
func resolve_spawn_when_ready() -> void:
	_resolve_retries = 0
	_pending_spawn_resolve = true
	_spawn_resolve_active = true
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
	var resolved := _resolve_surface_position(_spawn)
	if not _pending_spawn_resolve:
		global_position = resolved
		velocity = Vector3.ZERO
		_spawn = resolved
		_spawn_resolve_active = false
		print("SPAWN_RESOLVED position=%s attempts=%d" % [resolved, _resolve_retries])
		return

	print("SPAWN_RAY_MISS attempt=%d xz=(%.3f, %.3f)" % [
		_resolve_retries, _spawn.x, _spawn.z])
	if _resolve_retries >= MAX_RESOLVE_RETRIES:
		_spawn_resolve_active = false
		push_error("SPAWN_RESOLVE_FAILED after %d physics-frame attempts at xz=(%.3f, %.3f)" % [
			_resolve_retries, _spawn.x, _spawn.z])
		return

	_schedule_spawn_resolve()

func _resolve_surface_position(pos: Vector3) -> Vector3:
	var space_state := get_world_3d().direct_space_state
	if space_state == null:
		_pending_spawn_resolve = true
		return pos
	var ray_from := Vector3(pos.x, pos.y + SPAWN_RAY_LENGTH * 0.5, pos.z)
	var ray_to := Vector3(pos.x, pos.y - SPAWN_RAY_LENGTH, pos.z)
	var query := PhysicsRayQueryParameters3D.create(ray_from, ray_to)
	query.exclude = [self]
	# The current terrain artifact has reversed triangle winding. The runtime
	# collider is deliberately two-sided; make the spawn query intent explicit.
	query.hit_back_faces = true
	var result := space_state.intersect_ray(query)
	if result.is_empty():
		_pending_spawn_resolve = true
		return pos
	_pending_spawn_resolve = false
	print("SPAWN_RAY_HIT y=%.3f collider=%s" % [float(result["position"].y), result["collider"]])
	return Vector3(pos.x, result["position"].y + SPAWN_ABOVE_SURFACE, pos.z)
