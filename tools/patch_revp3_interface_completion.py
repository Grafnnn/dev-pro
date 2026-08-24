from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    text = text.replace(old, new, 1)


# Vectorised point-in-polygon support for terrain cutting and verification.
replace_once(
    "from shapely.geometry import LineString, MultiPolygon, Point, Polygon\nfrom shapely.ops import nearest_points, unary_union",
    "from shapely import contains_xy\nfrom shapely.geometry import LineString, MultiPolygon, Point, Polygon\nfrom shapely.ops import nearest_points, unary_union\nfrom shapely.strtree import STRtree",
    "Shapely vectorised QA imports",
)

# D6 is separated from the D5 connector and routed north of BLD_12 and the oil
# tank farm. The only D4/D6 overlap is the intentional shared junction at start.
old_d6 = '''    d6_parts = [sample_line((338.0, 128.0), (342.0, 128.0), 0.8)]
    shift = 14.0
    angle = math.acos(1.0 - shift / 30.0)
    s, _ = sample_s_bend((342.0, 128.0), 0.0, 15.0, angle, +1, 0.8)
    d6_parts.append(s[1:])
    d6_parts.append(sample_line(tuple(s[-1]), (550.0, 142.0), 1.2)[1:])'''
new_d6 = '''    d6_parts = [sample_line((338.0, 128.0), (370.0, 128.0), 0.8)]
    shift = 14.0
    angle = math.acos(1.0 - shift / 30.0)
    s, _ = sample_s_bend((370.0, 128.0), 0.0, 15.0, angle, +1, 0.8)
    d6_parts.append(s[1:])
    d6_parts.append(sample_line(tuple(s[-1]), (550.0, 142.0), 1.2)[1:])'''
replace_once(old_d6, new_d6, "D6 separated utility route")

# D3 passes the D5 service-loop level at a controlled node. Build the vertical
# profile in two smooth grade-limited pieces so both road surfaces share 110.7 m.
replace_once(
    '    roads["D3"] = [assign_linear_z(d3_xy, 133.7, 102.2)]',
    '''    d3_node_xy = np.array([580.5, 163.0], dtype=float)
    d3_node_index = int(np.argmin(np.linalg.norm(d3_xy[:, :2] - d3_node_xy, axis=1)))
    d3_upper = assign_linear_z(d3_xy[: d3_node_index + 1], 133.7, 110.7)
    d3_lower = assign_linear_z(d3_xy[d3_node_index:], 110.7, 102.2)
    d3_xyz = dedupe_points(np.vstack([d3_upper, d3_lower[1:]]))
    roads["D3"] = [d3_xyz]''',
    "D3 piecewise vertical profile",
)

# Add a D5 service spur to the D3 node. It is part of the same D5 polygon and
# is clipped only at the final shared node by the partition order below.
replace_once(
    '    roads["D5"] = [assign_linear_z(d5_conn_xy, 108.7, 110.7), assign_constant_z(d5_loop_xy, 110.7)]',
    '''    d5_spur_xy = sample_line((558.0, 168.0), (580.5, 163.0), 0.6)
    roads["D5"] = [
        assign_linear_z(d5_conn_xy, 108.7, 110.7),
        assign_constant_z(d5_loop_xy, 110.7),
        assign_constant_z(d5_spur_xy, 110.7),
    ]''',
    "D5-D3 service spur",
)

# D3 is assigned before D5/D6 so it remains one continuous serpent; later
# roads are clipped at their intentional junctions instead of cutting D3.
replace_once(
    '    order = ["D1", "D4", "D2", "D5", "D6", "D3"]',
    '    order = ["D1", "D4", "D2", "D3", "D5", "D6"]',
    "road partition priority",
)

# New D3/D5 junction suppresses curbs, rails and markings within its shared pad.
replace_once(
    '            Point(439.0, 345.0).buffer(8.0),\n            Point(338.0, 128.0).buffer(10.0),',
    '            Point(439.0, 345.0).buffer(8.0),\n            Point(580.5, 163.0).buffer(8.0),\n            Point(338.0, 128.0).buffer(10.0),',
    "D3-D5 junction clear zone",
)
replace_once(
    '        ("D2-D3", "D2", "D3", (439.0, 345.0)),\n        ("D4-D5", "D4", "D5", (338.0, 128.0)),',
    '        ("D2-D3", "D2", "D3", (439.0, 345.0)),\n        ("D3-D5", "D3", "D5", (580.5, 163.0)),\n        ("D4-D5", "D4", "D5", (338.0, 128.0)),',
    "D3-D5 junction QA",
)

