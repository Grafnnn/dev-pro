from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def solid_from_polygon(\n")
end = text.find("\ndef polygon_from_mesh_xy", start)
if start < 0 or end < 0:
    raise RuntimeError("solid_from_polygon function block not found")

replacement = r'''def _oriented_boundary_edges(faces: np.ndarray) -> np.ndarray:
    """Return boundary edges with the direction inherited from upward top faces."""
    faces = np.asarray(faces, dtype=int)
    directed = np.vstack(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]
    )
    undirected = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(
        undirected, axis=0, return_inverse=True, return_counts=True
    )
    return directed[counts[inverse] == 1]


def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """
    Build a road/apron solid whose top, bottom and side walls share exactly the
    same subdivided boundary vertices. This removes the T-junctions and open
    edges produced when a fully extruded mesh was subdivided after extrusion.
    """
    vertices_2d, top_faces = trimesh.creation.triangulate_polygon(
        component, engine="earcut"
    )
    vertices_2d = np.asarray(vertices_2d, dtype=float)
    top_faces = np.asarray(top_faces, dtype=int)
    if vertices_2d.shape[1] > 2:
        vertices_2d = vertices_2d[:, :2]

    flat_vertices = np.column_stack(
        [vertices_2d, np.zeros(len(vertices_2d), dtype=float)]
    )
    flat_top = trimesh.Trimesh(
        vertices=flat_vertices, faces=top_faces, process=False
    )
    if float(np.mean(flat_top.face_normals[:, 2])) < 0.0:
        top_faces = top_faces[:, ::-1]
        flat_top = trimesh.Trimesh(
            vertices=flat_vertices, faces=top_faces, process=False
        )

    subdivided_vertices, subdivided_faces = trimesh.remesh.subdivide_to_size(
        np.asarray(flat_top.vertices),
        np.asarray(flat_top.faces),
        max_edge=max_edge,
        max_iter=12,
        return_index=False,
    )
    subdivided_vertices = np.asarray(subdivided_vertices, dtype=float)
    subdivided_faces = np.asarray(subdivided_faces, dtype=int)
    check_top = trimesh.Trimesh(
        vertices=subdivided_vertices,
        faces=subdivided_faces,
        process=False,
    )
    if float(np.mean(check_top.face_normals[:, 2])) < 0.0:
        subdivided_faces = subdivided_faces[:, ::-1]

    boundary_edges = _oriented_boundary_edges(subdivided_faces)
    xy = subdivided_vertices[:, :2]
    top_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in xy], dtype=float
    )
    top_vertices = np.column_stack([xy, top_z])
    bottom_vertices = np.column_stack([xy, top_z - float(thickness)])
    vertex_count = len(top_vertices)
    vertices = np.vstack([top_vertices, bottom_vertices])

    top = subdivided_faces.copy()
    bottom = subdivided_faces[:, ::-1] + vertex_count
    side_faces = np.empty((len(boundary_edges) * 2, 3), dtype=int)
    for index, (a, b) in enumerate(boundary_edges):
        side_faces[2 * index] = [a, a + vertex_count, b + vertex_count]
        side_faces[2 * index + 1] = [a, b + vertex_count, b]
    faces = np.vstack([top, bottom, side_faces])

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=9)
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
    mesh.merge_vertices(digits_vertex=9)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    if not mesh.is_watertight:
        edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
        _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
        open_edges = int(np.count_nonzero(edge_counts != 2))
        raise RuntimeError(
            f"Conforming road solid is not watertight: open/non-manifold edges={open_edges}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Conforming road solid has inconsistent winding")
    return mesh


def solid_from_polygon(
    geometry,
    z_function: Callable[[float, float], float],
    thickness: float,
    rgba: Sequence[int],
    max_edge: float = MESH_MAX_EDGE,
) -> trimesh.Trimesh | None:
    meshes: list[trimesh.Trimesh] = []
    for polygon in iter_polygons(geometry):
        if polygon.area < 1.0e-5:
            continue
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        for component in iter_polygons(polygon):
            if component.area < 1.0e-5:
                continue
            mesh = _conforming_watertight_solid(
                component=component,
                z_function=z_function,
                thickness=thickness,
                max_edge=max_edge,
            )
            color_mesh(mesh, rgba)
            meshes.append(mesh)
    if not meshes:
        return None
    result = trimesh.util.concatenate(meshes)
    result.merge_vertices(digits_vertex=9)
    result.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(result, multibody=True)
    return result
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_WATERTIGHT_SOLIDS_PATCHED")
