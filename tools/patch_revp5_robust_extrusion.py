from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P5 road solid function not found")

replacement = r'''def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """Create a closed road/apron body from the actual triangulation boundary.

    The previous generic extrusion failed on the D2 loop because its connector
    and annular carriageway create a numerically difficult hole interface.  This
    implementation deduplicates all 2D triangulation vertices, obtains boundary
    edges directly from the filled top mesh, and creates one matching side wall
    for every boundary edge.  Closed topology is therefore guaranteed before
    any 3D refinement or profile warping.
    """
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    exterior = np.round(np.asarray(component.exterior.coords, dtype=float), 7)
    holes = []
    for ring in component.interiors:
        hole = Polygon(ring)
        if hole.area >= 0.005:
            holes.append(np.round(np.asarray(ring.coords, dtype=float), 7))
    component = Polygon(exterior, holes).buffer(0)
    if component.is_empty or not isinstance(component, Polygon):
        raise RuntimeError("Precision cleanup did not produce one road polygon")

    vertices_2d, top_faces = trimesh.creation.triangulate_polygon(
        component,
        engine="earcut",
    )
    coordinates = np.round(np.asarray(vertices_2d, dtype=float)[:, :2], 8)
    unique_xy, inverse = np.unique(coordinates, axis=0, return_inverse=True)
    top_faces = inverse[np.asarray(top_faces, dtype=int)]

    # Remove triangles collapsed by coordinate deduplication.
    unique_vertex_count = np.apply_along_axis(lambda row: len(set(row.tolist())), 1, top_faces)
    top_faces = top_faces[unique_vertex_count == 3]
    if len(top_faces) == 0:
        raise RuntimeError("No valid top triangles after vertex deduplication")
    sorted_faces = np.sort(top_faces, axis=1)
    _, unique_face_indices = np.unique(sorted_faces, axis=0, return_index=True)
    top_faces = top_faces[np.sort(unique_face_indices)]

    triangles = unique_xy[top_faces]
    area2 = (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )
    keep = np.abs(area2) > 1.0e-12
    top_faces = top_faces[keep]
    area2 = area2[keep]
    if len(top_faces) == 0:
        raise RuntimeError("All top triangles are degenerate")
    flip = area2 < 0.0
    if np.any(flip):
        temporary = top_faces[flip, 1].copy()
        top_faces[flip, 1] = top_faces[flip, 2]
        top_faces[flip, 2] = temporary

    # Directed boundary edges follow the top-face orientation.  Every
    # undirected edge used once receives exactly two side triangles.
    directed_edges = np.vstack(
        [top_faces[:, [0, 1]], top_faces[:, [1, 2]], top_faces[:, [2, 0]]]
    )
    undirected_edges = np.sort(directed_edges, axis=1)
    _, inverse_edges, edge_counts = np.unique(
        undirected_edges,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    boundary_edges = directed_edges[edge_counts[inverse_edges] == 1]
    if len(boundary_edges) < 3:
        raise RuntimeError("Triangulation contains no valid polygon boundary")

    count = len(unique_xy)
    top_vertices = np.column_stack(
        [unique_xy, np.full(count, float(thickness), dtype=float)]
    )
    bottom_vertices = np.column_stack(
        [unique_xy, np.zeros(count, dtype=float)]
    )
    vertices = np.vstack([top_vertices, bottom_vertices])
    bottom_faces = top_faces[:, ::-1] + count
    side_faces = []
    for a, b in boundary_edges:
        a = int(a)
        b = int(b)
        side_faces.append([a + count, b + count, b])
        side_faces.append([a + count, b, a])
    faces = np.vstack([top_faces, bottom_faces, np.asarray(side_faces, dtype=int)])
    flat = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    flat.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(flat, multibody=True)

    edge_rows = np.sort(np.asarray(flat.edges, dtype=int), axis=1)
    _, edge_counts_3d = np.unique(edge_rows, axis=0, return_counts=True)
    initial_open = int(np.count_nonzero(edge_counts_3d != 2))
    if initial_open != 0 or not flat.is_watertight:
        raise RuntimeError(
            "Boundary-derived road shell is not watertight: "
            f"open/non-manifold edges={initial_open}; "
            f"area={component.area:.6f}; bounds={component.bounds}"
        )

    vertices, faces = trimesh.remesh.subdivide_to_size(
        np.asarray(flat.vertices, dtype=float),
        np.asarray(flat.faces, dtype=int),
        max_edge=float(max_edge),
        max_iter=12,
        return_index=False,
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=8)
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    mesh.remove_unreferenced_vertices()

    vertices = np.asarray(mesh.vertices, dtype=float)
    local_z = np.clip(vertices[:, 2], 0.0, float(thickness))
    profile_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices[:, :2]],
        dtype=float,
    )
    vertices[:, 2] = profile_z - float(thickness) + local_z
    mesh.vertices = vertices
    trimesh.repair.fix_normals(mesh, multibody=True)

    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, final_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(final_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Refined boundary-derived road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}; "
            f"area={component.area:.6f}; bounds={component.bounds}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Boundary-derived road solid has inconsistent winding")
    return mesh
'''

marker = "REV_P5_ROBUST_EXTRUSION_ACTIVE = True\n\n"
prefix = text[:start]
if "REV_P5_ROBUST_EXTRUSION_ACTIVE" not in prefix:
    prefix += marker
path.write_text(prefix + replacement + text[end:], encoding="utf-8")
print("REV_P5_ROBUST_EXTRUSION_PATCHED")
