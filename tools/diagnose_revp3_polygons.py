from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import requests
import trimesh
from shapely.ops import unary_union

MODULE_PATH = Path("tools/build_revp3_roadqa.py")
spec = importlib.util.spec_from_file_location("revp3_builder", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def download(url: str, path: Path) -> None:
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with path.open("wb") as f:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def component_rows(geometry):
    rows = []
    for index, polygon in enumerate(module.iter_polygons(geometry)):
        rows.append(
            {
                "index": index,
                "area_m2": float(polygon.area),
                "bounds": list(map(float, polygon.bounds)),
                "centroid": [float(polygon.centroid.x), float(polygon.centroid.y)],
                "perimeter_m": float(polygon.length),
            }
        )
    rows.sort(key=lambda row: row["area_m2"], reverse=True)
    return rows


def main() -> None:
    source_path = Path("revp2_for_polygon_diag.glb")
    download(module.SOURCE_URL, source_path)
    source = trimesh.load(str(source_path), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)

    paths = module.build_paths()
    profiles = {
        code: module.RoadProfile(code=code, width=module.WIDTHS[code], paths=road_paths)
        for code, road_paths in paths.items()
    }
    obstacles = []
    for name, mesh in source.geometry.items():
        if module.re.match(r"BLD_.*_FOUNDATION_DECK$", name, module.re.I) or module.re.match(
            r"BLD_.*_(?:WALL_PANELS|SHELL)$", name, module.re.I
        ):
            obstacles.append(module.polygon_from_mesh_xy(mesh))
    obstacle_union = unary_union(obstacles).buffer(0.02)

    asphalt = module.partition_polygons(profiles, 0.0, obstacle_union)
    shoulder = module.partition_polygons(profiles, 1.5, obstacle_union)
    subbase = module.partition_polygons(profiles, 3.0, obstacle_union)

    report = {
        "partition_order_note": "read from runtime-patched module",
        "roads": {},
    }
    for code in module.WIDTHS:
        report["roads"][code] = {
            "raw": component_rows(profiles[code].polygon(module.WIDTHS[code])),
            "asphalt": component_rows(asphalt[code]),
            "shoulder": component_rows(shoulder[code]),
            "subbase": component_rows(subbase[code]),
        }
    Path("revp3_polygon_diagnostics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
