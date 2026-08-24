from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString

MODULE_PATH = Path("tools/build_revp3_roadqa.py")
spec = importlib.util.spec_from_file_location("revp5_builder_compact", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def summary(geometry):
    result = {
        "type": geometry.geom_type,
        "empty": bool(geometry.is_empty),
        "bounds": list(geometry.bounds) if not geometry.is_empty else None,
        "length": float(getattr(geometry, "length", 0.0)),
    }
    if geometry.is_empty:
        return result
    if geometry.geom_type == "Point":
        result["coordinates"] = [float(geometry.x), float(geometry.y)]
    elif geometry.geom_type in {"LineString", "LinearRing"}:
        result["coordinates"] = [[float(x), float(y)] for x, y in geometry.coords]
    elif hasattr(geometry, "geoms"):
        result["components"] = [summary(item) for item in geometry.geoms]
    return result


def main():
    paths = module.build_paths()
    d3 = np.asarray(paths["D3"][0], dtype=float)
    d5 = np.asarray(paths["D5"][0], dtype=float)
    d3_line = LineString(d3[:, :2])
    d5_line = LineString(d5[:, :2])

    cross_sections = {}
    for y in [150.0, 156.0, 163.0, 170.0, 176.0, 182.0, 189.0, 196.0, 202.0]:
        horizontal = LineString([(0.0, y), (700.0, y)])
        cross_sections[str(int(y))] = summary(d3_line.intersection(horizontal))

    report = {
        "D3_D5_centerline_intersection": summary(d3_line.intersection(d5_line)),
        "D3_horizontal_cross_sections": cross_sections,
        "D5_start": d5[0].tolist(),
        "D5_end": d5[-1].tolist(),
        "D5_last_40_points": d5[-40:].tolist(),
        "D3_points_with_155_le_y_le_195": [
            point.tolist() for point in d3 if 155.0 <= float(point[1]) <= 195.0
        ][::5],
    }
    output = Path("audit/revp5_d3_d5_junction_compact.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
