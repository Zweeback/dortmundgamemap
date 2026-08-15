import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("fetch_cell",ROOT/"tools"/"fetch_cell.py");mod=importlib.util.module_from_spec(SPEC);assert SPEC.loader;SPEC.loader.exec_module(mod)
class CellPipelineTest(unittest.TestCase):
 def setUp(self): self.cell=mod.load_cell(ROOT/"cells"/"phoenix_west_001.json")
 def test_cell_dimensions(self): self.assertEqual(self.cell["bbox"],[394744.0,5705000.0,395000.0,5705256.0]);self.assertEqual(self.cell["size_m"],256.0)
 def test_lod2_tile(self): self.assertIn("lod2_do_20251103_ul_394000_5705000.gml",self.cell["sources"]["lod2_tiles"])
 def test_alkis_bbox_request(self):
  u=mod.alkis_url(self.cell);self.assertIn("ALKIS_ADV:ALKIS_ADV_GebaeudeBauwerk",u);self.assertIn("394744.0,5705000.0,395000.0,5705256.0,EPSG:25832",u)
 def test_dgm_request(self):
  u=mod.dgm_url(self.cell);self.assertIn("COVERAGEID=nw_dgm",u);self.assertIn("SUBSET=x(394744.0,395000.0)",u);self.assertIn("SUBSET=y(5705000.0,5705256.0)",u)
 def test_dop_request(self):
  u=mod.dop_url(self.cell,.5);self.assertIn("COVERAGEID=nw_dop",u);self.assertIn("RANGESUBSET=1,2,3",u);self.assertIn("SCALEFACTOR=0.5",u)
if __name__=="__main__":unittest.main()
