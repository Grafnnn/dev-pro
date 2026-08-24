from __future__ import annotations

import importlib.util
import json
import re
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


def download(url: str, target: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with target.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)


def component_rows(geometry):
    rows = []
    for index, polygon in enumerate(module.iter_polygons(geometry)):
        rows.append(
            {
                "index": index,
                "area_m2": float(polygon.area),
                "bounds": [float(value) for value in polygon.bounds],
                "centroid": [float(polygon.centroid.x), float(polygon.centroid.y)],
                "perimeter_m": float(polygon.length),
            }
        )
    rows.sort(key=lambda row: row["area_m2"], reverse=True)
    return rows


def main() -> None:
    source_path = Path("revp2_for_post_apron_diag.glb")
    download(module.SOURCE_URL, source_path)
    source = trimesh.load(str(source_path), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)

    paths = module.build_paths()
    profiles = {
        code: module.RoadProfile(code=code, width=module.WIDTHS[code], paths=road_paths)
        for code, road_paths in paths.items()
    }

    foundation_polys = {}
    wall_polys = {}
    for name, mesh in source.geometry.items():
        if re.match(r"BLD_.*_FOUNDATION_DECK$", name, re.I):
            foundation_polys[name] = module.polygon_from_mesh_xy(mesh)
        elif re.match(r"BLD_.*_(?:WALL_PANELS|SHELL)$", name, re.I):
            wall_polys[name] = module.polygon_from_mesh_xy(mesh)
    obstacles = unary_union(list(foundation_polys.values()) + list(wall_polys.values())).buffer(0.02)

    asphalt = module.partition_polygons(profiles, 0.0, obstacles)
    asphalt_union = unary_union(list(asphalt.values())).buffer(0)
    aprons, apron_info, _ = module.build_aprons(source, asphalt_union, profiles, obstacles)
    apron_union = unary_union(list(aprons.values())).buffer(0)

    shoulder_before = module.partition_polygons(profiles, 1.5, obstacles)
    subbase_before = module.partition_polygons(profiles, 3.0, obstacles)
    shoulder_after = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_before.items()}
    subbase_after = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_before.items()}

    report = {
        "aprons": {
            code: {
                "area_m2": float(polygon.area),
                "bounds": [float(value) for value in polygon.bounds],
                "info": apron_info[code],
            }
            for code, polygon in aprons.items()
        },
        "roads": {},
    }
    for code in module.WIDTHS:
        report["roads"][code] = {
            "shoulder_before_apron": component_rows(shoulder_before[code]),
            "shoulder_after_apron": component_rows(shoulder_after[code]),
            "subbase_before_apron": component_rows(subbase_before[code]),
            "subbase_after_apron": component_rows(subbase_after[code]),
            "intersecting_aprons": [
                {
                    "apron": apron_code,
                    "intersection_m2_shoulder": float(shoulder_before[code].intersection(apron).area),
                    "intersection_m2_subbase": float(subbase_before[code].intersection(apron).area),
                }
                for apron_code, apron in aprons.items()
                if shoulder_before[code].intersection(apron).area > 1.0e-8
                or subbase_before[code].intersection(apron).area > 1.0e-8
            ],
        }

    output = Path("revp3_post_apron_diagnostics.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
