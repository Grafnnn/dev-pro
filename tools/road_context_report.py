from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import numpy as np
import requests
import trimesh
from shapely.geometry import LineString, Polygon


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def centerline(g):
    v=np.asarray(g.vertices,float); n=len(v)//2
    return (v[:n]+v[n:])/2


def main():
    root=Path('work_context'); root.mkdir(exist_ok=True)
    arc=root/'source.zip'; download(os.environ['SOURCE_ZIP_URL'],arc)
    ext=root/'src'; ext.mkdir(exist_ok=True)
    with zipfile.ZipFile(arc) as zf: zf.extractall(ext)
    glb=max(ext.rglob('*.glb'),key=lambda p:p.stat().st_size)
    sc=trimesh.load(str(glb),force='scene',process=False)
    if not isinstance(sc,trimesh.Scene): sc=trimesh.Scene(sc)
    out=Path('audit'); out.mkdir(exist_ok=True)
    lines=['# Road and building context','']
    widths={'D1':8,'D2':7,'D3':6,'D4':8,'D5':7,'D6':6}
    for code in widths:
        cl=centerline(sc.geometry[f'road_{code}'])
        ls=LineString(cl[:,:2])
        simp=np.asarray(ls.simplify(1.0,preserve_topology=False).coords,float)
        lines.append(f'## ROAD {code} width={widths[code]} raw_points={len(cl)} length={ls.length:.3f} start={cl[0].round(3).tolist()} end={cl[-1].round(3).tolist()} bounds={ls.bounds}')
        lines.append('simplified_xy_1m:')
        for p in simp: lines.append(f'- [{p[0]:.3f}, {p[1]:.3f}]')
        lines.append('raw_xyz:')
        for p in cl: lines.append(f'- [{p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f}]')
        lines.append('')

    excluded=('FOUNDATION','PILE','ROOF','CANOPY','APRON','STAIR','RAILING','GUTTER','DOWNPIPE','DOOR','WINDOW','LOUVER','SERVICE','ANCHOR')
    preferred=('CLADDING','WALL','ENVELOPE','BODY','SHELL')
    groups={}
    for name,g in sc.geometry.items():
        m=re.match(r'(BLD_[0-9]+[A-Z]?)_',name,re.I)
        if not m or any(t in name.upper() for t in excluded): continue
        e=np.asarray(g.extents,float)
        if e[2]<2.5 or e[0]*e[1]<8: continue
        priority=1 if any(t in name.upper() for t in preferred) else 0
        groups.setdefault(m.group(1),[]).append((priority,e[0]*e[1],name,g))
    lines.append('# BUILDINGS')
    for code,items in sorted(groups.items()):
        items.sort(key=lambda x:(x[0],x[1]),reverse=True)
        _,_,name,g=items[0]
        v=np.asarray(g.vertices,float); poly=Polygon(v[:,:2]).convex_hull; c=poly.centroid
        lines.append(f'## {code} mesh={name} centroid=[{c.x:.3f},{c.y:.3f}] bounds={poly.bounds} area={poly.area:.3f}')
        lines.append('hull:')
        for x,y in poly.exterior.coords: lines.append(f'- [{x:.3f}, {y:.3f}]')
    (out/'road_context_report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('ROAD_CONTEXT_DONE')

if __name__=='__main__':main()
