from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''            vertices = np.asarray(mesh.vertices, dtype=float)
            top_mask = vertices[:, 2] > thickness / 2.0
            z_values = np.asarray([z_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)
'''

new = '''            vertices = np.asarray(mesh.vertices, dtype=float)
            source_local_z = vertices[:, 2].copy()
            z_values = np.asarray([z_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
            # Preserve every subdivided side-wall vertex continuously between
            # bottom and top. The Rev.P2-style binary top/bottom classification
            # collapsed intermediate side vertices and created zero-area faces.
            vertices[:, 2] = z_values - thickness + source_local_z
            mesh.vertices = vertices

            # Merge coincident vertices, remove any residual degenerates from
            # polygon booleans, and validate the resulting closed road solid.
            mesh.merge_vertices(digits_vertex=8)
            try:
                mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-8))
            except TypeError:
                mesh.remove_degenerate_faces(height=1.0e-8)
            try:
                mesh.update_faces(mesh.unique_faces())
            except Exception:
                pass
            mesh.remove_unreferenced_vertices()
            mesh.process(validate=True)
            mesh.merge_vertices(digits_vertex=8)
            try:
                mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-8))
            except Exception:
                pass
            try:
                mesh.update_faces(mesh.unique_faces())
            except Exception:
                pass
            mesh.remove_unreferenced_vertices()
            trimesh.repair.fill_holes(mesh)
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)
'''

if old not in text:
    raise RuntimeError("Rev.P3 solid post-warp block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P3_MESH_CLEANUP_PATCHED")
