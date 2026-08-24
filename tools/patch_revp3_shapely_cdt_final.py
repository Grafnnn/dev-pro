from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P3 solid function not found for Shapely CDT patch")

replacement = r'''def _split_disconnected_vertex_fans(
    vertices: np.ndarray,
    faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Split coincident but topologically disconnected triangle fans.

    Boolean subtraction of an apron can leave two boundary cycles touching at a
    single coordinate.  A coordinate-only vertex merge then creates one vertical
    edge used four times after extrusion.  Each disconnected incident-face fan
    receives its own vertex index while retaining the exact same XY coordinate.
    """
    vertices_out = np.asarray(vertices, dtype=float).tolist()
    faces_out = np.asarray(faces, dtype=int).copy()
    split_report: list[dict] = []
    original_vertex_count = len(vertices_out)

    for vertex_index in range(original_vertex_count):
        incident = [
            int(face_index)
            for face_index in np.where(np.any(faces_out == vertex_index, axis=1))[0]
        ]
        if len(incident) <= 1:
            continue

        adjacency: dict[int, set[int]] = {face_index: set() for face_index in incident}
        by_other_vertex: dict[int, list[int]] = {}
        for face_index in incident:
            face = faces_out[face_index]
            for other in face:
                other = int(other)
                if other == vertex_index:
                    continue
                by_other_vertex.setdefault(other, []).append(face_index)
        for face_indices in by_other_vertex.values():
            for first in face_indices:
                adjacency[first].update(second for second in face_indices if second != first)

        remaining = set(incident)
        components: list[list[int]] = []
        while remaining:
            seed = remaining.pop()
            stack = [seed]
            component_faces = [seed]
            while stack:
                current = stack.pop()
                for neighbour in adjacency[current]:
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        stack.append(neighbour)
                        component_faces.append(neighbour)
            components.append(sorted(component_faces))

        if len(components) <= 1:
            continue
        components.sort(key=len, reverse=True)
        created = []
        for component_faces in components[1:]:
            replacement_index = len(vertices_out)
            vertices_out.append(list(vertices_out[vertex_index]))
            created.append(replacement_index)
            for face_index in component_faces:
                locations = np.where(faces_out[face_index] == vertex_index)[0]
                faces_out[face_index, locations] = replacement_index
        split_report.append(
            {
                "source_vertex": int(vertex_index),
                "xy": [float(value) for value in vertices_out[vertex_index]],
                "fan_count": int(len(components)),
                "created_vertices": created,
            }
        )

    return np.asarray(vertices_out, dtype=float), faces_out, split_report


def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """Build a closed warped solid from Shapely constrained Delaunay faces."""
    import shapely

    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    try:
        component = component.segmentize(max(0.35, float(max_edge) * 0.80))
    except Exception:
        pass
    component = component.buffer(0)
    if component.is_empty or not component.is_valid:
        raise RuntimeError("Road polygon became invalid during boundary segmentizing")

    bounds_text = tuple(round(value, 4) for value in component.bounds)
    print(
        f"CDT_SOLID_START area={component.area:.6f} bounds={bounds_text} "
        f"holes={len(component.interiors)} thickness={thickness:.3f}",
        flush=True,
    )

    collection = shapely.constrained_delaunay_triangles(component)
    triangle_geometries = [
        geom for geom in getattr(collection, "geoms", [])
        if isinstance(geom, Polygon) and geom.area > 1.0e-12
    ]
    if not triangle_geometries:
        raise RuntimeError("Shapely constrained Delaunay returned no triangles")

    vertex_lookup: dict[tuple[float, float], int] = {}
    vertex_rows: list[list[float]] = []
    face_rows: list[list[int]] = []
    for triangle in triangle_geometries:
        coordinates = list(triangle.exterior.coords)[:-1]
        if len(coordinates) != 3:
            raise RuntimeError(
                f"Constrained Delaunay returned non-triangle face with {len(coordinates)} vertices"
            )
        face: list[int] = []
        for x, y in coordinates:
            key = (round(float(x), 10), round(float(y), 10))
            index = vertex_lookup.get(key)
            if index is None:
                index = len(vertex_rows)
                vertex_lookup[key] = index
                vertex_rows.append([float(x), float(y)])
            face.append(index)
        if len(set(face)) != 3:
            continue
        face_rows.append(face)

    vertices_2d = np.asarray(vertex_rows, dtype=float)
    faces_2d = np.asarray(face_rows, dtype=int)
    if len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Indexed CDT contains no usable triangulation")

    union = unary_union(triangle_geometries)
    missing_area = float(component.difference(union).area)
    excess_area = float(union.difference(component).area)
    if missing_area > 1.0e-6 or excess_area > 1.0e-6:
        raise RuntimeError(
            "CDT does not reproduce road polygon: "
            f"missing={missing_area:.9f} m2 excess={excess_area:.9f} m2"
        )

    signed = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
    valid = np.abs(signed) > 1.0e-12
    faces_2d = faces_2d[valid]
    signed = signed[valid]
    if len(faces_2d) < 1:
        raise RuntimeError("CDT top triangulation contains only zero-area faces")
    reverse = signed < 0.0
    if np.any(reverse):
        faces_2d[reverse] = faces_2d[reverse][:, ::-1]

    vertices_2d, faces_2d, fan_splits = _split_disconnected_vertex_fans(
        vertices_2d,
        faces_2d,
    )
    if fan_splits:
        print(
            "CDT_VERTEX_FANS_SPLIT " + json.dumps(fan_splits, ensure_ascii=False),
            flush=True,
        )

    # A conforming planar manifold may have boundary edges once and interior
    # edges twice, but never an edge used more than twice.  Each boundary cycle
    # must have degree two after splitting all pinched point contacts.
    planar_edges = np.sort(
        np.vstack(
            [faces_2d[:, [0, 1]], faces_2d[:, [1, 2]], faces_2d[:, [2, 0]]]
        ),
        axis=1,
    )
    unique_planar, planar_counts = np.unique(planar_edges, axis=0, return_counts=True)
    if np.any(planar_counts > 2):
        raise RuntimeError(
            f"CDT planar complex has {int(np.count_nonzero(planar_counts > 2))} non-manifold edges"
        )
    boundary_planar = unique_planar[planar_counts == 1]
    boundary_degree: dict[int, int] = {}
    for a, b in boundary_planar:
        boundary_degree[int(a)] = boundary_degree.get(int(a), 0) + 1
        boundary_degree[int(b)] = boundary_degree.get(int(b), 0) + 1
    bad_boundary_vertices = {
        vertex: degree for vertex, degree in boundary_degree.items() if degree != 2
    }
    if bad_boundary_vertices:
        raise RuntimeError(
            "CDT boundary remains pinched/open after fan split: "
            + json.dumps(bad_boundary_vertices, ensure_ascii=False)
        )

    vertices_2d, faces_2d = _refine_triangulation_conforming(
        vertices_2d,
        faces_2d,
        max_edge=float(max_edge),
        max_iterations=14,
    )
    print(
        f"CDT_PLAN_DONE vertices={len(vertices_2d)} faces={len(faces_2d)}",
        flush=True,
    )

    boundary_edges = _oriented_boundary_edges(faces_2d)
    top_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices_2d],
        dtype=float,
    )
    if not np.isfinite(top_z).all():
        raise RuntimeError("Road profile returned non-finite elevations")
    top_vertices = np.column_stack([vertices_2d, top_z])
    bottom_vertices = np.column_stack(
        [vertices_2d, top_z - float(thickness)]
    )
    count = len(top_vertices)
    vertices = np.vstack([top_vertices, bottom_vertices])

    top_faces = faces_2d.copy()
    bottom_faces = faces_2d[:, ::-1] + count
    side_faces = np.empty((len(boundary_edges) * 2, 3), dtype=int)
    for index, (a, b) in enumerate(boundary_edges):
        a = int(a)
        b = int(b)
        side_faces[2 * index] = [a, a + count, b + count]
        side_faces[2 * index + 1] = [a, b + count, b]
    faces = np.vstack([top_faces, bottom_faces, side_faces])

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    bad_edge_count = int(np.count_nonzero(edge_counts != 2))
    if bad_edge_count != 0 or not mesh.is_watertight:
        values, frequencies = np.unique(edge_counts[edge_counts != 2], return_counts=True)
        distribution = {int(v): int(n) for v, n in zip(values, frequencies)}
        raise RuntimeError(
            "Shapely-CDT road solid is not watertight: "
            f"bad edges={bad_edge_count}; count distribution={distribution}; "
            f"area={component.area:.6f}; bounds={bounds_text}; holes={len(component.interiors)}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Shapely-CDT road solid has inconsistent winding")
    print(
        f"CDT_SOLID_PASS vertices={len(mesh.vertices)} faces={len(mesh.faces)}",
        flush=True,
    )
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_SHAPELY_CDT_FINAL_PATCHED")
