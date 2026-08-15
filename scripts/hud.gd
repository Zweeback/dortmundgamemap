extends CanvasLayer
class_name DortmundHUD

const TOUCH_STICK_SCRIPT := preload("res://scripts/touch_stick.gd")

signal move_changed(value: Vector2)
signal jump_pressed
signal sprint_changed(enabled: bool)
signal map_pressed
signal reset_pressed

var info_label: Label
var mode_label: Label
var sprint_button: Button
var map_button: Button
var _fps_accum := 0.0

func _ready() -> void:
	_build_ui()

func _build_ui() -> void:
	var root := Control.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_PASS
	add_child(root)

	var title := Label.new()
	title.text = "DORTMUND // GAMEMAP"
	title.add_theme_font_size_override("font_size", 24)
	title.position = Vector2(20, 16)
	root.add_child(title)

	mode_label = Label.new()
	mode_label.text = "EXPLORE"
	mode_label.add_theme_font_size_override("font_size", 15)
	mode_label.position = Vector2(22, 48)
	mode_label.modulate = Color(1.0, 0.80, 0.25)
	root.add_child(mode_label)

	info_label = Label.new()
	info_label.text = "x 0  y 0  z 0"
	info_label.add_theme_font_size_override("font_size", 14)
	info_label.position = Vector2(22, 74)
	root.add_child(info_label)

	var stick := TOUCH_STICK_SCRIPT.new()
	stick.anchor_left = 0.0
	stick.anchor_top = 1.0
	stick.anchor_right = 0.0
	stick.anchor_bottom = 1.0
	stick.offset_left = 20.0
	stick.offset_top = -212.0
	stick.offset_right = 212.0
	stick.offset_bottom = -20.0
	stick.value_changed.connect(func(v: Vector2): move_changed.emit(v))
	root.add_child(stick)

	var jump_button := _make_button("JUMP", 112.0, 112.0)
	jump_button.anchor_left = 1.0
	jump_button.anchor_top = 1.0
	jump_button.anchor_right = 1.0
	jump_button.anchor_bottom = 1.0
	jump_button.offset_left = -136.0
	jump_button.offset_top = -150.0
	jump_button.offset_right = -24.0
	jump_button.offset_bottom = -38.0
	jump_button.pressed.connect(func(): jump_pressed.emit())
	root.add_child(jump_button)

	sprint_button = _make_button("RUN", 92.0, 62.0)
	sprint_button.toggle_mode = true
	sprint_button.anchor_left = 1.0
	sprint_button.anchor_top = 1.0
	sprint_button.anchor_right = 1.0
	sprint_button.anchor_bottom = 1.0
	sprint_button.offset_left = -242.0
	sprint_button.offset_top = -106.0
	sprint_button.offset_right = -150.0
	sprint_button.offset_bottom = -44.0
	sprint_button.toggled.connect(func(on: bool): sprint_changed.emit(on))
	root.add_child(sprint_button)

	map_button = _make_button("MAP", 100.0, 54.0)
	map_button.anchor_left = 1.0
	map_button.anchor_top = 0.0
	map_button.anchor_right = 1.0
	map_button.anchor_bottom = 0.0
	map_button.offset_left = -120.0
	map_button.offset_top = 18.0
	map_button.offset_right = -20.0
	map_button.offset_bottom = 72.0
	map_button.pressed.connect(func(): map_pressed.emit())
	root.add_child(map_button)

	var reset_button := _make_button("RESET", 100.0, 48.0)
	reset_button.anchor_left = 1.0
	reset_button.anchor_top = 0.0
	reset_button.anchor_right = 1.0
	reset_button.anchor_bottom = 0.0
	reset_button.offset_left = -120.0
	reset_button.offset_top = 82.0
	reset_button.offset_right = -20.0
	reset_button.offset_bottom = 130.0
	reset_button.pressed.connect(func(): reset_pressed.emit())
	root.add_child(reset_button)

	var hint := Label.new()
	hint.text = "left: move  •  right drag: look"
	hint.anchor_left = 0.5
	hint.anchor_top = 1.0
	hint.anchor_right = 0.5
	hint.anchor_bottom = 1.0
	hint.offset_left = -160.0
	hint.offset_top = -38.0
	hint.offset_right = 160.0
	hint.offset_bottom = -12.0
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.modulate = Color(1, 1, 1, 0.58)
	root.add_child(hint)

func _make_button(text_value: String, width: float, height: float) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(width, height)
	button.add_theme_font_size_override("font_size", 17)
	return button

func update_position(pos: Vector3) -> void:
	if info_label:
		info_label.text = "x %.1f   y %.1f   z %.1f   |   %d FPS" % [pos.x, pos.y, pos.z, int(Engine.get_frames_per_second())]

func set_map_mode(enabled: bool) -> void:
	if mode_label:
		mode_label.text = "BIRD'S-EYE MAP" if enabled else "EXPLORE"
	if map_button:
		map_button.text = "PLAY" if enabled else "MAP"
