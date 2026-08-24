from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")
old = '''        if asphalt_components != 1:
            raise RuntimeError(f"{code} asphalt contour has {asphalt_components} components")'''
new = '''        if asphalt_components != 1:
            component_details = [
                {
                    "area_m2": float(item.area),
                    "bounds": [float(value) for value in item.bounds],
                }
                for item in sorted(iter_polygons(asphalt_polys[code]), key=lambda value: value.area, reverse=True)
            ]
            raise RuntimeError(
                f"{code} asphalt contour has {asphalt_components} components: "
                + json.dumps(component_details, ensure_ascii=False)
            )'''
if old not in text:
    raise RuntimeError("Road component acceptance block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P5_COMPONENT_DIAGNOSTICS_PATCHED")
