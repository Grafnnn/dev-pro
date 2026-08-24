from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Generated conforming solid function not found")

replacement = r'''def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """
    Create a quality constrained 2D triangulation first, extrude it as one
    closed solid, and only then warp top and bottom by the road/apron profile.
    No post-extrusion subdivision is used, so top, bottom and side walls retain
    identical boundary indices and cannot develop T-junctions.
    """
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build solid from empty polygon")

    # A maximum triangle area of roughly half max_edge squared produces a
    # compact, non-sliver mesh. The Triangle engine also splits long boundary
    # segments, including polygon holes, while preserving all constraints.
    maximum_area = max(0.20, 0.42 * float(max_edge) * float(max_edge))
    triangle_args = f"pq28a{maximum_area:.8f}"
    vertices_2d, faces_2d = trimesh.creation.triangulate_polygon(
        component,
        engine="triangle",
        triangle_args=triangle_args,
    )
    vertices_2d = np.asarray(vertices_2d, dtype=float)
    faces_2d = np.asarray(faces_2d, dtype=int)
    if vertices_2d.ndim != 2 or len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Constrained triangulation returned no usable faces")
    if vertices_2d.shape[1] > 2:
        vertices_2d = vertices_2d[:, :2]

    mesh = trimesh.creation.extrude_triangulation(
        vertices=vertices_2d,
        faces=faces_2d,
        height=float(thickness),
    )
    vertices = np.asarray(mesh.vertices, dtype=float)
    source_local_z = vertices[:, 2].copy()
    z_values = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices[:, :2]],
        dtype=float,
    )
    vertices[:, 2] = z_values - float(thickness) + source_local_z
    mesh.vertices = vertices

    # Topology is unchanged by the warp. Clean only duplicate/degenerate faces
    # without merging topological bridge vertices created for polygon holes.
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Quality-constrained road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Quality-constrained road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_TRIANGLE_SOLIDS_PATCHED")
