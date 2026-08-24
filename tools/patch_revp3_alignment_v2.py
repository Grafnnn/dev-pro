from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    d3_parts = [sample_line((439.0, 345.0), (589.0, 345.0), 1.2)]
    point = np.array([589.0, 345.0])
    heading = 0.0
    for index in range(9):
        signed = -math.pi if index % 2 == 0 else math.pi
        arc, heading = arc_from_pose(point, heading, 14.5, signed, 0.75)
        d3_parts.append(arc[1:])
        point = arc[-1]
        if index < 8:
            target_x = 570.0 if index % 2 == 0 else 589.0
            line = sample_line(tuple(point), (target_x, float(point[1])), 0.9)
            d3_parts.append(line[1:])
            point = line[-1]
    d3_parts.append(sample_line(tuple(point), (577.0, 84.0), 0.6)[1:])
    d3_xy = dedupe_points(np.vstack(d3_parts))'''

new = '''    d3_parts = [sample_line((439.0, 345.0), (590.0, 345.0), 1.2)]
    point = np.array([590.0, 345.0])
    heading = 0.0
    for index in range(9):
        signed = -math.pi if index % 2 == 0 else math.pi
        arc, heading = arc_from_pose(point, heading, 13.0, signed, 0.70)
        d3_parts.append(arc[1:])
        point = arc[-1]
        if index < 8:
            target_x = 580.5 if index % 2 == 0 else 590.0
            line = sample_line(tuple(point), (target_x, float(point[1])), 0.75)
            d3_parts.append(line[1:])
            point = line[-1]
    final_arc, heading = arc_from_pose(point, heading, 13.0, math.pi / 2.0, 0.70)
    d3_parts.append(final_arc[1:])
    d3_parts.append(sample_line(tuple(final_arc[-1]), (577.0, 84.0), 0.55)[1:])
    d3_xy = dedupe_points(np.vstack(d3_parts))'''

if old not in text:
    raise RuntimeError("Generated D3 Rev.P3 block not found")
text = text.replace(old, new, 1)

# The original D5 connector retained a 12 m theoretical curve which evaluated
# below 12 m after discretisation. Increase it to 13 m and shift the loop's
# west tangent to x=351 m, keeping a genuinely tangent and continuous route.
replacements = [
    (
        '    arc, _ = arc_from_pose((338.0, 128.0), 0.0, 12.0, math.pi / 2.0, 0.7)',
        '    arc, _ = arc_from_pose((338.0, 128.0), 0.0, 13.0, math.pi / 2.0, 0.7)',
        "D5 connector radius",
    ),
    (
        '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 168.0), 1.0)[1:])',
        '    d5_connector_parts.append(sample_line(tuple(arc[-1]), (351.0, 168.0), 1.0)[1:])',
        "D5 tangent endpoint",
    ),
    (
        'd5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 199.0, 13.0, 0.9)',
        'd5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)',
        "D5 loop west tangent",
    ),
]
for old_text, new_text, label in replacements:
    if old_text not in text:
        raise RuntimeError(f"Generated patch target not found: {label}")
    text = text.replace(old_text, new_text, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_ALIGNMENT_V2_PATCHED")