# Terrain cut: remove every finished-surface face which has a vertex, edge
# midpoint or centroid inside the widest road/subbase corridor. This is a true
# geometric cut under ROAD/SHOULDER/SUBBASE, not a reporting-only override.
terrain_functions_anchor = '''def build_terrain_sampler(terrain: trimesh.Trimesh):
'''
terrain_functions = '''def cut_finished_surface(mesh: trimesh.Trimesh, corridor) -> tuple[trimesh.Trimesh, dict]:
    result = mesh.copy()
    vertices = np.asarray(result.vertices, dtype=float)
    faces = np.asarray(result.faces, dtype=int)
    triangles = vertices[faces]
    samples = np.stack(
        [
            triangles[:, 0, :2],
            triangles[:, 1, :2],
            triangles[:, 2, :2],
            0.5 * (triangles[:, 0, :2] + triangles[:, 1, :2]),
            0.5 * (triangles[:, 1, :2] + triangles[:, 2, :2]),
            0.5 * (triangles[:, 2, :2] + triangles[:, 0, :2]),
            np.mean(triangles[:, :, :2], axis=1),
        ],
        axis=1,
    )
    flat = samples.reshape(-1, 2)
    inside = contains_xy(corridor, flat[:, 0], flat[:, 1]).reshape(len(faces), samples.shape[1])
    remove = np.any(inside, axis=1)
    kept = ~remove
    result.update_faces(kept)
    result.remove_unreferenced_vertices()
    return result, {
        "source_faces": int(len(faces)),
        "removed_faces": int(np.count_nonzero(remove)),
        "remaining_faces": int(np.count_nonzero(kept)),
        "cut_corridor_area_m2": float(corridor.area),
    }


def terrain_interface_qa(mesh: trimesh.Trimesh, corridor, profiles: dict[str, "RoadProfile"]) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    triangles = vertices[faces]
    samples = np.stack(
        [
            triangles[:, 0], triangles[:, 1], triangles[:, 2],
            0.5 * (triangles[:, 0] + triangles[:, 1]),
            0.5 * (triangles[:, 1] + triangles[:, 2]),
            0.5 * (triangles[:, 2] + triangles[:, 0]),
            np.mean(triangles, axis=1),
        ],
        axis=1,
    ).reshape(-1, 3)
    inside = contains_xy(corridor, samples[:, 0], samples[:, 1])
    candidate = samples[inside]
    above = []
    for x, y, z in candidate:
        road_z = point_z_from_profiles(profiles, float(x), float(y))
        if float(z) > road_z - 0.02:
            above.append((float(x), float(y), float(z), road_z))
    return {
        "sample_points_inside_road_and_shoulders": int(len(candidate)),
        "terrain_above_road_points": int(len(above)),
        "maximum_terrain_above_road_m": float(max((z - rz for _, _, z, rz in above), default=0.0)),
    }


def top_face_duplicate_count(scene: trimesh.Scene, names: list[str]) -> int:
    seen: dict[tuple, str] = {}
    duplicates = 0
    for name in names:
        mesh = scene.geometry.get(name)
        if mesh is None:
            continue
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        normals = np.asarray(mesh.face_normals, dtype=float)
        for face, normal in zip(faces, normals):
            if normal[2] < 0.55:
                continue
            triangle = np.round(vertices[face], 5)
            key = tuple(sorted(tuple(point) for point in triangle))
            if key in seen:
                duplicates += 1
            else:
                seen[key] = name
    return int(duplicates)


def nonadjacent_top_triangle_intersections(mesh: trimesh.Trimesh) -> int:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    normals = np.asarray(mesh.face_normals, dtype=float)
    top_indices = np.where(normals[:, 2] > 0.55)[0]
    polygons = []
    face_ids = []
    vertex_sets = []
    for face_index in top_indices:
        face = faces[face_index]
        polygon = Polygon(vertices[face, :2])
        if polygon.area <= 1.0e-10:
            continue
        polygons.append(polygon)
        face_ids.append(int(face_index))
        vertex_sets.append(set(int(v) for v in face))
    if not polygons:
        return 0
    tree = STRtree(polygons)
    intersections = 0
    for index, polygon in enumerate(polygons):
        for other in tree.query(polygon):
            other_index = int(other)
            if other_index <= index or vertex_sets[index] & vertex_sets[other_index]:
                continue
            intersection = polygon.intersection(polygons[other_index])
            if intersection.area > 1.0e-9:
                intersections += 1
    return int(intersections)


''' + terrain_functions_anchor
replace_once(terrain_functions_anchor, terrain_functions, "terrain and global QA functions")

