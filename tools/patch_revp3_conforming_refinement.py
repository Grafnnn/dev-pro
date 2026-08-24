from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Generated Rev.P3 solid function not found")

replacement = r'''def _triangle_signed_area(vertices: np.ndarray, face: np.ndarray) -> float:
    a, b, c = vertices[face]
    return 0.5 * float(
        (b[0] - a[0]) * (c[1] - a[1])
        - (b[1] - a[1]) * (c[0] - a[0])
    )


def _refine_triangulation_conforming(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    max_edge: float,
    max_iterations: int = 12,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Split every over-length undirected edge once per iteration. Affected faces
    are retriangulated from a face-centroid to the ordered, midpoint-enriched
    boundary. The same midpoint index is reused by both incident faces, so no
    T-junctions or hanging boundary nodes are possible.
    """
    vertices = np.asarray(vertices_2d, dtype=float).copy()
    triangles = np.asarray(faces, dtype=int).copy()
    tolerance = float(max_edge) * (1.0 + 1.0e-9)

    for _ in range(max_iterations):
        edge_keys: set[tuple[int, int]] = set()
        for a, b, c in triangles:
            edge_keys.add((min(int(a), int(b)), max(int(a), int(b))))
            edge_keys.add((min(int(b), int(c)), max(int(b), int(c))))
            edge_keys.add((min(int(c), int(a)), max(int(c), int(a))))

        long_edges = {
            edge
            for edge in edge_keys
            if float(np.linalg.norm(vertices[edge[0]] - vertices[edge[1]]))
            > tolerance
        }
        if not long_edges:
            return vertices, triangles

        midpoint_index: dict[tuple[int, int], int] = {}
        new_vertices = vertices.tolist()
        for edge in sorted(long_edges):
            midpoint_index[edge] = len(new_vertices)
            new_vertices.append(
                (0.5 * (vertices[edge[0]] + vertices[edge[1]])).tolist()
            )

        refined_faces: list[list[int]] = []
        for face in triangles:
            a, b, c = [int(value) for value in face]
            edge_ab = (min(a, b), max(a, b))
            edge_bc = (min(b, c), max(b, c))
            edge_ca = (min(c, a), max(c, a))
            split_ab = edge_ab in midpoint_index
            split_bc = edge_bc in midpoint_index
            split_ca = edge_ca in midpoint_index
            if not (split_ab or split_bc or split_ca):
                refined_faces.append([a, b, c])
                continue

            ring = [a]
            if split_ab:
                ring.append(midpoint_index[edge_ab])
            ring.append(b)
            if split_bc:
                ring.append(midpoint_index[edge_bc])
            ring.append(c)
            if split_ca:
                ring.append(midpoint_index[edge_ca])

            centroid_index = len(new_vertices)
            centroid = np.mean(vertices[[a, b, c]], axis=0)
            new_vertices.append(centroid.tolist())
            original_sign = 1.0 if _triangle_signed_area(vertices, face) >= 0.0 else -1.0

            local_vertices = np.asarray(new_vertices, dtype=float)
            for index in range(len(ring)):
                candidate = [centroid_index, ring[index], ring[(index + 1) % len(ring)]]
                sign = _triangle_signed_area(local_vertices, np.asarray(candidate, dtype=int))
                if sign * original_sign < 0.0:
                    candidate[1], candidate[2] = candidate[2], candidate[1]
                if abs(_triangle_signed_area(local_vertices, np.asarray(candidate, dtype=int))) <= 1.0e-12:
                    raise RuntimeError("Conforming refinement generated a degenerate face")
                refined_faces.append(candidate)

        vertices = np.asarray(new_vertices, dtype=float)
        triangles = np.asarray(refined_faces, dtype=int)

    maximum = 0.0
    for face in triangles:
        points = vertices[face]
        maximum = max(
            maximum,
            float(np.linalg.norm(points[1] - points[0])),
            float(np.linalg.norm(points[2] - points[1])),
            float(np.linalg.norm(points[0] - points[2])),
        )
    if maximum > tolerance:
        raise RuntimeError(
            f"Conforming refinement did not reach edge limit: {maximum:.6f} m"
        )
    return vertices, triangles


def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
) -> trimesh.Trimesh:
    """Build one closed road/apron solid without nonconforming subdivision."""
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    vertices_2d, faces_2d = trimesh.creation.triangulate_polygon(
        component,
        engine="earcut",
    )
    vertices_2d = np.asarray(vertices_2d, dtype=float)
    faces_2d = np.asarray(faces_2d, dtype=int)
    if vertices_2d.shape[1] > 2:
        vertices_2d = vertices_2d[:, :2]
    if len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Earcut returned no usable triangulation")

    vertices_2d, faces_2d = _refine_triangulation_conforming(
        vertices_2d,
        faces_2d,
        max_edge=float(max_edge),
    )
    # Normalize top orientation before deriving directed boundary edges.
    signed = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
    if float(np.median(signed)) < 0.0:
        faces_2d = faces_2d[:, ::-1]
    if np.any(np.abs(signed) <= 1.0e-12):
        raise RuntimeError("Refined top triangulation contains zero-area faces")

    boundary_edges = _oriented_boundary_edges(faces_2d)
    top_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices_2d],
        dtype=float,
    )
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
            "Conforming refined road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Conforming refined road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_CONFORMING_REFINEMENT_PATCHED")
