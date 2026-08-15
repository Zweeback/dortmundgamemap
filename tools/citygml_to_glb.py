#!/usr/bin/env python3
"""Extract CityGML LoD2 surfaces intersecting a cell and export a local-space GLB."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Iterable
import numpy as np
from lxml import etree
GML="http://www.opengis.net/gml"; BLDG="http://www.opengis.net/citygml/building/2.0"; NS={"gml":GML,"bldg":BLDG}

def parse_poslist(text:str,dim:int=3)->np.ndarray:
    vals=np.fromstring(text or "",sep=" ",dtype=np.float64)
    if len(vals)<dim*3 or len(vals)%dim:return np.empty((0,3),dtype=np.float64)
    pts=vals.reshape((-1,dim))[:,:3]
    if len(pts)>1 and np.allclose(pts[0],pts[-1]):pts=pts[:-1]
    return pts

def polygon_normal(p):
    n=np.zeros(3)
    for i in range(len(p)):n+=np.cross(p[i],p[(i+1)%len(p)])
    k=np.linalg.norm(n); return n/k if k else np.array([0.,0.,1.])

def project(p):
    drop=int(np.argmax(np.abs(polygon_normal(p)))); return np.delete(p,drop,axis=1)

def area(p):
    x,y=p[:,0],p[:,1]; return .5*float(np.sum(x*np.roll(y,-1)-np.roll(x,-1)*y))

def inside(p,a,b,c):
    def cr(u,v,w):return (v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0])
    x=[cr(a,b,p),cr(b,c,p),cr(c,a,p)]; return not (any(v < -1e-10 for v in x) and any(v > 1e-10 for v in x))

def triangulate(p3):
    if len(p3)<3:return []
    p=project(p3); order=list(range(len(p))); ccw=area(p)>0; faces=[]; guard=0
    while len(order)>3 and guard<len(p)*len(p):
        found=False
        for j in range(len(order)):
            i0,i1,i2=order[j-1],order[j],order[(j+1)%len(order)]; a,b,c=p[i0],p[i1],p[i2]
            turn=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            if (ccw and turn<=1e-10) or ((not ccw) and turn>=-1e-10):continue
            if any(inside(p[k],a,b,c) for k in order if k not in (i0,i1,i2)):continue
            faces.append((i0,i1,i2) if ccw else (i2,i1,i0)); del order[j]; found=True; break
        if not found:break
        guard+=1
    if len(order)==3:
        a,b,c=order; faces.append((a,b,c) if ccw else (c,b,a))
    return faces or [(0,i,i+1) for i in range(1,len(p3)-1)]

def intersects(points:Iterable[np.ndarray],bbox):
    arr=[p for p in points if len(p)]
    if not arr:return False
    p=np.vstack(arr); minx,miny,maxx,maxy=bbox
    return not (p[:,0].max()<minx or p[:,0].min()>maxx or p[:,1].max()<miny or p[:,1].min()>maxy)

def extract(src:Path,bbox,origin_e,origin_n,out:Path):
    import trimesh
    vertices=[]; faces=[]; buildings=polygons=holes=0
    ctx=etree.iterparse(str(src),events=("end",),tag=f"{{{BLDG}}}Building",huge_tree=True)
    for _,b in ctx:
        rings=[]
        for poly in b.xpath(".//gml:Polygon",namespaces=NS):
            ext=poly.xpath("./gml:exterior//gml:posList",namespaces=NS)
            if not ext:continue
            dim=int(ext[0].get("srsDimension") or poly.get("srsDimension") or 3); pts=parse_poslist(ext[0].text,dim)
            if len(pts)>=3:rings.append(pts)
            holes+=len(poly.xpath("./gml:interior//gml:posList",namespaces=NS))
        if intersects(rings,bbox):
            buildings+=1
            for pts in rings:
                local=np.column_stack([pts[:,0]-origin_e,pts[:,2],-(pts[:,1]-origin_n)]); tri=triangulate(local)
                base=len(vertices); vertices.extend(local.tolist()); faces.extend((base+a,base+b0,base+c) for a,b0,c in tri); polygons+=1
        b.clear()
        while b.getprevious() is not None:del b.getparent()[0]
    if not faces:raise RuntimeError("No LoD2 surfaces intersect the cell bbox")
    mesh=trimesh.Trimesh(np.asarray(vertices),np.asarray(faces),process=False); out.parent.mkdir(parents=True,exist_ok=True); mesh.export(out)
    return {"source":str(src),"output":str(out),"buildings":buildings,"polygons":polygons,"vertices":int(len(mesh.vertices)),"triangles":int(len(mesh.faces)),"skipped_polygon_holes":holes,"bounds_local":mesh.bounds.tolist()}

def main():
    p=argparse.ArgumentParser();p.add_argument("gml",type=Path);p.add_argument("--cell",required=True,type=Path);p.add_argument("--out",type=Path,default=Path("data/derived/buildings_lod2.glb"));a=p.parse_args();cell=json.loads(a.cell.read_text());minx,miny,maxx,maxy=map(float,cell["bbox"]);print(json.dumps(extract(a.gml,(minx,miny,maxx,maxy),minx,miny,a.out),indent=2))
if __name__=="__main__":main()
