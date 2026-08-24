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
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P3_D3_ALIGNMENT_V2_PATCHED")
