extends Control
class_name TouchStick

signal value_changed(value: Vector2)

var value: Vector2 = Vector2.ZERO
var _touch_id: int = -1
var _mouse_down := false
var _center := Vector2.ZERO
var _radius := 72.0
var _knob_radius := 29.0

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	queue_redraw()

func _notification(what: int) -> void:
	if what == NOTIFICATION_RESIZED:
		_center = size * 0.5
		_radius = max(38.0, min(size.x, size.y) * 0.40)
		_knob_radius = _radius * 0.38
		queue_redraw()

func _draw() -> void:
	if _center == Vector2.ZERO:
		_center = size * 0.5
	draw_circle(_center, _radius, Color(0.06, 0.08, 0.12, 0.56))
	draw_arc(_center, _radius, 0.0, TAU, 48, Color(1.0, 1.0, 1.0, 0.22), 3.0, true)
	draw_circle(_center + value * _radius, _knob_radius, Color(0.95, 0.80, 0.22, 0.88))

func _gui_input(event: InputEvent) -> void:
	if event is InputEventScreenTouch:
		if event.pressed and _touch_id == -1:
			_touch_id = event.index
			_update_value(event.position)
			accept_event()
		elif not event.pressed and event.index == _touch_id:
			_touch_id = -1
			_set_value(Vector2.ZERO)
			accept_event()
	elif event is InputEventScreenDrag and event.index == _touch_id:
		_update_value(event.position)
		accept_event()
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		_mouse_down = event.pressed
		if _mouse_down:
			_update_value(event.position)
		else:
			_set_value(Vector2.ZERO)
		accept_event()
	elif event is InputEventMouseMotion and _mouse_down:
		_update_value(event.position)
		accept_event()

func _update_value(local_position: Vector2) -> void:
	var delta := local_position - _center
	_set_value(delta.limit_length(_radius) / _radius)

func _set_value(new_value: Vector2) -> void:
	value = new_value
	value_changed.emit(value)
	queue_redraw()
