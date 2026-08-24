from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=9)
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    mesh.remove_unreferenced_vertices()
    mesh.process(validate=True)
    mesh.merge_vertices(digits_vertex=9)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    if not mesh.is_watertight:
'''

new = '''    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    # Earcut may intentionally duplicate coincident XY vertices at hole bridges.
    # They are distinct topological vertices with their own closed side loops.
    # Merging them converts a valid closed solid into a non-manifold junction,
    # so preserve the exact conforming indices generated above.
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-10))
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    if not mesh.is_watertight:
'''

if old not in text:
    raise RuntimeError("Watertight solid cleanup block not found")
text = text.replace(old, new, 1)

old_result = '''    result = trimesh.util.concatenate(meshes)
    result.merge_vertices(digits_vertex=9)
    result.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(result, multibody=True)
    return result
'''
new_result = '''    result = trimesh.util.concatenate(meshes)
    # Keep disconnected polygon components and earcut bridge indices distinct;
    # every component was already individually proven watertight.
    result.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(result, multibody=True)
    return result
'''
if old_result not in text:
    raise RuntimeError("Watertight solid result cleanup block not found")
text = text.replace(old_result, new_result, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_TOPOLOGY_INDICES_PRESERVED")
