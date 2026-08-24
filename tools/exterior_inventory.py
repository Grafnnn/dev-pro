from __future__ import annotations

import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests
import trimesh
from pygltflib import GLTF2


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with target.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def classify(name: str) -> str:
    rules = [
        ('helper', r'QA_|CLEARANCE|CENTERLINE|AXIS|HELPER|GUIDE|CLASH|DEBUG|TEMP|BOUNDARY|CONTOUR|PR_EW_LINE|RFI|ZONE'),
        ('road', r'^D\d|ROAD|DRIVE|SERP|LOOP|ACCESS|ENTRY|FIRE_ROUTE|PAVEMENT|ASPHALT|ДОРОГ|ПРОЕЗД|СЕРПАНТ|ВЪЕЗД|ВЫЕЗД'),
        ('terrain', r'TERRAIN|GROUND|RELIEF|LAND|SLOPE|EARTH|РЕЛЬЕФ|ЗЕМЛ|ОТКОС'),
        ('terrace', r'TERRACE|PLATFORM|PAD|APRON|ПЛОЩАД|ТЕРРАС'),
        ('wall', r'RETAINING|WALL|GABION|ПОДПОР|СТЕН'),
        ('utility', r'^NET_|PIPE|UTILITY|DUCT|CABLE|WATER|SEWER|DRAIN|GAS|OIL|CW_|FW_|W1_|K1_|K2_|LV_|MV_|СЕТЬ|ТРУБ|КАБЕЛ|ВОД|КАНАЛ|ГАЗ|МАСЛ'),
        ('rack', r'RACK|TRESTLE|SUPPORT|PIPEBRIDGE|PIPE_BRIDGE|ЭСТАКАД|ОПОРА'),
        ('building', r'BUILDING|BLDG|HALL|WAREHOUSE|ABK|ADMIN|SHOP|B\d|ЗДАН|ЦЕХ|СКЛАД|АБК'),
        ('foundation', r'FOUNDATION|PILE|GRILLAGE|FOOTING|ANCHOR|ФУНД|СВА'),
        ('tank', r'TANK|RVS|VESSEL|RESERVOIR|РВС|РЕЗЕРВУАР|ЕМКОСТ'),
        ('pond', r'POND|BASIN|LOS|WATERBODY|ПРУД|ЛОС'),
        ('fence', r'FENCE|GATE|BARRIER|GUARDRAIL|RAILING|ОГРАЖ|ВОРОТ|ШЛАГБАУМ'),
        ('lighting', r'LIGHT|LAMP|POLE|CAMERA|CCTV|ОСВЕЩ|ФОНАР|КАМЕР'),
        ('landscape', r'TREE|SHRUB|LANDSCAPE|GREEN|ДЕРЕВ|КУСТ|ОЗЕЛЕН'),
        ('parking', r'PARK|MARKING|STALL|PARKING|СТОЯН|ПАРКОВ'),
        ('equipment', r'^E\d|EQUIP|MACHINE|REACTOR|SHREDDER|MILL|COMPRESSOR|TRANSFORMER|PUMP|EQUIPMENT|ОБОРУД|РЕАКТОР|ДРОБИЛ|НАСОС|ТРАНСФОРМ'),
    ]
    for cat, pattern in rules:
        if re.search(pattern, name, re.I):
            return cat
    return 'other'


def fmt_vec(vec) -> str:
    return '(' + ', '.join(f'{float(v):.3f}' for v in vec) + ')'


def main() -> None:
    url = os.environ['SOURCE_ZIP_URL']
    root = Path('work_inventory')
    root.mkdir(exist_ok=True)
    zpath = root / 'source.zip'
    download(url, zpath)
    extract = root / 'src'
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
        zf.extractall(extract)

    glbs = sorted(extract.rglob('*.glb'), key=lambda p: p.stat().st_size, reverse=True)
    if not glbs:
        raise RuntimeError('No GLB')
    glb = glbs[0]
    scene = trimesh.load(str(glb), force='scene', process=False)
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)

    grouped = defaultdict(list)
    for name, geom in scene.geometry.items():
        grouped[classify(name)].append({
            'name': name,
            'bounds': np.asarray(geom.bounds, float),
            'extents': np.asarray(geom.extents, float),
            'faces': len(getattr(geom, 'faces', [])),
            'vertices': len(getattr(geom, 'vertices', [])),
            'volume': float(abs(getattr(geom, 'volume', 0.0))),
        })

    gltf = GLTF2().load_binary(str(glb))
    node_rows = []
    for i, node in enumerate(gltf.nodes or []):
        if node.extras:
            node_rows.append((i, node.name or '', node.mesh, node.extras))

    out = Path('audit')
    out.mkdir(exist_ok=True)
    lines = []
    lines.append('# A1 LOD400-P exterior model inventory')
    lines.append('')
    lines.append(f'- Source GLB: `{glb.name}`')
    lines.append(f'- Scene bounds: {fmt_vec(scene.bounds[0])} — {fmt_vec(scene.bounds[1])}')
    lines.append(f'- Scene extents: {fmt_vec(scene.extents)}')
    lines.append(f'- Geometry count: {len(scene.geometry)}')
    lines.append(f'- Nodes with extras: {len(node_rows)}')
    lines.append('')
    lines.append('## ZIP contents')
    for n in names:
        lines.append(f'- `{n}`')
    lines.append('')

    order = ['helper','road','terrain','terrace','wall','utility','rack','building','foundation','tank','pond','fence','lighting','landscape','parking','equipment','other']
    for cat in order:
        items = grouped.get(cat, [])
        items.sort(key=lambda x: (-x['volume'], -x['faces'], x['name']))
        lines.append(f'## {cat} ({len(items)})')
        limit = len(items) if cat != 'other' else min(300, len(items))
        for item in items[:limit]:
            lines.append(
                f"- `{item['name']}` | ext={fmt_vec(item['extents'])} | "
                f"min={fmt_vec(item['bounds'][0])} | max={fmt_vec(item['bounds'][1])} | "
                f"v={item['vertices']} f={item['faces']} vol={item['volume']:.3f}"
            )
        if len(items) > limit:
            lines.append(f'- … {len(items)-limit} more omitted')
        lines.append('')

    lines.append('## Nodes with BIM extras')
    for i, name, mesh, extras in node_rows[:500]:
        lines.append(f'- node {i}, mesh={mesh}, `{name}`: `{json.dumps(extras, ensure_ascii=False, sort_keys=True)}`')
    if len(node_rows) > 500:
        lines.append(f'- … {len(node_rows)-500} more omitted')

    (out / 'exterior_inventory.md').write_text('\n'.join(lines), encoding='utf-8')
    (out / 'exterior_inventory.json').write_text(json.dumps({
        'source': glb.name,
        'scene_bounds': np.asarray(scene.bounds).tolist(),
        'scene_extents': np.asarray(scene.extents).tolist(),
        'zip_entries': names,
        'groups': {cat: [
            {
                'name': x['name'],
                'bounds': x['bounds'].tolist(),
                'extents': x['extents'].tolist(),
                'faces': x['faces'],
                'vertices': x['vertices'],
                'volume': x['volume'],
            } for x in items
        ] for cat, items in grouped.items()},
        'nodes_with_extras': [
            {'index': i, 'name': name, 'mesh': mesh, 'extras': extras}
            for i, name, mesh, extras in node_rows
        ],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('INVENTORY_DONE')


if __name__ == '__main__':
    main()
