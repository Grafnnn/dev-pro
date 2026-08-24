from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    mesh.remove_unreferenced_vertices()
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-9))
    except Exception:
        pass
    mesh.merge_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''

new = '''    mesh.remove_unreferenced_vertices()
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-9))
    except Exception:
        pass
    # Subdivision can leave numerically duplicated seam vertices at curved
    # polygon boundaries. Weld them at sub-millimetre precision, then seal any
    # residual short boundary loops. This is a geometric repair, not a QA
    # waiver: strict manifold checks still run after this step.
    try:
        mesh.merge_vertices(digits_vertex=7)
    except TypeError:
        mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        try:
            trimesh.repair.fill_holes(mesh)
        except Exception as exc:
            log(f"Hole-fill warning: {exc}")
        try:
            mesh.merge_vertices(digits_vertex=7)
        except TypeError:
            mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh'''

if old not in text:
    raise RuntimeError("Rev.P3 mesh-repair patch target not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("REV_P3_MESH_REPAIR_PATCHED")
