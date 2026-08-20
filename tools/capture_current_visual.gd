extends SceneTree

const OUTPUT_RELATIVE_PATH := "docs/status/current.png"
const WARMUP_FRAMES := 90

func _initialize() -> void:
    call_deferred("_capture")

func _capture() -> void:
    var scene_path: String = ProjectSettings.get_setting("application/run/main_scene", "")
    if scene_path.is_empty():
        push_error("application/run/main_scene is not configured")
        quit(2)
        return

    var packed := load(scene_path) as PackedScene
    if packed == null:
        push_error("Unable to load main scene: %s" % scene_path)
        quit(3)
        return

    var scene := packed.instantiate()
    root.add_child(scene)

    for _frame in range(WARMUP_FRAMES):
        await process_frame

    var image := root.get_texture().get_image()
    if image == null or image.is_empty():
        push_error("Viewport capture returned an empty image")
        quit(4)
        return

    image.resize(1600, 900, Image.INTERPOLATE_LANCZOS)
    var output_path: String = ProjectSettings.globalize_path("res://").path_join(OUTPUT_RELATIVE_PATH)
    DirAccess.make_dir_recursive_absolute(output_path.get_base_dir())
    var result := image.save_png(output_path)
    if result != OK:
        push_error("Unable to save screenshot: %s" % error_string(result))
        quit(5)
        return

    print("CURRENT_VISUAL_SAVED=", OUTPUT_RELATIVE_PATH)
    quit(0)
