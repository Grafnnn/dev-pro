from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import requests


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def main() -> None:
    root = Path('work_source')
    root.mkdir(exist_ok=True)
    archive = root / 'source.zip'
    download(os.environ['SOURCE_ZIP_URL'], archive)
    extract = root / 'src'
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    candidates = list(extract.rglob('build_stage7_lod400p.py'))
    if not candidates:
        raise RuntimeError('build_stage7_lod400p.py not found')
    src = candidates[0]
    lines = src.read_text(encoding='utf-8', errors='replace').splitlines()
    patterns = [
        r'ROAD', r'road', r'D1_', r'D2_', r'D3_', r'D4_', r'D5_', r'D6_',
        r'serp', r'centerline', r'polyline', r'path', r'terrace', r'pad_',
        r'retaining', r'wall', r'pond', r'snow', r'fence', r'lighting',
        r'building', r'BLD_', r'landscape', r'tree', r'ground', r'terrain',
        r'export', r'glb', r'scene.add_geometry', r'TRANSFORM', r'NET_',
    ]
    rx = re.compile('|'.join(f'(?:{p})' for p in patterns), re.I)
    selected = set()
    for i, line in enumerate(lines):
        if rx.search(line):
            for j in range(max(0, i-5), min(len(lines), i+9)):
                selected.add(j)
    out_lines = [f'# Sanitized line excerpts from {src.name}', '']
    last = -10
    for i in sorted(selected):
        if i > last + 1:
            out_lines.append('')
            out_lines.append(f'--- around line {i+1} ---')
        out_lines.append(f'{i+1:05d}: {lines[i]}')
        last = i
    out = Path('audit')
    out.mkdir(exist_ok=True)
    (out / 'source_snippets.txt').write_text('\n'.join(out_lines), encoding='utf-8')
    print(f'Wrote {len(out_lines)} lines')


if __name__ == '__main__':
    main()
