from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# Insert plan-topology validation before layer/building collision checks.
anchor = '''    all_layer_polys = {
        "ROAD": asphalt_polys,
        "SHOULDER": shoulder_polys,
        "SUBBASE": subbase_polys,
    }
    layer_clashes = []'''
replacement = '''    all_layer_polys = {
        "ROAD": asphalt_polys,
        "SHOULDER": shoulder_polys,
        "SUBBASE": subbase_polys,
    }
    plan_topology = {}
    for layer_name, layer_by_road in all_layer_polys.items():
        plan_topology[layer_name] = {}
        for code, geometry in layer_by_road.items():
            components = list(iter_polygons(geometry))
            valid = bool(geometry.is_valid)
            simple = all(bool(component.exterior.is_simple) and all(ring.is_simple for ring in component.interiors) for component in components)
            if not valid or not simple or len(components) != 1:
                raise RuntimeError(
                    f"Invalid/self-intersecting/disconnected plan geometry {layer_name}/{code}: "
                    f"valid={valid}, simple={simple}, components={len(components)}"
                )
            plan_topology[layer_name][code] = {
                "valid": valid,
                "simple_boundary": simple,
                "connected_components": len(components),
                "self_intersections": 0,
            }
    layer_clashes = []'''
if anchor not in text:
    raise RuntimeError("Plan-topology patch anchor not found")
text = text.replace(anchor, replacement, 1)

# Add component-level normal orientation and strict manifold checks.
anchor = '''        quality = mesh_quality(mesh)
        changed_quality[name] = quality
        if not quality["finite_coordinates"]:
            raise RuntimeError(f"Non-finite coordinates in {name}")
        if quality["zero_area_faces"] != 0 or quality["duplicate_faces"] != 0:
            raise RuntimeError(f"Degenerate/duplicate faces in {name}: {quality}")
        if not quality["winding_consistent"]:
            raise RuntimeError(f"Inconsistent normals in {name}")
        if quality["max_edge_m"] > MESH_MAX_EDGE * 1.55:
            raise RuntimeError(f"Long edge in {name}: {quality['max_edge_m']:.3f} m")'''
replacement = '''        quality = mesh_quality(mesh)
        components = mesh.split(only_watertight=False)
        quality["component_count"] = int(len(components))
        quality["inverted_normal_components"] = int(
            sum(1 for component in components if component.is_watertight and float(component.volume) < -1.0e-9)
        )
        changed_quality[name] = quality
        if not quality["finite_coordinates"]:
            raise RuntimeError(f"Non-finite coordinates in {name}")
        if quality["zero_area_faces"] != 0 or quality["duplicate_faces"] != 0:
            raise RuntimeError(f"Degenerate/duplicate faces in {name}: {quality}")
        if not quality["watertight"] or quality["non_manifold_edges"] != 0:
            raise RuntimeError(f"Non-manifold/open topology in {name}: {quality}")
        if not quality["winding_consistent"] or quality["inverted_normal_components"] != 0:
            raise RuntimeError(f"Inconsistent/inverted normals in {name}: {quality}")
        if quality["max_edge_m"] > MESH_MAX_EDGE * 1.55:
            raise RuntimeError(f"Long edge in {name}: {quality['max_edge_m']:.3f} m")'''
if anchor not in text:
    raise RuntimeError("Mesh-quality patch anchor not found")
text = text.replace(anchor, replacement, 1)

# Record the stronger topology checks in the QA document and acceptance block.
anchor = '''        "mesh_quality": changed_quality,
        "removed_revp2_geometry": sorted(removed),'''
replacement = '''        "plan_topology": plan_topology,
        "mesh_quality": changed_quality,
        "removed_revp2_geometry": sorted(removed),'''
if anchor not in text:
    raise RuntimeError("QA plan-topology insertion anchor not found")
text = text.replace(anchor, replacement, 1)

anchor = '''            "zero_area_faces": 0,
            "duplicate_faces": 0,
            "inconsistent_normals": 0,
            "status": "PASS",'''
replacement = '''            "plan_self_intersections": 0,
            "non_manifold_edges": 0,
            "zero_area_faces": 0,
            "duplicate_faces": 0,
            "inverted_normal_components": 0,
            "inconsistent_normals": 0,
            "status": "PASS",'''
if anchor not in text:
    raise RuntimeError("Acceptance hardening anchor not found")
text = text.replace(anchor, replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_QA_HARDENED")
