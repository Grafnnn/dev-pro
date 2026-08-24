from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

anchor = '''    if not mesh.is_watertight:
        mesh, boundary_repairs = seal_small_boundary_loops(mesh)
        if boundary_repairs:
            log(f"Repaired {len(boundary_repairs)} small boundary loop(s): {boundary_repairs}")
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''

replacement = '''    if not mesh.is_watertight:
        mesh, boundary_repairs = seal_small_boundary_loops(mesh)
        if boundary_repairs:
            log(f"Repaired {len(boundary_repairs)} small boundary loop(s): {boundary_repairs}")
    trimesh.repair.fix_normals(mesh, multibody=True)
    if not mesh.is_watertight:
        edge_sorted = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
        unique_edges, inverse, counts = np.unique(edge_sorted, axis=0, return_inverse=True, return_counts=True)
        anomalous = unique_edges[counts != 2]
        details = []
        for edge in anomalous[:20]:
            key = tuple(int(value) for value in edge)
            face_indices = []
            for face_index, face in enumerate(np.asarray(mesh.faces, dtype=int)):
                pairs = {
                    tuple(sorted((int(face[0]), int(face[1])))),
                    tuple(sorted((int(face[1]), int(face[2])))),
                    tuple(sorted((int(face[2]), int(face[0])))),
                }
                if key in pairs:
                    face_indices.append(face_index)
            details.append(
                {
                    "edge": list(key),
                    "count": int(counts[np.where((unique_edges == edge).all(axis=1))[0][0]]),
                    "coordinates": np.asarray(mesh.vertices, dtype=float)[list(key)].tolist(),
                    "faces": face_indices[:12],
                }
            )
        log(f"Residual anomalous edges after repair: {details}")
    return mesh'''

if anchor not in text:
    raise RuntimeError("Rev.P3 edge diagnostic patch anchor not found")
text = text.replace(anchor, replacement, 1)
path.write_text(text, encoding="utf-8")
print("REV_P3_EDGE_DIAGNOSTIC_PATCHED")
