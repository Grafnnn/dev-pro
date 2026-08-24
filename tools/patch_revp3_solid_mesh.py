from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''            mesh = trimesh.creation.extrude_polygon(component, height=thickness, engine="earcut")
            mesh = subdivide_mesh(mesh, max_edge)
            vertices = np.asarray(mesh.vertices, dtype=float)
            top_mask = vertices[:, 2] > thickness / 2.0
            z_values = np.asarray([z_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)'''

new = '''            mesh = trimesh.creation.extrude_polygon(component, height=thickness, engine="earcut")
            # Warp the original top/bottom shell first, while its vertices still
            # have unambiguous Z=0 or Z=thickness classification. Subdividing an
            # unwarped extrusion first creates intermediate side vertices; the
            # former binary top-mask then collapsed them onto the top/bottom
            # planes and produced zero-area faces and non-manifold seams.
            vertices = np.asarray(mesh.vertices, dtype=float)
            top_mask = vertices[:, 2] > thickness / 2.0
            z_values = np.asarray([z_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices
            mesh = subdivide_mesh(mesh, max_edge)
            mesh.remove_unreferenced_vertices()
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)'''

if old not in text:
    raise RuntimeError("Rev.P3 solid-mesh patch target not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("REV_P3_SOLID_MESH_PATCHED")
