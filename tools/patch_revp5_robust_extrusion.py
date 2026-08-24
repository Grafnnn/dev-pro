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
    """Create a closed road/apron body and refine the *whole* solid.

    Earcut first creates one valid closed extrusion.  Refinement is then applied
    to the complete 3D shell with shared midpoint indexing.  This avoids the
    unmatched boundary edge produced when only the top triangulation was
    recursively refined and side walls were reconstructed afterwards.
    """
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    flat = trimesh.creation.extrude_polygon(
        component,
        height=float(thickness),
        engine="earcut",
    )
    if not flat.is_watertight:
        raise RuntimeError("Initial Earcut extrusion is not watertight")

    vertices, faces = trimesh.remesh.subdivide_to_size(
        np.asarray(flat.vertices, dtype=float),
        np.asarray(flat.faces, dtype=int),
        max_edge=float(max_edge),
        max_iter=12,
        return_index=False,
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=9)
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
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Full-shell refined road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Full-shell refined road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P5_ROBUST_EXTRUSION_PATCHED")
