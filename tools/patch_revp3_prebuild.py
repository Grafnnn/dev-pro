from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    return text.replace(old, new, 1)


path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# D1 starts its controlled S-bend immediately, so the full subbase and the
# conservative swept envelopes clear the fixed gatehouse.
text = replace_once(
    text,
    '    d1_parts = [sample_line((167.0, 305.0), (176.0, 305.0), 1.0)]\n    s1, _ = sample_s_bend((176.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    '    d1_parts = [np.array([[167.0, 305.0]], dtype=float)]\n    s1, _ = sample_s_bend((167.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    "D1 early gatehouse bypass",
)

# D2 is expanded south/east/north and uses a 12 m tangent connector plus
# 15 m loop corners.  The resulting widest subbase clears BLD_02/02A.
text = replace_once(
    text,
    '    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]\n    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 14.5, math.pi / 2.0, 0.8)\n    d2_connector_parts.append(arc[1:])\n    d2_connector_parts.append(sample_line(tuple(arc[-1]), (290.0, 324.5), 0.5)[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(290.0, 310.0, 436.0, 379.0, 14.5, 0.9)',
    '    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]\n    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 12.0, math.pi / 2.0, 0.7)\n    d2_connector_parts.append(arc[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(287.0, 307.0, 439.0, 382.0, 15.0, 0.9)',
    "D2 expanded fixed-building clearance",
)

# D3 is rebuilt as nine explicit 14.5 m U-turns between x=570 and x=589.
# The full subbase remains inside x<=608 and clears BLD_08.
old_d3 = '''    d3_parts = [sample_line((436.0, 345.0), (568.0, 345.0), 1.2)]\n    point = np.array([568.0, 345.0])\n    heading = 0.0\n    for index in range(7):\n        signed = -math.pi if index % 2 == 0 else math.pi\n        arc, heading = arc_from_pose(point, heading, 17.5, signed, 0.8)\n        d3_parts.append(arc[1:])\n        point = arc[-1]\n        target_x = 542.0 if index % 2 == 0 else 568.0\n        line = sample_line(tuple(point), (target_x, float(point[1])), 1.0)\n        d3_parts.append(line[1:])\n        point = line[-1]\n    final_arc, heading = arc_from_pose(point, heading, 13.0, math.pi / 2.0, 0.7)\n    d3_parts.append(final_arc[1:])\n    d3_parts.append(sample_line(tuple(final_arc[-1]), (555.0, 85.0), 0.5)[1:])\n    d3_xy = dedupe_points(np.vstack(d3_parts))'''
new_d3 = '''    d3_parts = [sample_line((439.0, 345.0), (589.0, 345.0), 1.2)]\n    point = np.array([589.0, 345.0])\n    heading = 0.0\n    for index in range(9):\n        signed = -math.pi if index % 2 == 0 else math.pi\n        arc, heading = arc_from_pose(point, heading, 14.5, signed, 0.75)\n        d3_parts.append(arc[1:])\n        point = arc[-1]\n        if index < 8:\n            target_x = 570.0 if index % 2 == 0 else 589.0\n            line = sample_line(tuple(point), (target_x, float(point[1])), 0.9)\n            d3_parts.append(line[1:])\n            point = line[-1]\n    d3_parts.append(sample_line(tuple(point), (577.0, 84.0), 0.6)[1:])\n    d3_xy = dedupe_points(np.vstack(d3_parts))'''
text = replace_once(text, old_d3, new_d3, "D3 nine-switchback controlled alignment")

# D2-D3 intentional junction follows the relocated east side of the D2 loop.
text = replace_once(
    text,
    '("D2-D3", "D2", "D3", (436.0, 345.0)),',
    '("D2-D3", "D2", "D3", (439.0, 345.0)),',
    "D2-D3 junction",
)
text = replace_once(
    text,
    'Point(436.0, 345.0).buffer(8.0),',
    'Point(439.0, 345.0).buffer(8.0),',
    "D2-D3 curb break",
)

# D5 north side is lowered to clear BLD_05. A 12 m loop corner keeps the
# widest road structure out of the top-right corner of BLD_08 while meeting
# the minimum-radius acceptance criterion. The connector ends tangentially at
# the new west-side tangent point y=167 m.
text = replace_once(
    text,
    '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 170.0), 1.0)[1:])',
    '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 167.0), 1.0)[1:])',
    "D5 connector tangent",
)
text = replace_once(
    text,
    'd5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 202.0, 15.0, 0.9)',
    'd5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 199.0, 12.0, 0.9)',
    "D5 fixed-building clearance",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_PREBUILD_PATCHED")
