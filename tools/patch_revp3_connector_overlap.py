from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# Exact tangent endpoint contact between two independently buffered centerline
# paths produced a pinched polygon vertex and one vertical edge shared by four
# faces after extrusion. Extend each connector along the loop axis by 5 m. The
# centerlines now overlap, so unary_union removes the internal seam instead of
# exporting coincident walls. Alignment, widths and building clearances remain
# unchanged.

d2_anchor = '''    d2_connector_parts.append(arc[1:])
    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))
    d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)'''
d2_replacement = '''    d2_connector_parts.append(arc[1:])
    d2_connector_parts.append(sample_line(tuple(arc[-1]), (288.0, 328.0), 0.5)[1:])
    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))
    d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)'''
if d2_anchor not in text:
    raise RuntimeError("Generated D2 connector/loop seam anchor not found")
text = text.replace(d2_anchor, d2_replacement, 1)

d5_anchor = '''    d5_connector_parts.append(sample_line(tuple(arc[-1]), (351.0, 168.0), 1.0)[1:])
    d5_conn_xy = dedupe_points(np.vstack(d5_connector_parts))
    d5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)'''
d5_replacement = '''    d5_connector_parts.append(sample_line(tuple(arc[-1]), (351.0, 173.0), 0.5)[1:])
    d5_conn_xy = dedupe_points(np.vstack(d5_connector_parts))
    d5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)'''
if d5_anchor not in text:
    raise RuntimeError("Generated D5 connector/loop seam anchor not found")
text = text.replace(d5_anchor, d5_replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_CONNECTOR_OVERLAP_PATCHED")
