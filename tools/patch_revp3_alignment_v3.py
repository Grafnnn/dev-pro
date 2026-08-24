from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"Rev.P3 v3 patch target not found: {label}")
    text = text.replace(old, new, 1)


# Give D5 a lower southern side and a genuine spur to the D3 tangent at
# (580.5, 163).  The spur and the loop remain one connected principal contour.
replace_once(
    'd5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)',
    'd5_loop_xy = rounded_rectangle_centerline(351.0, 150.0, 558.0, 199.0, 13.0, 0.9)',
    "D5 lower loop side",
)
replace_once(
    '    roads["D5"] = [assign_linear_z(d5_conn_xy, 108.7, 110.7), assign_constant_z(d5_loop_xy, 110.7)]',
    '    d5_spur_xy = sample_line((558.0, 163.0), (580.5, 163.0), 0.65)\n'
    '    roads["D5"] = [\n'
    '        assign_linear_z(d5_conn_xy, 108.7, 110.7),\n'
    '        assign_constant_z(d5_loop_xy, 110.7),\n'
    '        assign_constant_z(d5_spur_xy, 110.7),\n'
    '    ]',
    "D5 spur to D3",
)

# Force the D3 vertical profile through the D5 node so the common junction has
# no inherited ~0.7 m step.  Each half uses the smooth grade-limited profile.
replace_once(
    '    roads["D3"] = [assign_linear_z(d3_xy, 133.7, 102.2)]',
    '    d3_junction_index = int(np.argmin(np.linalg.norm(d3_xy[:, :2] - np.array([580.5, 163.0]), axis=1)))\n'
    '    d3_upper = assign_linear_z(d3_xy[: d3_junction_index + 1], 133.7, 110.7)\n'
    '    d3_lower = assign_linear_z(d3_xy[d3_junction_index:], 110.7, 102.2)\n'
    '    d3_profile = np.vstack([d3_upper, d3_lower[1:]])\n'
    '    roads["D3"] = [d3_profile]',
    "D3 piecewise vertical profile",
)

# Priority is chosen so the continuous D3 spine is never split by lower loops;
# later roads are trimmed at the shared nodes rather than overlaid coplanarly.
replace_once(
    '    order = ["D1", "D4", "D2", "D5", "D6", "D3"]',
    '    order = ["D1", "D4", "D2", "D3", "D5", "D6"]',
    "road partition order",
)

replace_once(
    '            Point(439.0, 345.0).buffer(8.0),\n            Point(338.0, 128.0).buffer(10.0),',
    '            Point(439.0, 345.0).buffer(8.0),\n'
    '            Point(580.5, 163.0).buffer(9.0),\n'
    '            Point(338.0, 128.0).buffer(10.0),',
    "D3-D5 roadside-detail break",
)

replace_once(
    '        ("D2-D3", "D2", "D3", (439.0, 345.0)),\n'
    '        ("D4-D5", "D4", "D5", (338.0, 128.0)),',
    '        ("D2-D3", "D2", "D3", (439.0, 345.0)),\n'
    '        ("D3-D5", "D3", "D5", (580.5, 163.0)),\n'
    '        ("D4-D5", "D4", "D5", (338.0, 128.0)),',
    "D3-D5 junction QA",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_ALIGNMENT_V3_PATCHED")
