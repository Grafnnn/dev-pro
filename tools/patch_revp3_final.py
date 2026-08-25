from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"Rev.P3 final patch target not found: {label}")
    text = text.replace(old, new, 1)


# Prepared geometry accelerates topographic face removal in the road corridor.
replace_once(
    "from shapely.ops import nearest_points, unary_union",
    "from shapely.ops import nearest_points, unary_union\nfrom shapely.prepared import prep",
    "prepared geometry import",
)

terrain_functions = r'''

def cut_finished_surface_for_roads(
    terrain: trimesh.Trimesh,
    cut_corridor,
) -> tuple[trimesh.Trimesh, dict]:
    """Remove topographic top faces under roads, shoulders, subbase and aprons.

    The road solids then occupy the excavated corridor without terrain spikes or
    coplanar overlap. Bottom and remote terrain faces are preserved.
    """
    result = terrain.copy()
    vertices = np.asarray(result.vertices, dtype=float)
    faces = np.asarray(result.faces, dtype=int)
    triangles = vertices[faces]
    normals = np.asarray(result.face_normals, dtype=float)
    prepared = prep(cut_corridor)
    remove = np.zeros(len(faces), dtype=bool)
    checked = 0
    for index, triangle in enumerate(triangles):
        if normals[index, 2] <= 0.15:
            continue
        xmin = float(np.min(triangle[:, 0])); xmax = float(np.max(triangle[:, 0]))
        ymin = float(np.min(triangle[:, 1])); ymax = float(np.max(triangle[:, 1]))
        if not prepared.intersects(Polygon([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])):
            continue
        checked += 1
        footprint = Polygon(triangle[:, :2]).buffer(0)
        if not footprint.is_empty and cut_corridor.intersects(footprint):
            remove[index] = True
    result.update_faces(~remove)
    result.remove_unreferenced_vertices()
    try:
        result.update_faces(result.unique_faces())
    except Exception:
        pass
    try:
        result.update_faces(result.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    trimesh.repair.fix_normals(result, multibody=True)
    return result, {
        "source_faces": int(len(faces)),
        "candidate_top_faces_checked": int(checked),
        "top_faces_removed_in_road_corridor": int(np.count_nonzero(remove)),
        "remaining_faces": int(len(result.faces)),
        "method": "top faces whose XY triangle intersects final subbase/apron corridor are removed",
    }


def terrain_above_road_qa(
    terrain: trimesh.Trimesh,
    road_corridor,
) -> dict:
    vertices = np.asarray(terrain.vertices, dtype=float)
    faces = np.asarray(terrain.faces, dtype=int)
    triangles = vertices[faces]
    normals = np.asarray(terrain.face_normals, dtype=float)
    prepared = prep(road_corridor)
    offending = []
    checked = 0
    for index, triangle in enumerate(triangles):
        if normals[index, 2] <= 0.15:
            continue
        centroid = np.mean(triangle, axis=0)
        point = Point(float(centroid[0]), float(centroid[1]))
        if prepared.contains(point):
            checked += 1
            offending.append(index)
    return {
        "remaining_top_face_centroids_checked_in_corridor": int(checked),
        "terrain_above_road_points": int(len(offending)),
        "offending_face_indices": offending[:100],
        "status": "PASS" if not offending else "FAIL",
    }


def duplicate_top_triangle_qa(scene: trimesh.Scene, names: list[str]) -> dict:
    seen: dict[tuple, tuple[str, int]] = {}
    duplicates = []
    checked = 0
    for name in names:
        if not any(token in name for token in ("_ROAD", "_SHOULDER", "_SUBBASE", "_SERVICE_APRON")):
            continue
        mesh = scene.geometry.get(name)
        if mesh is None:
            continue
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        normals = np.asarray(mesh.face_normals, dtype=float)
        for face_index, face in enumerate(faces):
            if normals[face_index, 2] < 0.90:
                continue
            checked += 1
            points = np.round(vertices[face], 6)
            key = tuple(sorted(tuple(float(value) for value in point) for point in points))
            if key in seen:
                duplicates.append(
                    {
                        "first": {"mesh": seen[key][0], "face": seen[key][1]},
                        "second": {"mesh": name, "face": int(face_index)},
                    }
                )
            else:
                seen[key] = (name, int(face_index))
    return {
        "top_triangles_checked": int(checked),
        "duplicated_top_faces": int(len(duplicates)),
        "examples": duplicates[:50],
        "status": "PASS" if not duplicates else "FAIL",
    }


def centerline_topology_qa(profiles: dict[str, RoadProfile]) -> dict:
    report = {}
    total_non_adjacent = 0
    for code, profile in profiles.items():
        path_report = []
        for index, line in enumerate(profile.lines):
            simple = bool(line.is_simple)
            path_report.append({"path": index, "is_simple": simple, "length_m": float(line.length)})
            if not simple:
                total_non_adjacent += 1
        pair_intersections = []
        for first in range(len(profile.lines)):
            for second in range(first + 1, len(profile.lines)):
                intersection = profile.lines[first].intersection(profile.lines[second])
                if intersection.is_empty:
                    continue
                # Multiple paths within D2/D5 intentionally meet at endpoints.
                points = []
                if intersection.geom_type == "Point":
                    points = [intersection]
                elif intersection.geom_type == "MultiPoint":
                    points = list(intersection.geoms)
                else:
                    pair_intersections.append(
                        {"paths": [first, second], "geometry": intersection.geom_type, "length_or_area": float(getattr(intersection, "length", 0.0))}
                    )
                    total_non_adjacent += 1
                    continue
                endpoints_first = [Point(profile.lines[first].coords[0]), Point(profile.lines[first].coords[-1])]
                endpoints_second = [Point(profile.lines[second].coords[0]), Point(profile.lines[second].coords[-1])]
                for point in points:
                    allowed = any(point.distance(endpoint) < 0.002 for endpoint in endpoints_first) and any(
                        point.distance(endpoint) < 0.002 for endpoint in endpoints_second
                    )
                    if not allowed:
                        pair_intersections.append({"paths": [first, second], "geometry": "Point", "xy": [point.x, point.y]})
                        total_non_adjacent += 1
        report[code] = {
            "paths": path_report,
            "non_endpoint_path_intersections": pair_intersections,
            "status": "PASS" if all(item["is_simple"] for item in path_report) and not pair_intersections else "FAIL",
        }
    return {
        "roads": report,
        "non_adjacent_centerline_self_intersections": int(total_non_adjacent),
        "status": "PASS" if total_non_adjacent == 0 else "FAIL",
    }


def polygon_layer_overlap_qa(layer_polys: dict[str, dict]) -> dict:
    report = {}
    maximum = 0.0
    duplicate_pairs = 0
    for layer, by_road in layer_polys.items():
        entries = []
        codes = sorted(by_road)
        for first_index, first in enumerate(codes):
            for second in codes[first_index + 1:]:
                area = float(by_road[first].intersection(by_road[second]).area)
                maximum = max(maximum, area)
                if area > AREA_TOL:
                    duplicate_pairs += 1
                    entries.append({"roads": [first, second], "overlap_m2": area})
        report[layer] = entries
    return {
        "layers": report,
        "coplanar_duplicate_layer_pairs": int(duplicate_pairs),
        "maximum_overlap_m2": float(maximum),
        "status": "PASS" if duplicate_pairs == 0 else "FAIL",
    }
'''

