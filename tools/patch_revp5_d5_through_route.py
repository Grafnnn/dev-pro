from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    d5_spur_xy = sample_line((558.0, 189.0), (570.0, 189.0), 0.6)
    roads["D5"] = [
        assign_linear_z(d5_conn_xy, 108.7, 110.7),
        assign_constant_z(d5_loop_xy, 110.7),
        assign_constant_z(d5_spur_xy, 110.7),
    ]'''
new = '''    # Rev.P5 value-engineered product circulation is one continuous one-way
    # through-route. It serves the south side of BLD_09/07/08, turns north in
    # the 9.9 m clear strip between the BLD_08 foundation and the western edge
    # of the lower D3 hairpin, and joins D3 only once at the y=189 leg. This
    # removes the repeated D3 crossings which split the earlier route into four
    # disconnected road polygons.
    d5_parts = [np.array([[338.0, 128.0]], dtype=float)]
    d5_shift_angle = math.acos(1.0 - 22.0 / (2.0 * 15.0))
    d5_sbend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_shift_angle, +1, 0.70)
    d5_parts.append(d5_sbend[1:])
    d5_parts.append(sample_line(tuple(d5_sbend[-1]), (545.0, 150.0), 0.90)[1:])
    d5_arc_north, _ = arc_from_pose((545.0, 150.0), 0.0, 13.0, math.pi / 2.0, 0.60)
    d5_parts.append(d5_arc_north[1:])
    d5_parts.append(sample_line(tuple(d5_arc_north[-1]), (558.0, 176.0), 0.60)[1:])
    d5_arc_exit, _ = arc_from_pose((558.0, 176.0), math.pi / 2.0, 13.0, -math.pi / 2.0, 0.60)
    d5_parts.append(d5_arc_exit[1:])
    d5_parts.append(sample_line(tuple(d5_arc_exit[-1]), (595.0, 189.0), 0.50)[1:])
    d5_xy = dedupe_points(np.vstack(d5_parts))
    roads["D5"] = [assign_linear_z(d5_xy, 108.7, 110.7)]'''
if old not in text:
    raise RuntimeError("Generated branched D5 block not found")
text = text.replace(old, new, 1)

# D3/D5 vertical-profile split, junction QA and roadside-detail break use the
# D3 centreline at the common node; the D5 centreline continues into the D3
# surface so the final partition produces one transverse, non-overlapping seam.
text = text.replace("570.0, 189.0", "590.0, 189.0")

path.write_text(text, encoding="utf-8")
print("REV_P5_D5_THROUGH_ROUTE_PATCHED")
