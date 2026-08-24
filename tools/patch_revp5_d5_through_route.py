from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    d5_spur_xy = sample_line((558.0, 168.0), (580.5, 163.0), 0.6)
    roads["D5"] = [
        assign_linear_z(d5_conn_xy, 108.7, 110.7),
        assign_constant_z(d5_loop_xy, 110.7),
        assign_constant_z(d5_spur_xy, 110.7),
    ]'''
new = '''    # Rev.P5 product circulation is one continuous one-way route. From the
    # D4 node it rises smoothly to the product terrace, passes south of
    # BLD_09/07/08 and terminates at the first western crossing of the accepted
    # D3 centreline. The exact intersection is (557.0394602, 150.0). Ending the
    # D5 axis at this first crossing prevents it from entering the stacked D3
    # hairpins and eliminates every disconnected far-side road fragment.
    d5_node_xy = np.array([557.0394602011489, 150.0], dtype=float)
    d5_parts = [np.array([[338.0, 128.0]], dtype=float)]
    d5_shift_angle = math.acos(1.0 - 22.0 / (2.0 * 15.0))
    d5_sbend, _ = sample_s_bend((338.0, 128.0), 0.0, 15.0, d5_shift_angle, +1, 0.70)
    d5_parts.append(d5_sbend[1:])
    d5_parts.append(sample_line(tuple(d5_sbend[-1]), tuple(d5_node_xy), 0.75)[1:])
    d5_xy = dedupe_points(np.vstack(d5_parts))
    roads["D5"] = [assign_linear_z(d5_xy, 108.7, 109.0)]'''
if old not in text:
    raise RuntimeError("Generated branched D5 block not found")
text = text.replace(old, new, 1)

# Align the D3 vertical-profile break, junction clear-zone and numerical seam
# check with the actual first centreline crossing used by the new D5 route.
text = text.replace("580.5, 163.0", "557.0394602011489, 150.0")

# The lower D3 reach between the junction and the site toe is comparatively
# short.  A 110.7 m junction created a 7.346% local grade.  The controlled
# junction elevation 109.0 m keeps both D3 reaches below the 6% acceptance
# limit while matching the new D5 profile at the common seam.
text = text.replace(
    "assign_linear_z(d3_xy[: d3_junction_index + 1], 133.7, 110.7)",
    "assign_linear_z(d3_xy[: d3_junction_index + 1], 133.7, 109.0)",
)
text = text.replace(
    "assign_linear_z(d3_xy[d3_junction_index:], 110.7, 102.2)",
    "assign_linear_z(d3_xy[d3_junction_index:], 109.0, 102.2)",
)

path.write_text(text, encoding="utf-8")
print("REV_P5_D5_FIRST_CROSSING_AND_GRADE_PATCHED")
