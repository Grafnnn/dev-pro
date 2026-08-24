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

    The source polygon is precision-cleaned, Earcut creates the initial closed
    shell, and the complete 3D shell is refined with shared midpoint indexing.
    Duplicate and degenerate faces are removed before and after refinement.
    """
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    # Remove sub-millimetre Boolean noise without changing the engineering
    # corridor.  Tiny interior rings below 1 cm2 are modelling artefacts rather
    # than drainage/building clearances and are intentionally discarded.
    exterior = np.round(np.asarray(component.exterior.coords, dtype=float), 6)
    holes = []
    for ring in component.interiors:
        hole = Polygon(ring)
        if hole.area >= 0.01:
            holes.append(np.round(np.asarray(ring.coords, dtype=float), 6))
    component = Polygon(exterior, holes).buffer(0)
    if component.is_empty or not isinstance(component, Polygon):
        raise RuntimeError("Precision cleanup did not produce one road polygon")

    flat = trimesh.creation.extrude_polygon(
        component,
        height=float(thickness),
        engine="earcut",
    )
    flat.merge_vertices(digits_vertex=8)
    try:
        flat.update_faces(flat.unique_faces())
    except Exception:
        pass
    try:
        flat.update_faces(flat.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    flat.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(flat, multibody=True)
    if not flat.is_watertight:
        # Earcut can occasionally leave a microscopic duplicate seam after a
        # complex Shapely difference.  Trimesh's validator and hole repair are
        # applied to the already closed extrusion topology before refinement.
        flat.process(validate=True)
        flat.merge_vertices(digits_vertex=7)
        try:
            flat.update_faces(flat.unique_faces())
        except Exception:
            pass
        try:
            flat.update_faces(flat.nondegenerate_faces(height=1.0e-10))
        except Exception:
            pass
        flat.remove_unreferenced_vertices()
        trimesh.repair.fill_holes(flat)
        trimesh.repair.fix_normals(flat, multibody=True)
    if not flat.is_watertight:
        edge_rows = np.sort(np.asarray(flat.edges, dtype=int), axis=1)
        _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
        raise RuntimeError(
            "Repaired Earcut extrusion is not watertight: "
            f"open/non-manifold edges={int(np.count_nonzero(edge_counts != 2))}; "
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
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Full-shell refined road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}; "
            f"area={component.area:.6f}; bounds={component.bounds}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Full-shell refined road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P5_ROBUST_EXTRUSION_PATCHED")
