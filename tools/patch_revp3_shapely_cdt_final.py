from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P3 solid function not found for Shapely CDT patch")

replacement = r'''def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """Build a closed warped solid from Shapely constrained Delaunay faces.

    The Triangle C extension can segfault on the Boolean-heavy road polygons
    containing multiple apron holes. Shapely/GEOS constrained Delaunay gives a
    deterministic, hole-respecting planar complex. Its triangle coordinates are
    globally indexed and then refined with the existing conforming edge splitter.
    """
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

    # Verify the planar complex is neither missing area nor crossing holes.
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
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Shapely-CDT road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}; "
            f"area={component.area:.6f}; bounds={bounds_text}; "
            f"holes={len(component.interiors)}"
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
