from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    return text.replace(old, new, 1)


path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# Replace the prior cubic smoothstep with a grade-integrated profile. The
# vertical grade ramps linearly from zero, remains constant, and ramps back to
# zero. This preserves smooth vertical tangency while guaranteeing <=6%.
old_vertical = '''def assign_linear_z(path_xy: np.ndarray, z0: float, z1: float) -> np.ndarray:\n    path_xy = np.asarray(path_xy, dtype=float)\n    temp = np.column_stack([path_xy[:, :2], np.zeros(len(path_xy))])\n    station = cumulative_xy(temp)\n    if station[-1] < 1.0e-9:\n        z = np.full(len(path_xy), z0)\n    else:\n        t = station / station[-1]\n        z = z0 + (z1 - z0) * (t * t * (3.0 - 2.0 * t))\n    return np.column_stack([path_xy[:, :2], z])'''
new_vertical = '''def assign_linear_z(path_xy: np.ndarray, z0: float, z1: float) -> np.ndarray:\n    path_xy = np.asarray(path_xy, dtype=float)\n    temp = np.column_stack([path_xy[:, :2], np.zeros(len(path_xy))])\n    station = cumulative_xy(temp)\n    length = float(station[-1])\n    delta = float(z1 - z0)\n    if length < 1.0e-9 or abs(delta) < 1.0e-12:\n        z = np.full(len(path_xy), z0)\n    else:\n        desired_transition = min(40.0, max(5.0, 0.12 * length))\n        maximum_transition = max(0.0, length - abs(delta) / MAX_GRADE)\n        transition = min(desired_transition, 0.90 * maximum_transition)\n        if transition < 1.0e-6:\n            grade = delta / length\n            z = z0 + grade * station\n        else:\n            grade = delta / (length - transition)\n            z = np.empty(len(station), dtype=float)\n            sign = 1.0 if grade >= 0.0 else -1.0\n            magnitude = abs(grade)\n            for index, s in enumerate(station):\n                if s <= transition:\n                    rise = magnitude * s * s / (2.0 * transition)\n                elif s <= length - transition:\n                    rise = magnitude * transition / 2.0 + magnitude * (s - transition)\n                else:\n                    u = s - (length - transition)\n                    rise = magnitude * transition / 2.0 + magnitude * (length - 2.0 * transition) + magnitude * (u - u * u / (2.0 * transition))\n                z[index] = z0 + sign * rise\n            z[-1] = z1\n    return np.column_stack([path_xy[:, :2], z])'''
text = replace_once(text, old_vertical, new_vertical, "smooth grade-limited vertical profiles")

# D1 starts its controlled S-bend immediately, so the full subbase and the
# conservative swept envelopes clear the fixed gatehouse.
text = replace_once(
    text,
    '    d1_parts = [sample_line((167.0, 305.0), (176.0, 305.0), 1.0)]\n    s1, _ = sample_s_bend((176.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    '    d1_parts = [np.array([[167.0, 305.0]], dtype=float)]\n    s1, _ = sample_s_bend((167.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)',
    "D1 early gatehouse bypass",
)

# D2 is expanded south/east/north and uses a 13 m tangent connector plus
# 15 m loop corners. The resulting widest subbase clears BLD_02/02A and the
# discretized numerical radius remains strictly above 12 m.
text = replace_once(
    text,
    '    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]\n    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 14.5, math.pi / 2.0, 0.8)\n    d2_connector_parts.append(arc[1:])\n    d2_connector_parts.append(sample_line(tuple(arc[-1]), (290.0, 324.5), 0.5)[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(290.0, 310.0, 436.0, 379.0, 14.5, 0.9)',
    '    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]\n    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 13.0, math.pi / 2.0, 0.7)\n    d2_connector_parts.append(arc[1:])\n    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))\n    d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)',
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

# D5 north side is lowered to clear BLD_05. A 13 m loop corner keeps the
# widest road structure out of the top-right corner of BLD_08 and leaves a
# numerical radius margin above the 12 m criterion. The connector ends at the
# corresponding west tangent y=168 m.
text = replace_once(
    text,
    '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 170.0), 1.0)[1:])',
    '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 168.0), 1.0)[1:])',
    "D5 connector tangent",
)
text = replace_once(
    text,
    'd5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 202.0, 15.0, 0.9)',
    'd5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 199.0, 13.0, 0.9)',
    "D5 fixed-building clearance",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_PREBUILD_PATCHED")
