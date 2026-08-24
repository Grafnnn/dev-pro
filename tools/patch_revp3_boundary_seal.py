from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# Add NetworkX import used for deterministic boundary-loop ordering.
import_anchor = "import numpy as np\nimport requests\nimport trimesh"
import_replacement = "import numpy as np\nimport networkx as nx\nimport requests\nimport trimesh"
if import_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal import anchor not found")
text = text.replace(import_anchor, import_replacement, 1)

# Insert a conservative boundary repair before subdivide_mesh. It accepts only
# small, simple, nearly planar cycles. Collinear 3-edge cycles are not actual
# holes: they are T-junctions where one adjacent triangle uses a long A-C edge
# while its neighbour uses A-B and B-C. Those are repaired by splitting the
# adjacent face at B, avoiding zero-area cap triangles entirely.
function_anchor = "\ndef subdivide_mesh(mesh: trimesh.Trimesh, max_edge: float = MESH_MAX_EDGE) -> trimesh.Trimesh:\n"
helper = r'''
def seal_small_boundary_loops(
    mesh: trimesh.Trimesh,
    *,
    max_loop_perimeter_m: float = 15.0,
    max_loop_vertices: int = 24,
    max_planarity_error_m: float = 0.025,
    minimum_face_area_m2: float = 1.0e-10,
) -> tuple[trimesh.Trimesh, list[dict]]:
    edge_sorted = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    if len(edge_sorted) == 0:
        return mesh, []
    unique_edges, counts = np.unique(edge_sorted, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    if len(boundary_edges) == 0:
        return mesh, []

    graph = nx.Graph()
    graph.add_edges_from((int(a), int(b)) for a, b in boundary_edges)
    vertices = np.asarray(mesh.vertices, dtype=float).tolist()
    faces = np.asarray(mesh.faces, dtype=int).tolist()
    repairs: list[dict] = []

    for component_index, node_set in enumerate(nx.connected_components(graph), 1):
        subgraph = graph.subgraph(node_set)
        degrees = {int(node): int(degree) for node, degree in subgraph.degree()}
        if any(degree != 2 for degree in degrees.values()):
            raise RuntimeError(
                f"Boundary component {component_index} is not a simple cycle: degrees={degrees}"
            )
        if len(node_set) > max_loop_vertices:
            raise RuntimeError(
                f"Boundary component {component_index} has {len(node_set)} vertices; "
                f"limit is {max_loop_vertices}"
            )

        start = min(int(node) for node in node_set)
        ordered = [start]
        previous = None
        current = start
        while True:
            neighbours = sorted(int(node) for node in subgraph.neighbors(current))
            candidates = [node for node in neighbours if node != previous]
            if not candidates:
                raise RuntimeError(f"Cannot traverse boundary cycle {component_index}")
            next_node = candidates[0]
            if next_node == start:
                break
            if next_node in ordered:
                raise RuntimeError(f"Boundary cycle {component_index} self-repeats at vertex {next_node}")
            ordered.append(next_node)
            previous, current = current, next_node
            if len(ordered) > len(node_set) + 1:
                raise RuntimeError(f"Boundary cycle {component_index} traversal overflow")
        if len(ordered) != len(node_set):
            raise RuntimeError(
                f"Boundary cycle {component_index} traversal mismatch: "
                f"ordered={len(ordered)} nodes={len(node_set)}"
            )

        coordinates = np.asarray([vertices[index] for index in ordered], dtype=float)
        closed = np.vstack([coordinates, coordinates[0]])
        perimeter = float(np.linalg.norm(np.diff(closed, axis=0), axis=1).sum())
        if perimeter > max_loop_perimeter_m:
            raise RuntimeError(
                f"Boundary cycle {component_index} perimeter {perimeter:.3f} m exceeds "
                f"repair limit {max_loop_perimeter_m:.3f} m"
            )

        centroid = coordinates.mean(axis=0)
        _, _, vh = np.linalg.svd(coordinates - centroid, full_matrices=False)
        normal = vh[-1]
        planarity_error = float(np.max(np.abs((coordinates - centroid) @ normal)))
        if planarity_error > max_planarity_error_m:
            raise RuntimeError(
                f"Boundary cycle {component_index} planarity error {planarity_error:.4f} m exceeds "
                f"{max_planarity_error_m:.4f} m"
            )

        # Special case: a collinear triangular boundary is a T-junction seam,
        # not a geometric hole. Split the one face using the long endpoint edge.
        if len(ordered) == 3:
            a, b, c = coordinates
            triangle_area = float(np.linalg.norm(np.cross(b - a, c - a)) / 2.0)
            if triangle_area <= minimum_face_area_m2:
                distances = {
                    (0, 1): float(np.linalg.norm(coordinates[0] - coordinates[1])),
                    (1, 2): float(np.linalg.norm(coordinates[1] - coordinates[2])),
                    (0, 2): float(np.linalg.norm(coordinates[0] - coordinates[2])),
                }
                endpoint_local = max(distances, key=distances.get)
                middle_local = ({0, 1, 2} - set(endpoint_local)).pop()
                endpoint_first = ordered[endpoint_local[0]]
                endpoint_second = ordered[endpoint_local[1]]
                middle = ordered[middle_local]

                candidate_faces = [
                    index
                    for index, face in enumerate(faces)
                    if endpoint_first in face and endpoint_second in face and middle not in face
                ]
                if len(candidate_faces) != 1:
                    raise RuntimeError(
                        f"T-junction boundary {component_index} expected one adjacent long-edge face, "
                        f"found {len(candidate_faces)}"
                    )
                face_index = candidate_faces[0]
                face = list(faces[face_index])
                third = next(vertex for vertex in face if vertex not in (endpoint_first, endpoint_second))

                # Preserve the original face orientation by detecting the
                # directed long edge in its cyclic vertex order.
                oriented_start = oriented_end = None
                for position in range(3):
                    first = face[position]
                    second = face[(position + 1) % 3]
                    if {first, second} == {endpoint_first, endpoint_second}:
                        oriented_start, oriented_end = first, second
                        break
                if oriented_start is None:
                    raise RuntimeError(f"Cannot orient T-junction face {face_index}")

                first_face = [oriented_start, middle, third]
                second_face = [middle, oriented_end, third]
                for candidate in (first_face, second_face):
                    xyz = np.asarray([vertices[index] for index in candidate], dtype=float)
                    area = float(np.linalg.norm(np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0])) / 2.0)
                    if area <= minimum_face_area_m2:
                        raise RuntimeError(
                            f"T-junction split would create zero-area face in component {component_index}: "
                            f"{candidate}, area={area}"
                        )
                faces[face_index] = first_face
                faces.append(second_face)
                repairs.append(
                    {
                        "loop": component_index,
                        "vertices": 3,
                        "perimeter_m": perimeter,
                        "planarity_error_m": planarity_error,
                        "repair": "split adjacent long-edge face at collinear T-junction",
                        "split_face_index": face_index,
                    }
                )
                continue

            # A genuine non-collinear triangular hole closes with one triangle.
            faces.append(list(ordered))
            repairs.append(
                {
                    "loop": component_index,
                    "vertices": 3,
                    "perimeter_m": perimeter,
                    "planarity_error_m": planarity_error,
                    "repair": "single triangular cap; normals repaired after closure",
                }
            )
            continue

        # General small planar cycle: centroid fan with explicit area checks.
        centroid_index = len(vertices)
        vertices.append(centroid.tolist())
        new_faces = []
        for index, first in enumerate(ordered):
            second = ordered[(index + 1) % len(ordered)]
            candidate = [first, second, centroid_index]
            xyz = np.asarray([vertices[vertex] for vertex in candidate], dtype=float)
            area = float(np.linalg.norm(np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0])) / 2.0)
            if area <= minimum_face_area_m2:
                raise RuntimeError(
                    f"Boundary fan would create zero-area face in component {component_index}: "
                    f"{candidate}, area={area}"
                )
            new_faces.append(candidate)
        faces.extend(new_faces)
        repairs.append(
            {
                "loop": component_index,
                "vertices": len(ordered),
                "perimeter_m": perimeter,
                "planarity_error_m": planarity_error,
                "repair": "checked centroid-fan cap; normals repaired after closure",
            }
        )

    repaired = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=float),
        faces=np.asarray(faces, dtype=int),
        process=False,
    )
    repaired.remove_unreferenced_vertices()
    try:
        repaired.merge_vertices(digits_vertex=7)
    except TypeError:
        repaired.merge_vertices()
    repaired.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(repaired, multibody=True)
    repaired.metadata["revp3_boundary_loop_repairs"] = repairs
    return repaired, repairs

'''
if function_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal function anchor not found")
text = text.replace(function_anchor, "\n" + helper + function_anchor, 1)

# Invoke the conservative sealer after the normal Trimesh repair pass and
# before strict manifold QA. If closure is not exact, hard QA still fails.
call_anchor = '''        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''
call_replacement = '''        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    if not mesh.is_watertight:
        mesh, boundary_repairs = seal_small_boundary_loops(mesh)
        if boundary_repairs:
            log(f"Repaired {len(boundary_repairs)} small boundary loop(s): {boundary_repairs}")
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''
if call_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal invocation anchor not found")
text = text.replace(call_anchor, call_replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_BOUNDARY_SEAL_PATCHED")