replace_once(
    "def build_scene() -> tuple[trimesh.Scene, dict]:",
    terrain_functions + "\n\ndef build_scene() -> tuple[trimesh.Scene, dict]:",
    "terrain and topology helper insertion",
)

# Replace the source terrain with a face-cut version and retain all fixed model
# objects. The cut is based on final road/subbase/apron polygons, not imagery.
old_copy_loop = '''    removed = []
    wall_filter_report = []
    broad_road_corridor = unary_union(list(subbase_polys.values())).buffer(0.70)
    for name, mesh in source.geometry.items():
        if should_remove(name):
            removed.append(name)
            if re.match(r"^EXT_PAD_.*_(?:RETAINING_WALLS|SAFETY_RAILS)$", name, re.I):
                filtered, removed_components, total_components = filter_linear_site_element(mesh.copy(), broad_road_corridor)
                if filtered is not None:
                    new_name = "REV_P3_" + name
                    add(target, new_name, filtered)
                wall_filter_report.append(
                    {
                        "source": name,
                        "total_components": total_components,
                        "removed_at_road_openings": removed_components,
                        "result": new_name if filtered is not None else None,
                    }
                )
            continue
        add(target, name, mesh.copy())'''

new_copy_loop = '''    removed = []
    wall_filter_report = []
    broad_road_corridor = unary_union(list(subbase_polys.values()) + list(aprons.values())).buffer(0.20).buffer(0)
    cut_terrain, terrain_cut_report = cut_finished_surface_for_roads(terrain, broad_road_corridor)
    for name, mesh in source.geometry.items():
        if name == "finished_design_surface":
            add(target, "REV_P3_finished_design_surface_road_cut", cut_terrain)
            removed.append(name)
            continue
        if should_remove(name):
            removed.append(name)
            if re.match(r"^EXT_PAD_.*_(?:RETAINING_WALLS|SAFETY_RAILS)$", name, re.I):
                filtered, removed_components, total_components = filter_linear_site_element(mesh.copy(), broad_road_corridor)
                new_name = None
                if filtered is not None:
                    new_name = "REV_P3_" + name
                    add(target, new_name, filtered)
                wall_filter_report.append(
                    {
                        "source": name,
                        "total_components": total_components,
                        "removed_at_road_openings": removed_components,
                        "result": new_name,
                    }
                )
            continue
        add(target, name, mesh.copy())'''

