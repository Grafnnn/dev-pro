from __future__ import annotations

import os
import zipfile
from pathlib import Path

import numpy as np
import requests
import trimesh


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def rgba(geom):
    try:
        fc = np.asarray(geom.visual.face_colors)
        if len(fc):
            return tuple(int(x) for x in fc[0])
    except Exception:
        pass
    return None


def row(name, g):
    ext=np.asarray(g.extents,float); b=np.asarray(g.bounds,float)
    return dict(name=name,ext=ext,bounds=b,faces=len(getattr(g,'faces',[])),verts=len(getattr(g,'vertices',[])),vol=float(abs(getattr(g,'volume',0.0))),rgba=rgba(g),area2=float(ext[0]*ext[1]))


def fmt(x):
    return '('+', '.join(f'{v:.3f}' for v in x)+')'


def main():
    root=Path('work_critical'); root.mkdir(exist_ok=True)
    arc=root/'source.zip'; download(os.environ['SOURCE_ZIP_URL'],arc)
    extdir=root/'src'; extdir.mkdir(exist_ok=True)
    with zipfile.ZipFile(arc) as zf: zf.extractall(extdir)
    glb=max(extdir.rglob('*.glb'),key=lambda p:p.stat().st_size)
    sc=trimesh.load(str(glb),force='scene',process=False)
    if not isinstance(sc,trimesh.Scene): sc=trimesh.Scene(sc)
    rows=[row(n,g) for n,g in sc.geometry.items()]
    groups={
      'largest_plan_area':sorted(rows,key=lambda r:-r['area2'])[:120],
      'large_flat_surfaces':sorted([r for r in rows if r['ext'][0]>20 and r['ext'][1]>20 and r['ext'][2]<3],key=lambda r:-r['area2']),
      'terrain_candidates':sorted([r for r in rows if r['ext'][0]>300 and r['ext'][1]>250],key=lambda r:-r['area2']),
      'long_thin_artifacts':sorted([r for r in rows if max(r['ext'][0],r['ext'][1])>50 and min(r['ext'][0],r['ext'][1],max(r['ext'][2],1e-9))<0.5],key=lambda r:-max(r['ext'])),
      'huge_volumes':sorted([r for r in rows if r['vol']>5000],key=lambda r:-r['vol']),
    }
    out=Path('audit'); out.mkdir(exist_ok=True)
    lines=['# Critical exterior geometry',f'- source `{glb.name}`','']
    for title,items in groups.items():
        lines.append(f'## {title} ({len(items)})')
        for r in items:
            lines.append(f"- `{r['name']}` ext={fmt(r['ext'])} min={fmt(r['bounds'][0])} max={fmt(r['bounds'][1])} area2={r['area2']:.1f} vol={r['vol']:.1f} f={r['faces']} rgba={r['rgba']}")
        lines.append('')
    (out/'critical_geometry.md').write_text('\n'.join(lines),encoding='utf-8')
    print('CRITICAL_GEOMETRY_DONE')

if __name__=='__main__': main()
