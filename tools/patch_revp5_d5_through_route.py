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
    # through-route rather than a closed annulus with two T-branches. It enters
    # from the D4 node, serves the south side of BLD_09/07/08, moves east far
    # enough to clear the full BLD_08 foundation envelope, and then turns north
    # and east into D3. The previous turn at x=549/562 was cut into two major
    # pieces by the BLD_08 obstacle; the revised 14 m curves at x=560/574 keep
    # every road layer outside the fixed foundation.
    d5_parts = [np.array([[338.0, 128.0]], dtype=float)]
    d5_shift_angle = math.acos(1.0 - 22.0 / (2.0 * 15.0))
    d5_sbend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_shift_angle, +1, 0.70)
    d5_parts.append(d5_sbend[1:])
    d5_parts.append(sample_line(tuple(d5_sbend[-1]), (560.0, 150.0), 0.90)[1:])
    d5_arc_east, _ = arc_from_pose((560.0, 150.0), 0.0, 14.0, math.pi / 2.0, 0.65)
    d5_parts.append(d5_arc_east[1:])
    d5_parts.append(sample_line(tuple(d5_arc_east[-1]), (574.0, 175.0), 0.65)[1:])
    d5_arc_exit, _ = arc_from_pose((574.0, 175.0), math.pi / 2.0, 14.0, -math.pi / 2.0, 0.65)
    d5_parts.append(d5_arc_exit[1:])
    d5_parts.append(sample_line(tuple(d5_arc_exit[-1]), (595.0, 189.0), 0.50)[1:])
    d5_xy = dedupe_points(np.vstack(d5_parts))
    roads["D5"] = [assign_linear_z(d5_xy, 108.7, 110.7)]'''
if old not in text:
    raise RuntimeError("Generated branched D5 block not found")
text = text.replace(old, new, 1)

# D3/D5 vertical-profile split, junction QA and roadside-detail break use the
# D3 centreline at the common node; the D5 centreline extends farther east so
# the clipped edge is a clean transverse seam rather than a detached crescent.
text = text.replace("570.0, 189.0", "590.0, 189.0")

path.write_text(text, encoding="utf-8")
print("REV_P5_D5_THROUGH_ROUTE_PATCHED")
