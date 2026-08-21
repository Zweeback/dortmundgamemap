import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "showcase-48cell-apk.yml"
EXPORT_PRESETS_PATH = ROOT / "export_presets.cfg"
HUD_PATH = ROOT / "scripts" / "hud.gd"


class ShowcaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_reuses_verified_48_cell_artifact(self):
        self.assertIn("run-id: 32152051688", self.workflow)
        self.assertIn("name: dortmund-connected-world-48cells", self.workflow)
        self.assertIn("repository: Zweeback/dortmundgamemap", self.workflow)
        self.assertIn("path: assets/world_cells", self.workflow)

    def test_validates_manifest_contract_before_export(self):
        self.assertIn("idx['crs'] == 'EPSG:25832'", self.workflow)
        self.assertIn("idx['world_origin'] == [392192.0, 5704704.0, 100.0]", self.workflow)
        self.assertIn("assert len(idx['cells']) == 48", self.workflow)
        self.assertIn("terrain_render", self.workflow)
        self.assertIn("terrain_collision", self.workflow)

    def test_uploads_showcase_apk_artifact(self):
        self.assertIn("name: DortmundGameMap-48Cell-Showcase-APK", self.workflow)
        self.assertIn("artifact_id=${{ steps.upload_apk.outputs.artifact-id }}", self.workflow)
        self.assertIn('apk_name": "DortmundGameMap-48Cell-Showcase.apk"', self.workflow)


class ShowcaseExportPresetTest(unittest.TestCase):
    def setUp(self):
        self.presets = EXPORT_PRESETS_PATH.read_text(encoding="utf-8")

    def test_world_cells_are_packaged(self):
        self.assertIn("assets/world_cells/*.json", self.presets)
        self.assertIn("assets/world_cells/**/*.glbraw", self.presets)

    def test_package_id_is_showcase_specific(self):
        match = re.search(r'package/unique_name="([^"]+)"', self.presets)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "com.bentropie.dortmundgamemap.showcase48")


class ShowcaseHudTest(unittest.TestCase):
    def test_hud_exposes_streaming_debug_fields(self):
        hud = HUD_PATH.read_text(encoding="utf-8")
        self.assertIn("cell %s", hud)
        self.assertIn("active %d", hud)
        self.assertIn("HUD_DEBUG_METRICS", hud)


if __name__ == "__main__":
    unittest.main()
