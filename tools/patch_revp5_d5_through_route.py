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
    # from D4, serves the south side of BLD_09/07/08 and exits to D3. This
    # removes the pinched/non-manifold loop topology and also reduces paved area.
    d5_parts = [np.array([[338.0, 128.0]], dtype=float)]
    d5_shift_angle = math.acos(1.0 - 22.0 / (2.0 * 15.0))
    d5_sbend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_shift_angle, +1, 0.70)
    d5_parts.append(d5_sbend[1:])
    d5_parts.append(sample_line(tuple(d5_sbend[-1]), (549.0, 150.0), 0.90)[1:])
    d5_arc_east, d5_heading = arc_from_pose((549.0, 150.0), 0.0, 13.0, math.pi / 2.0, 0.65)
    d5_parts.append(d5_arc_east[1:])
    d5_parts.append(sample_line(tuple(d5_arc_east[-1]), (562.0, 176.0), 0.65)[1:])
    d5_arc_exit, _ = arc_from_pose((562.0, 176.0), math.pi / 2.0, 13.0, -math.pi / 2.0, 0.65)
    d5_parts.append(d5_arc_exit[1:])
    d5_xy = dedupe_points(np.vstack(d5_parts))
    roads["D5"] = [assign_linear_z(d5_xy, 108.7, 110.7)]'''
if old not in text:
    raise RuntimeError("Generated branched D5 block not found")
text = text.replace(old, new, 1)

# Align all generated D3/D5 node checks and roadside-detail clear zones with
# the smooth D5 exit point. The D3 centreline is close enough that the final
# non-overlapping partition has a common finite-width junction.
text = text.replace("570.0, 189.0", "575.0, 189.0")

path.write_text(text, encoding="utf-8")
print("REV_P5_D5_THROUGH_ROUTE_PATCHED")
