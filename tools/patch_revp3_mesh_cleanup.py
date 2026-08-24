from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)
'''

new = '''            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices

            # Warping an extruded triangulation can collapse vertices which were
            # distinct only in the source planar triangulation. Merge them first,
            # then remove newly degenerate/duplicate faces and validate the closed
            # solid. This prevents zero-area spikes and restores manifold seams.
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
