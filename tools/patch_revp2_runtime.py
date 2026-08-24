from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f'Patch target not found: {label}')
    return text.replace(old, new, 1)


def patch_build() -> None:
    p = Path('tools/build_revp2_exterior.py')
    s = p.read_text(encoding='utf-8')

    s = replace_once(
        s,
        'ROAD_SMOOTH_ITERS = {"D1": 1, "D2": 2, "D3": 3, "D4": 1, "D5": 2, "D6": 1}',
        'ROAD_SMOOTH_ITERS = {"D1": 2, "D2": 3, "D3": 5, "D4": 2, "D5": 3, "D6": 3}',
        'road smoothing iterations',
    )

    old = '''def smooth_road_centerline(raw: np.ndarray, road_code: str) -> np.ndarray:\n    raw = np.asarray(raw, float)\n    z0, z1 = float(raw[0, 2]), float(raw[-1, 2])\n    sm = chaikin(raw, ROAD_SMOOTH_ITERS[road_code])\n    sm = resample_polyline(sm, ROAD_SPACING[road_code])\n    st = cumulative_xy(sm)\n    raw_s = cumulative_xy(raw)\n    base_z = np.interp(st / max(st[-1], 1e-6), raw_s / max(raw_s[-1], 1e-6), raw[:, 2])\n'''
    new = '''def smooth_road_centerline(raw: np.ndarray, road_code: str) -> np.ndarray:\n    raw = np.asarray(raw, float)\n    z0, z1 = float(raw[0, 2]), float(raw[-1, 2])\n    # Remove inherited centimetre-scale oscillation and redundant vertices before\n    # curve refinement.  This is the key correction for the previously faceted\n    # road ribbons and unrealistic switchback radii.\n    tolerance = {"D1": 0.75, "D2": 1.50, "D3": 3.25, "D4": 0.75, "D5": 1.50, "D6": 1.25}[road_code]\n    original = raw.copy()\n    original_s = cumulative_xy(original)\n    original_line = LineString(original[:, :2])\n    simplified_xy = np.asarray(original_line.simplify(tolerance, preserve_topology=False).coords, dtype=float)\n    simplified_station = np.asarray([original_line.project(Point(float(x), float(y))) for x, y in simplified_xy])\n    simplified_z = np.interp(simplified_station, original_s, original[:, 2])\n    raw = np.column_stack([simplified_xy, simplified_z])\n    sm = chaikin(raw, ROAD_SMOOTH_ITERS[road_code])\n    sm = resample_polyline(sm, ROAD_SPACING[road_code])\n    st = cumulative_xy(sm)\n    raw_s = cumulative_xy(raw)\n    base_z = np.interp(st / max(st[-1], 1e-6), raw_s / max(raw_s[-1], 1e-6), raw[:, 2])\n'''
    s = replace_once(s, old, new, 'smooth road centerline')

    s = replace_once(
        s,
        "        'min_radius_p05_m':min_horizontal_radius(centerline),",
        "        'min_radius_p05_m':min_horizontal_radius(resample_polyline(centerline, 5.0)),",
        'road radius QA sampling',
    )

    insert_after = '''def filter_components(mesh: trimesh.Trimesh, exclusion, gate_zones=None) -> tuple[trimesh.Trimesh, int]:\n    comps=mesh.split(only_watertight=False)\n    kept=[]; removed=0\n    for c in comps:\n        p=Point(float(c.centroid[0]),float(c.centroid[1]))\n        if exclusion is not None and exclusion.contains(p):\n            removed+=1; continue\n        if gate_zones is not None and gate_zones.contains(p):\n            removed+=1; continue\n        kept.append(c)\n    if not kept:\n        return mesh.copy(),0\n    return trimesh.util.concatenate(kept),removed\n\n\n'''
    addition = insert_after + '''def filter_faces_by_zone(mesh: trimesh.Trimesh, zone) -> tuple[trimesh.Trimesh, int]:\n    \"\"\"Remove fence/linear faces inside gate openings even if the mesh is connected.\"\"\"\n    out = mesh.copy()\n    centers = np.asarray(out.triangles_center, dtype=float)\n    remove = np.asarray([zone.contains(Point(float(x), float(y))) for x, y in centers[:, :2]], dtype=bool)\n    if np.any(remove):\n        out.update_faces(~remove)\n        out.remove_unreferenced_vertices()\n    return out, int(np.count_nonzero(remove))\n\n\n'''
    s = replace_once(s, insert_after, addition, 'face-zone filter')

    s = replace_once(
        s,
        "        elif name=='SITE_PERIMETER_FENCE':\n            mesh,fence_removed=filter_components(mesh,None,gate_zone)\n            out_name='SITE_PERIMETER_FENCE_WITH_GATES'",
        "        elif name=='SITE_PERIMETER_FENCE':\n            mesh,fence_removed=filter_faces_by_zone(mesh,gate_zone)\n            out_name='SITE_PERIMETER_FENCE_WITH_GATES'",
        'fence gate openings',
    )

    old = '''    building_footprints=[]\n    for name,g in source.geometry.items():\n        if re.match(r'BLD_.*_FOUNDATION_DECK$',name,re.I):\n            b=np.asarray(g.bounds,float); building_footprints.append((name,sbox(b[0,0],b[0,1],b[1,0],b[1,1])))\n'''
    new = '''    # Check carriageways against the actual vertical building envelope, not the\n    # oversized foundation/service decks.  The earlier deck-based test produced\n    # false positives exactly where loading aprons intentionally overlap roads.\n    building_groups=defaultdict(list)\n    excluded_tokens=('FOUNDATION','PILE','ROOF','CANOPY','APRON','STAIR','RAILING','GUTTER','DOWNPIPE','DOOR','WINDOW','LOUVER','SERVICE','ANCHOR')\n    preferred_tokens=('CLADDING','WALL','ENVELOPE','BODY')\n    for name,g in source.geometry.items():\n        match=re.match(r'(BLD_[0-9]+[A-Z]?)_',name,re.I)\n        if not match or any(token in name.upper() for token in excluded_tokens):\n            continue\n        b=np.asarray(g.bounds,float); e=np.asarray(g.extents,float)\n        if e[2] < 2.5 or e[0]*e[1] < 8.0:\n            continue\n        priority=1 if any(token in name.upper() for token in preferred_tokens) else 0\n        building_groups[match.group(1)].append((priority,float(e[0]*e[1]),name,b))\n    building_footprints=[]\n    for code,items in building_groups.items():\n        items.sort(key=lambda item:(item[0],item[1]),reverse=True)\n        _,_,name,b=items[0]\n        building_footprints.append((name,sbox(b[0,0],b[0,1],b[1,0],b[1,1])))\n'''
    s = replace_once(s, old, new, 'actual building envelope QA')

    s = replace_once(
        s,
        "    if road_building_clashes:\n        log('WARNING: residual road/building footprint intersections found: '+json.dumps(road_building_clashes,ensure_ascii=False))",
        "    if road_building_clashes:\n        raise RuntimeError('Residual road/building envelope intersections: '+json.dumps(road_building_clashes,ensure_ascii=False))",
        'hard fail genuine external clashes',
    )

    p.write_text(s, encoding='utf-8')


def patch_render() -> None:
    p = Path('tools/render_revp2_blender.py')
    s = p.read_text(encoding='utf-8')
    s = replace_once(
        s,
        "    scene.world.color = (0.82, 0.88, 0.94)",
        "    if scene.world is None:\n        scene.world = bpy.data.worlds.new('QA_WORLD')\n    scene.world.color = (0.82, 0.88, 0.94)",
        'Blender world creation',
    )
    p.write_text(s, encoding='utf-8')


if __name__ == '__main__':
    patch_build()
    patch_render()
    print('REV_P2_RUNTIME_PATCHED')
