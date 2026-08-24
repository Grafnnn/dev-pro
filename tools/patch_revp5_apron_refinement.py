from __future__ import annotations

from pathlib import Path

PATH = Path("tools/build_revp3_roadqa.py")
text = PATH.read_text(encoding="utf-8")

old = '''    changed_quality = {}
    for name in changed_mesh_names:
        mesh = target.geometry.get(name)
        if mesh is None:
            continue
        quality = mesh_quality(mesh)
        changed_quality[name] = quality'''

new = '''    changed_quality = {}
    for name in changed_mesh_names:
        mesh = target.geometry.get(name)
        if mesh is None:
            continue

        # Service-apron polygons can contain narrow connectors and internal
        # exclusions.  Refine their already-valid closed solids in 3D before
        # the final edge/aspect QA so that no long diagonal survives across an
        # apron bay.  This does not move the apron boundary or alter its grade.
        if name.endswith("_SERVICE_APRON"):
            preliminary = mesh_quality(mesh)
            if preliminary["max_edge_m"] > MESH_MAX_EDGE * 1.40:
                vertices, faces = trimesh.remesh.subdivide_to_size(
                    np.asarray(mesh.vertices, dtype=float),
                    np.asarray(mesh.faces, dtype=int),
                    max_edge=2.20,
                    max_iter=12,
                    return_index=False,
                )
                refined = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
                refined.remove_unreferenced_vertices()
                try:
                    refined.update_faces(refined.unique_faces())
                except Exception:
                    pass
                try:
                    refined.update_faces(refined.nondegenerate_faces(height=1.0e-10))
                except Exception:
                    pass
                refined.merge_vertices()
                trimesh.repair.fix_normals(refined, multibody=True)
                color_mesh(refined, COLORS["concrete"])
                target.delete_geometry(name)
                target.add_geometry(refined, geom_name=name, node_name=name)
                mesh = target.geometry.get(name)

        quality = mesh_quality(mesh)
        changed_quality[name] = quality'''

if old not in text:
    raise RuntimeError("Rev.P5 apron refinement insertion target not found")

PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P5_APRON_REFINEMENT_PATCHED")
