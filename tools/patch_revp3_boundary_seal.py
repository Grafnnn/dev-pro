from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# Add NetworkX import used for deterministic boundary-loop ordering.
import_anchor = "import numpy as np\nimport requests\nimport trimesh"
import_replacement = "import numpy as np\nimport networkx as nx\nimport requests\nimport trimesh"
if import_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal import anchor not found")
text = text.replace(import_anchor, import_replacement, 1)

# Insert a conservative hole sealer before subdivide_mesh.  It only accepts
# small, simple, nearly planar closed boundary cycles.  Large/open/non-planar
# boundaries remain a hard failure and cannot be hidden by this repair.
function_anchor = "\ndef subdivide_mesh(mesh: trimesh.Trimesh, max_edge: float = MESH_MAX_EDGE) -> trimesh.Trimesh:\n"
helper = r'''
def seal_small_boundary_loops(
    mesh: trimesh.Trimesh,
    *,
    max_loop_perimeter_m: float = 15.0,
    max_loop_vertices: int = 24,
    max_planarity_error_m: float = 0.025,
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

        centroid_index = len(vertices)
        vertices.append(centroid.tolist())
        for index, first in enumerate(ordered):
            second = ordered[(index + 1) % len(ordered)]
            faces.append([first, second, centroid_index])

        repairs.append(
            {
                "loop": component_index,
                "vertices": len(ordered),
                "perimeter_m": perimeter,
                "planarity_error_m": planarity_error,
                "repair": "centroid fan cap; normals repaired after closure",
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
    trimesh.repair.fix_normals(repaired, multibody=True)
    repaired.metadata["revp3_boundary_loop_repairs"] = repairs
    return repaired, repairs

'''
if function_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal function anchor not found")
text = text.replace(function_anchor, "\n" + helper + function_anchor, 1)

# Invoke the conservative sealer after the normal Trimesh repair pass and
# before strict manifold QA.  If closure is not exact, hard QA still fails.
call_anchor = '''        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''
call_replacement = '''        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    if not mesh.is_watertight:
        mesh, boundary_repairs = seal_small_boundary_loops(mesh)
        if boundary_repairs:
            log(f"Sealed {len(boundary_repairs)} small boundary loop(s): {boundary_repairs}")
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''
if call_anchor not in text:
    raise RuntimeError("Rev.P3 boundary-seal invocation anchor not found")
text = text.replace(call_anchor, call_replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_BOUNDARY_SEAL_PATCHED")
