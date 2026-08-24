from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    d5_spur_xy = sample_line((558.0, 168.0), (580.5, 163.0), 0.6)
    roads["D5"] = [
        assign_linear_z(d5_conn_xy, 108.7, 110.7),
        assign_constant_z(d5_loop_xy, 110.7),
        assign_constant_z(d5_spur_xy, 110.7),
    ]'''
new = '''    # Rev.P5 product circulation is one continuous one-way route.  From the
    # D4 node it rises smoothly to the product terrace, passes south of
    # BLD_09/07/08 and enters D3 transversely at the controlled node
    # (580.5, 163.0).  The final R13 quarter-turn is perpendicular to the D3
    # tangent; consequently the D3-priority boolean creates one clean T-seam,
    # not a collinear overlap and not a disconnected far-side fragment.
    d5_parts = [np.array([[338.0, 128.0]], dtype=float)]
    d5_shift_angle = math.acos(1.0 - 22.0 / (2.0 * 15.0))
    d5_sbend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_shift_angle, +1, 0.70)
    d5_parts.append(d5_sbend[1:])
    d5_parts.append(sample_line(tuple(d5_sbend[-1]), (567.5, 150.0), 0.85)[1:])
    d5_terminal_arc, _ = arc_from_pose((567.5, 150.0), 0.0, 13.0, math.pi / 2.0, 0.55)
    d5_parts.append(d5_terminal_arc[1:])
    d5_xy = dedupe_points(np.vstack(d5_parts))
    roads["D5"] = [assign_linear_z(d5_xy, 108.7, 110.7)]'''
if old not in text:
    raise RuntimeError("Generated branched D5 block not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("REV_P5_D5_T_JUNCTION_PATCHED")
