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


def main():
    root=Path('work_road_diag'); root.mkdir(exist_ok=True)
    arc=root/'source.zip'; download(os.environ['SOURCE_ZIP_URL'],arc)
    ext=root/'src'; ext.mkdir(exist_ok=True)
    with zipfile.ZipFile(arc) as zf: zf.extractall(ext)
    glb=max(ext.rglob('*.glb'),key=lambda p:p.stat().st_size)
    sc=trimesh.load(str(glb),force='scene',process=False)
    if not isinstance(sc,trimesh.Scene): sc=trimesh.Scene(sc)
    out=Path('audit'); out.mkdir(exist_ok=True)
    lines=[]
    for code in ('D1','D2','D3','D4','D5','D6'):
        g=sc.geometry[f'road_{code}']
        v=np.asarray(g.vertices,float); f=np.asarray(g.faces,int)
        lines.append(f'## {code} vertices={len(v)} faces={len(f)} bounds={g.bounds.tolist()}')
        lines.append('first vertices:')
        for i,p in enumerate(v[:40]): lines.append(f'{i}: {p.tolist()}')
        lines.append('last vertices:')
        for i,p in enumerate(v[-20:],start=len(v)-20): lines.append(f'{i}: {p.tolist()}')
        lines.append('first faces:')
        for i,face in enumerate(f[:40]): lines.append(f'{i}: {face.tolist()}')
        # unique Z and duplicate coordinate counts
        lines.append(f'unique_z_sample={np.unique(np.round(v[:,2],4))[:30].tolist()} count={len(np.unique(np.round(v[:,2],4)))}')
        lines.append('')
    (out/'road_vertex_diag.txt').write_text('\n'.join(lines),encoding='utf-8')
    print('ROAD_DIAG_DONE')

if __name__=='__main__': main()