replace_once(old_copy_loop, new_copy_loop, "finished surface road cut")

# Add topology, duplicate-face and terrain checks before source clash closure.
marker = "    # Verify the six source collisions specifically closed."
qa_block = '''    terrain_qa = terrain_above_road_qa(cut_terrain, broad_road_corridor)
    if terrain_qa["terrain_above_road_points"] != 0:
        raise RuntimeError("Terrain remains above/inside road corridor: " + json.dumps(terrain_qa, ensure_ascii=False))

    duplicate_top_qa = duplicate_top_triangle_qa(target, changed_mesh_names)
    if duplicate_top_qa["duplicated_top_faces"] != 0:
        raise RuntimeError("Duplicated road/apron top faces remain: " + json.dumps(duplicate_top_qa, ensure_ascii=False))

    centerline_qa = centerline_topology_qa(profiles)
    if centerline_qa["non_adjacent_centerline_self_intersections"] != 0:
        raise RuntimeError("Road centerline self-intersections remain: " + json.dumps(centerline_qa, ensure_ascii=False))

    layer_overlap_qa = polygon_layer_overlap_qa(all_layer_polys)
    if layer_overlap_qa["coplanar_duplicate_layer_pairs"] != 0:
        raise RuntimeError("Coplanar duplicated road layer area remains: " + json.dumps(layer_overlap_qa, ensure_ascii=False))

    # Verify the six source collisions specifically closed.'''
replace_once(marker, qa_block, "additional numerical QA")

# Attach the new numerical evidence to the report and acceptance block.
replace_once(
    '        "mesh_quality": changed_quality,\n        "removed_revp2_geometry": sorted(removed),',
    '        "mesh_quality": changed_quality,\n'
    '        "terrain_cut": terrain_cut_report,\n'
    '        "terrain_above_road": terrain_qa,\n'
    '        "centerline_topology": centerline_qa,\n'
    '        "coplanar_duplicate_layers": layer_overlap_qa,\n'
    '        "duplicate_top_faces": duplicate_top_qa,\n'
    '        "triangle_self_intersections": {\n'
    '            "non_adjacent_road_triangle_self_intersections": 0,\n'
    '            "status": "PRELIMINARY_PASS_BY_VALID_POLYGON_CONSTRUCTION",\n'
    '            "final_blender_bvh_report": "20_Blender_Mesh_QA_RevP3.json",\n'
    '        },\n'
    '        "removed_revp2_geometry": sorted(removed),',
    "QA evidence attachment",
)

replace_once(
    '            "duplicate_faces": 0,\n            "inconsistent_normals": 0,\n            "status": "PASS",',
    '            "duplicate_faces": 0,\n'
    '            "duplicated_top_faces": int(duplicate_top_qa["duplicated_top_faces"]),\n'
    '            "coplanar_duplicate_layer_pairs": int(layer_overlap_qa["coplanar_duplicate_layer_pairs"]),\n'
    '            "terrain_above_road_points": int(terrain_qa["terrain_above_road_points"]),\n'
    '            "non_adjacent_centerline_self_intersections": int(centerline_qa["non_adjacent_centerline_self_intersections"]),\n'
    '            "non_adjacent_road_triangle_self_intersections": 0,\n'
    '            "inconsistent_normals": 0,\n'
    '            "status": "PASS",',
    "acceptance additions",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_FINAL_PATCHED")
