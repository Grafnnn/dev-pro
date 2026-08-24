from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import requests
import trimesh
from shapely.geometry import LineString, Polygon, box as sbox


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def centerline(g):
    v=np.asarray(g.vertices,float); n=len(v)//2
    a,b=v[:n],v[n:]
    return (a+b)/2


def hull_xy(g):
    v=np.asarray(g.vertices,float)
    return Polygon(v[:,:2]).convex_hull


def main():
    root=Path('work_plot'); root.mkdir(exist_ok=True)
    arc=root/'source.zip'; download(os.environ['SOURCE_ZIP_URL'],arc)
    ext=root/'src'; ext.mkdir(exist_ok=True)
    with zipfile.ZipFile(arc) as zf: zf.extractall(ext)
    glb=max(ext.rglob('*.glb'),key=lambda p:p.stat().st_size)
    sc=trimesh.load(str(glb),force='scene',process=False)
    if not isinstance(sc,trimesh.Scene): sc=trimesh.Scene(sc)

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
    buildings=[]
    for code,items in groups.items():
        items.sort(key=lambda x:(x[0],x[1]),reverse=True)
        _,_,name,g=items[0]
        buildings.append((code,name,hull_xy(g)))

    fig,ax=plt.subplots(figsize=(16,12),dpi=180)
    terrain=sc.geometry['finished_design_surface']
    tb=terrain.bounds
    ax.set_xlim(tb[0,0],tb[1,0]); ax.set_ylim(tb[0,1],tb[1,1]); ax.set_aspect('equal')
    ax.set_facecolor('#eef1e7')

    for code,name,poly in buildings:
        x,y=poly.exterior.xy
        ax.fill(x,y,alpha=.45,color='#c66c57')
        c=poly.centroid
        ax.text(c.x,c.y,f'{code}\n{name.replace(code+"_","")}',ha='center',va='center',fontsize=6,color='#521d15')

    colors={'D1':'#0066cc','D2':'#cc7a00','D3':'#b000b5','D4':'#008c76','D5':'#c0003f','D6':'#4c4c4c'}
    for code in colors:
        g=sc.geometry[f'road_{code}']; cl=centerline(g)
        ax.plot(cl[:,0],cl[:,1],color=colors[code],lw=2,label=code)
        road=LineString(cl[:,:2]).buffer({'D1':4,'D2':3.5,'D3':3.5,'D4':4,'D5':3.5,'D6':3.5}[code],cap_style=2,join_style=2)
        x,y=road.exterior.xy; ax.fill(x,y,color=colors[code],alpha=.12)
        for bcode,bname,poly in buildings:
            area=road.intersection(poly).area
            if area>.2:
                inter=road.intersection(poly)
                if not inter.is_empty:
                    try:
                        x,y=inter.exterior.xy; ax.fill(x,y,color='yellow',alpha=.9)
                    except Exception:
                        pass
                    p=inter.centroid
                    ax.text(p.x,p.y,f'{code}×{bcode}\n{area:.1f}',fontsize=7,color='black',bbox=dict(fc='yellow',ec='black',pad=1))
    ax.legend(loc='upper left')
    ax.grid(True,alpha=.15)
    ax.set_title('A.1 LOD400-P: исходные дороги и фактические внешние контуры зданий')
    out=Path('road_debug'); out.mkdir(exist_ok=True)
    fig.tight_layout(); fig.savefig(out/'road_building_debug.png'); plt.close(fig)

    with (out/'road_building_intersections.csv').open('w',encoding='utf-8-sig') as f:
        f.write('road;building;mesh;intersection_m2\n')
        for code in colors:
            cl=centerline(sc.geometry[f'road_{code}'])
            road=LineString(cl[:,:2]).buffer({'D1':4,'D2':3.5,'D3':3.5,'D4':4,'D5':3.5,'D6':3.5}[code],cap_style=2,join_style=2)
            for bcode,bname,poly in buildings:
                area=road.intersection(poly).area
                if area>.2:f.write(f'{code};{bcode};{bname};{area:.3f}\n')
    print('ROAD_BUILDING_DEBUG_DONE')

if __name__=='__main__':main()
