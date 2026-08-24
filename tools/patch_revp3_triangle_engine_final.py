from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P3 solid function not found for final Triangle patch")

replacement = r'''def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """Build one closed warped solid from a constrained planar triangulation.

    The previous earcut/refinement chain could leave one unmatched edge on a
    Boolean-heavy road polygon.  Here the polygon boundary and all holes are
    segmentized first and passed to Jonathan Shewchuk's constrained Triangle
    engine.  The resulting indexed 2D complex is extruded once; the profile
    warp changes coordinates only and therefore cannot change topology.
    """
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    # Split every boundary segment before meshing.  This limits side-wall edge
    # length as well as top-face edge length and avoids post-extrusion T-joints.
    try:
        component = component.segmentize(max(0.25, float(max_edge) * 0.72))
    except Exception:
        pass
    component = component.buffer(0)
    if component.is_empty or not component.is_valid:
        raise RuntimeError("Road polygon became invalid during boundary segmentizing")

    maximum_area = max(0.15, 0.22 * float(max_edge) * float(max_edge))
    triangle_args = f"pq30a{maximum_area:.8f}"
    vertices_2d, faces_2d = trimesh.creation.triangulate_polygon(
        component,
        engine="triangle",
        triangle_args=triangle_args,
    )
    vertices_2d = np.asarray(vertices_2d, dtype=float)
    faces_2d = np.asarray(faces_2d, dtype=int)
    if vertices_2d.ndim != 2 or len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Triangle returned no usable constrained triangulation")
    if vertices_2d.shape[1] > 2:
        vertices_2d = vertices_2d[:, :2]

    # Triangle should already produce unique, conforming indices.  Remove only
    # mathematically zero-area faces and duplicate face rows; never drop a real
    # polygon component or weaken the final manifold acceptance criteria.
    repeated = (
        (faces_2d[:, 0] == faces_2d[:, 1])
        | (faces_2d[:, 1] == faces_2d[:, 2])
        | (faces_2d[:, 2] == faces_2d[:, 0])
    )
    signed_area = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
    keep = (~repeated) & (np.abs(signed_area) > 1.0e-12)
    faces_2d = faces_2d[keep]
    if len(faces_2d) < 1:
        raise RuntimeError("Triangle mesh contains no non-degenerate faces")
    # Normalize the whole planar mesh upward before extrusion.
    signed_area = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
    if float(np.median(signed_area)) < 0.0:
        faces_2d = faces_2d[:, ::-1]

    mesh = trimesh.creation.extrude_triangulation(
        vertices=vertices_2d,
        faces=faces_2d,
        height=float(thickness),
    )
    vertices = np.asarray(mesh.vertices, dtype=float)
    local_z = vertices[:, 2].copy()
    profile_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices[:, :2]],
        dtype=float,
    )
    if not np.isfinite(profile_z).all():
        raise RuntimeError("Road profile returned non-finite elevations")
    vertices[:, 2] = profile_z - float(thickness) + local_z
    mesh.vertices = vertices

    # Safe for Triangle output: unlike earcut hole bridges, constrained
    # triangulation does not rely on duplicated coincident topological nodes.
    mesh.merge_vertices(digits_vertex=10)
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    mesh.remove_unreferenced_vertices()
    mesh.process(validate=True)
    mesh.merge_vertices(digits_vertex=10)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Triangle-engine final road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}; "
            f"area={component.area:.6f}; bounds={tuple(round(v, 4) for v in component.bounds)}; "
            f"holes={len(component.interiors)}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Triangle-engine final road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_TRIANGLE_ENGINE_FINAL_PATCHED")
