from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

start_marker = '''    boundary_edges = _oriented_boundary_edges(faces_2d)
    top_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices_2d],
        dtype=float,
    )
'''
end_marker = '''    if not mesh.is_winding_consistent:
        raise RuntimeError("Conforming refined road solid has inconsistent winding")
    return mesh
'''
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P3 final solid-assembly block not found")
end += len(end_marker)

replacement = '''    # Use Trimesh's closed extrusion on the cleaned, conforming triangulation.
    # This creates the top, bottom and all polygon/hole side walls from the same
    # indexed topology and avoids the single unmatched boundary edge observed in
    # the manually assembled Rev.P3 solid. The subsequent Z-warp changes only
    # coordinates, never connectivity.
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
    vertices[:, 2] = profile_z - float(thickness) + local_z
    mesh.vertices = vertices
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Final extruded road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Final extruded road solid has inconsistent winding")
    return mesh
'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("REV_P3_FINAL_EXTRUSION_PATCHED")
