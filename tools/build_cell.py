#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path

def run(cmd): print("+"," ".join(cmd)); subprocess.run(cmd,check=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("cell",type=Path);p.add_argument("--raw-root",type=Path,default=Path("data/raw"));p.add_argument("--derived-root",type=Path,default=Path("data/derived"));a=p.parse_args();cell=json.loads(a.cell.read_text());raw=a.raw_root/cell["id"];derived=a.derived_root/cell["id"];derived.mkdir(parents=True,exist_ok=True);py=sys.executable
    run([py,"tools/build_terrain.py",str(raw/"dgm1.tif"),"--cell",str(a.cell),"--out",str(derived/"terrain_render.glb"),"--step","2"])
    run([py,"tools/build_terrain.py",str(raw/"dgm1.tif"),"--cell",str(a.cell),"--out",str(derived/"terrain_collision.glb"),"--step","4"])
    for tile in cell["sources"]["lod2_tiles"]: run([py,"tools/citygml_to_glb.py",str(raw/"lod2"/tile),"--cell",str(a.cell),"--out",str(derived/(Path(tile).stem+".glb"))])
if __name__=="__main__":main()
