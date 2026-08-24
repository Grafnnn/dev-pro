from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")
old = '    order = ["D1", "D4", "D2", "D3", "D5", "D6"]'
new = '    order = ["D1", "D4", "D2", "D5", "D3", "D6"]'
if old not in text:
    raise RuntimeError("Generated road partition order not found")
text = text.replace(old, new, 1)

# D5 owns the finite-width D3 connection throat. D3 is then clipped only at
# the side junction envelope; its principal serpentine remains connected and
# is verified by the existing connected-component acceptance check. This
# avoids producing a pinched D5 polygon when D3 is assigned first.
path.write_text(text, encoding="utf-8")
print("REV_P5_PARTITION_ORDER_PATCHED")
