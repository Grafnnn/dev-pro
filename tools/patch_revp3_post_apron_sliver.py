from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}
'''
new = '''    shoulder_polys = {
        code: _clean_boolean_micro_slivers(
            polygon.difference(apron_union).buffer(0), code, 1.5
        )
        for code, polygon in shoulder_polys.items()
    }
    subbase_polys = {
        code: _clean_boolean_micro_slivers(
            polygon.difference(apron_union).buffer(0), code, 3.0
        )
        for code, polygon in subbase_polys.items()
    }
'''

if old not in text:
    raise RuntimeError("Post-apron road-layer dictionary block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P3_POST_APRON_SLIVER_PATCHED")
