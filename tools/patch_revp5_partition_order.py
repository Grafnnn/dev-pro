from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")
wrong = '    order = ["D1", "D4", "D2", "D5", "D3", "D6"]'
correct = '    order = ["D1", "D4", "D2", "D3", "D5", "D6"]'
if wrong in text:
    text = text.replace(wrong, correct, 1)
elif correct not in text:
    raise RuntimeError("Generated road partition order not found")

# D3 is the continuous grade-controlled serpentine and owns the T-junction
# pavement. D5 terminates with a flat butt cap at the D3 boundary. Giving D5
# priority cuts D3 into two engineering-scale components and is prohibited.
path.write_text(text, encoding="utf-8")
print("REV_P5_D3_CONTINUOUS_PARTITION_ORDER_ENFORCED")
