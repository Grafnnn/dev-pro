from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# D2: replace the branch into the loop's lower-left rounded corner with a
# shallow direct approach that overlaps the straight lower loop axis. This
# removes the repeated pinch vertex at x=296.9/y=314.9 while preserving the
# fixed D1 junction, nominal width, 15 m loop radii and all building clearances.
old_d2 = '''    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]
    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 13.0, math.pi / 2.0, 0.7)
    d2_connector_parts.append(arc[1:])
    d2_connector_parts.append(sample_line(tuple(arc[-1]), (288.0, 328.0), 0.5)[1:])
    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))
    d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)'''
new_d2 = '''    d2_conn_xy = sample_line((245.0, 310.0), (315.0, 308.0), 0.75)
    d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)'''
if old_d2 not in text:
    raise RuntimeError("Generated D2 connector redesign anchor not found")
text = text.replace(old_d2, new_d2, 1)

# D5: use a radius-15 S-bend from the D4 junction to the loop's straight lower
# axis, then overlap the loop centreline. This eliminates the analogous pinch
# vertex at x=357.4/y=162.4 and keeps all local radii >=12 m.
old_d5 = '''    d5_connector_parts = [sample_line((338.0, 128.0), (338.0, 128.0), 1.0)]
    arc, _ = arc_from_pose((338.0, 128.0), 0.0, 13.0, math.pi / 2.0, 0.7)
    d5_connector_parts.append(arc)
    d5_connector_parts.append(sample_line(tuple(arc[-1]), (351.0, 173.0), 0.5)[1:])
    d5_conn_xy = dedupe_points(np.vstack(d5_connector_parts))
    d5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)'''
new_d5 = '''    d5_shift = 27.0
    d5_angle = math.acos(1.0 - d5_shift / (2.0 * 15.0))
    d5_s_bend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_angle, +1, 0.70)
    d5_connector_parts = [d5_s_bend]
    d5_connector_parts.append(sample_line(tuple(d5_s_bend[-1]), (380.0, 155.0), 0.60)[1:])
    d5_conn_xy = dedupe_points(np.vstack(d5_connector_parts))
    d5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)'''
if old_d5 not in text:
    raise RuntimeError("Generated D5 connector redesign anchor not found")
text = text.replace(old_d5, new_d5, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_CONNECTORS_REDESIGNED")
