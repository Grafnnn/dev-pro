from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = "d5_loop_xy = rounded_rectangle_centerline(351.0, 155.0, 558.0, 199.0, 13.0, 0.9)"
new = "d5_loop_xy = rounded_rectangle_centerline(347.0, 155.0, 562.0, 199.0, 13.0, 0.9)"
if old not in text:
    raise RuntimeError("Generated D5 loop block not found")
text = text.replace(old, new, 1)

# The lower connector ends near (351, 168) and the D3 spur begins near
# (558, 189). The former loop used these points as tangent/pinch contacts,
# producing a non-manifold D5 SUBBASE shell. Expanding the loop four metres on
# each side puts both interfaces inside the carriageway corridor and creates
# finite-area throats. The wider envelope remains clear of BLD_09 to the west
# and BLD_08 to the east.
path.write_text(text, encoding="utf-8")
print("REV_P5_D5_FINITE_THROATS_PATCHED")
