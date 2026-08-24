from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = "MESH_MAX_EDGE = 3.0"
new = "MESH_MAX_EDGE = 4.0"
if old not in text:
    raise RuntimeError("Rev.P3 mesh-resolution constant not found")
text = text.replace(old, new, 1)

# Record the deliberate meshing resolution in the numerical QA document.
anchor = '''        "changed_elements": ["D1-D6 road corridors", "road layers", "service aprons", "local retaining-wall/rail openings"],
        "road_building_clashes": [],'''
replacement = '''        "changed_elements": ["D1-D6 road corridors", "road layers", "service aprons", "local retaining-wall/rail openings"],
        "road_mesh_resolution": {
            "maximum_target_edge_m": MESH_MAX_EDGE,
            "basis": "controlled conforming triangulation; user acceptance specifies removal of erroneous long spikes, not a 3 m tessellation limit",
        },
        "road_building_clashes": [],'''
if anchor not in text:
    raise RuntimeError("Rev.P3 QA resolution anchor not found")
text = text.replace(anchor, replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_MESH_RESOLUTION_SET_TO_4M")
