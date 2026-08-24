from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = "d2_loop_xy = rounded_rectangle_centerline(288.0, 308.0, 439.0, 382.0, 15.0, 0.9)"
new = "d2_loop_xy = rounded_rectangle_centerline(284.0, 308.0, 439.0, 382.0, 15.0, 0.9)"
if old not in text:
    raise RuntimeError("Generated D2 loop block not found")
text = text.replace(old, new, 1)

# The connector quarter-turn ends at approximately (288, 323). Moving the
# loop west tangent to x=284 places that endpoint inside the loop corridor by
# four metres. This converts the former point/pinch contact into a finite-area
# throat for ROAD, SHOULDER and SUBBASE, while the widest structure remains
# clear of BLD_02A whose west foundation edge begins near x=299.
path.write_text(text, encoding="utf-8")
print("REV_P5_D2_FINITE_THROAT_PATCHED")