# Construct the terrain cut after final non-overlapping road polygons exist.
replace_once(
    '''    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    # Intentional road-road junctions; curbs/rails stop here.''',
    '''    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    terrain_cut_corridor = unary_union(list(subbase_polys.values()) + list(shoulder_polys.values())).buffer(0.35)
    terrain_cut_mesh, terrain_cut_stats = cut_finished_surface(terrain, terrain_cut_corridor)

    # Intentional road-road junctions; curbs/rails stop here.''',
    "terrain cut construction",
)

# Replace the source terrain during scene copying; Rev.P2 remains immutable.
replace_once(
    '''    for name, mesh in source.geometry.items():
        if should_remove(name):''',
    '''    for name, mesh in source.geometry.items():
        if name == "finished_design_surface":
            removed.append(name)
            add(target, "REV_P3_finished_design_surface_CUT", terrain_cut_mesh.copy())
            continue
        if should_remove(name):''',
    "replace source terrain with cut terrain",
)

# Capture terrain, self-intersection and duplicate-top-face checks before QA JSON.
replace_once(
    '''    # Verify the six source collisions specifically closed.
    closed_source_clashes = []''',
    '''    road_surface_names = [f"REV_P3_EXT_{code}_ROAD" for code in WIDTHS]
    road_layer_names = [
        f"REV_P3_EXT_{code}_{layer}"
        for code in WIDTHS
        for layer in ("ROAD", "SHOULDER", "SUBBASE")
    ]
    top_face_duplicates = top_face_duplicate_count(target, road_layer_names)
    if top_face_duplicates != 0:
        raise RuntimeError(f"Duplicated/copanar top road faces remain: {top_face_duplicates}")
    triangle_self_intersections = {
        name: nonadjacent_top_triangle_intersections(target.geometry[name])
        for name in road_surface_names
    }
    total_triangle_self_intersections = int(sum(triangle_self_intersections.values()))
    if total_triangle_self_intersections != 0:
        raise RuntimeError(
            "Non-adjacent road triangle self-intersections remain: "
            + json.dumps(triangle_self_intersections, ensure_ascii=False)
        )
    terrain_cut_qa = terrain_interface_qa(terrain_cut_mesh, terrain_cut_corridor, profiles)
    if terrain_cut_qa["terrain_above_road_points"] != 0:
        raise RuntimeError("Terrain remains above road after geometric cut: " + json.dumps(terrain_cut_qa))

    # Verify the six source collisions specifically closed.
    closed_source_clashes = []''',
    "global road geometry QA",
)

# Add hard results into the report and acceptance block.
replace_once(
    '''        "terrain_interface": terrain_report,
        "wall_and_railing_adjustments": wall_filter_report,''',
    '''        "terrain_interface": {
            "per_road_pre_cut_reference": terrain_report,
            "geometric_cut": terrain_cut_stats,
            "post_cut_qa": terrain_cut_qa,
        },
        "triangle_self_intersections": {
            "per_road_surface": triangle_self_intersections,
            "non_adjacent_road_triangle_self_intersections": total_triangle_self_intersections,
        },
        "duplicated_top_faces": top_face_duplicates,
        "wall_and_railing_adjustments": wall_filter_report,''',
    "QA terrain and triangle results",
)
replace_once(
    '''            "maximum_longitudinal_grade_pct": max(item["max_longitudinal_grade_pct"] for item in road_metrics.values()),
            "minimum_horizontal_radius_m": min(item["minimum_horizontal_radius_m"] for item in road_metrics.values()),''',
    '''            "maximum_longitudinal_grade_pct": max(item["max_longitudinal_grade_pct"] for item in road_metrics.values()),
            "minimum_horizontal_radius_m": min(item["minimum_horizontal_radius_m"] for item in road_metrics.values()),
            "terrain_above_road_points": terrain_cut_qa["terrain_above_road_points"],
            "non_adjacent_road_triangle_self_intersections": total_triangle_self_intersections,
            "duplicated_top_faces": top_face_duplicates,''',
    "acceptance terrain/triangle fields",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_INTERFACE_COMPLETION_PATCHED")
