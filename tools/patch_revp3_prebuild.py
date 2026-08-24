from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    return text.replace(old, new, 1)


path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '    d1_parts = [sample_line((167.0, 305.0), (176.0, 305.0), 1.0)]\n    s1, _ = sample_s_bend((176.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    '    d1_parts = [np.array([[167.0, 305.0]], dtype=float)]\n    s1, _ = sample_s_bend((167.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    "D1 early gatehouse bypass",
)

text = replace_once(
    text,
    '    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 14.5, math.pi / 2.0, 0.8)\n    d2_connector_parts.append(arc[1:])\n    d2_connector_parts.append(sample_line(tuple(arc[-1]), (290.0, 324.5), 0.5)[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(290.0, 310.0, 436.0, 379.0, 14.5, 0.9)',
    '    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 15.0, math.pi / 2.0, 0.8)\n    d2_connector_parts.append(arc[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(290.0, 310.0, 436.0, 379.0, 15.0, 0.9)',
    "D2 tangent connector and 15 m corners",
)

text = replace_once(
    text,
    '        point = arc[-1]\n        target_x = 542.0 if index % 2 == 0 else 568.0\n        line = sample_line(tuple(point), (target_x, float(point[1])), 1.0)\n        d3_parts.append(line[1:])\n        point = line[-1]\n    final_arc, heading = arc_from_pose(point, heading, 13.0, math.pi / 2.0, 0.7)',
    '        point = arc[-1]\n        if index < 6:\n            target_x = 542.0 if index % 2 == 0 else 568.0\n            line = sample_line(tuple(point), (target_x, float(point[1])), 1.0)\n            d3_parts.append(line[1:])\n            point = line[-1]\n    final_arc, heading = arc_from_pose(point, heading, 13.0, math.pi / 2.0, 0.7)',
    "D3 final switchback termination",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_PREBUILD_PATCHED")
