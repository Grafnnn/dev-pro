from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

MODULE_PATH = Path("tools/build_revp3_roadqa.py")
spec = importlib.util.spec_from_file_location("revp5_builder", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def crossing_rows(path: np.ndarray, y_value: float, tolerance: float = 6.0) -> list[dict]:
    rows: list[dict] = []
    for index, (first, second) in enumerate(zip(path[:-1], path[1:])):
        y0 = float(first[1])
        y1 = float(second[1])
        if min(y0, y1) - 1.0e-9 <= y_value <= max(y0, y1) + 1.0e-9 and abs(y1 - y0) > 1.0e-9:
            fraction = (y_value - y0) / (y1 - y0)
            x = float(first[0] + fraction * (second[0] - first[0]))
            z = float(first[2] + fraction * (second[2] - first[2]))
            heading = math.degrees(math.atan2(float(second[1] - first[1]), float(second[0] - first[0])))
            rows.append({
                "segment_index": index,
                "xy_at_y": [x, y_value],
                "z_m": z,
                "heading_deg": heading,
                "segment_start": first.tolist(),
                "segment_end": second.tolist(),
            })
        elif abs(y0 - y_value) <= tolerance and abs(y1 - y_value) <= tolerance:
            heading = math.degrees(math.atan2(float(second[1] - first[1]), float(second[0] - first[0])))
            rows.append({
                "segment_index": index,
                "near_target_y": True,
                "midpoint": ((first + second) / 2.0).tolist(),
                "heading_deg": heading,
                "segment_start": first.tolist(),
                "segment_end": second.tolist(),
            })
    return rows


def geometry_summary(geometry) -> dict:
    if geometry.is_empty:
        return {"type": geometry.geom_type, "empty": True}
    result = {
        "type": geometry.geom_type,
        "empty": False,
        "bounds": list(geometry.bounds),
        "length": float(getattr(geometry, "length", 0.0)),
        "area": float(getattr(geometry, "area", 0.0)),
    }
    if geometry.geom_type == "Point":
        result["coordinates"] = [geometry.x, geometry.y]
    elif geometry.geom_type == "MultiPoint":
        result["coordinates"] = [[point.x, point.y] for point in geometry.geoms]
    elif geometry.geom_type in {"LineString", "LinearRing"}:
        result["coordinates"] = [list(point) for point in geometry.coords]
    elif hasattr(geometry, "geoms"):
        result["components"] = [geometry_summary(component) for component in geometry.geoms]
    return result


def coordinated_profiles(paths) -> dict:
    profiles = {
        code: module.RoadProfile(code=code, width=module.WIDTHS[code], paths=road_paths)
        for code, road_paths in paths.items()
    }
    module.coordinate_revp5_d3_d5_profiles(profiles)
    return profiles


def main() -> None:
    paths = module.build_paths()
    d3 = np.asarray(paths["D3"][0], dtype=float)
    d5_paths = [np.asarray(path, dtype=float) for path in paths["D5"]]
    d3_line = LineString(d3[:, :2])
    d5_lines = [LineString(path[:, :2]) for path in d5_paths]
    d5_union = d5_lines[0]
    for line in d5_lines[1:]:
        d5_union = d5_union.union(line)

    diagnostic_profiles = coordinated_profiles(paths)
    d3_profile = diagnostic_profiles["D3"]
    d5_profile = diagnostic_profiles["D5"]
    d3_polygon = d3_profile.polygon(module.WIDTHS["D3"])
    d5_polygon = d5_profile.polygon(module.WIDTHS["D5"])

    d5_endpoint = Point(float(d5_paths[-1][-1, 0]), float(d5_paths[-1][-1, 1]))
    nearest_on_d3_line, nearest_from_d5_endpoint = nearest_points(d3_line, d5_endpoint)
    nearest_on_d3_boundary, nearest_from_d5_endpoint_to_boundary = nearest_points(d3_polygon.boundary, d5_endpoint)

    intersections = []
    for index, line in enumerate(d5_lines):
        path_profile = module.RoadProfile(code="D5", width=module.WIDTHS["D5"], paths=[d5_paths[index]])
        intersections.append({
            "d5_path_index": index,
            "line_intersection_with_d3": geometry_summary(line.intersection(d3_line)),
            "actual_profile_polygon_overlap_with_d3_m2": float(path_profile.polygon(module.WIDTHS["D5"]).intersection(d3_polygon).area),
        })

    layer_polys = {
        layer: module.partition_polygons(
            coordinated_profiles(paths),
            extra_width,
            None,
        )
        for layer, extra_width in (("ROAD", 0.0), ("SHOULDER", 1.5), ("SUBBASE", 3.0))
    }
    engineered_qa = module.revp5_d3_d5_junction_qa(
        diagnostic_profiles,
        layer_polys,
        getattr(module, "BOOLEAN_SLIVER_AUDIT", []),
    )

    # Sample D3 stations nearest to the D5 route and endpoint.
    distances = np.array([d5_union.distance(Point(float(x), float(y))) for x, y in d3[:, :2]])
    nearest_indices = np.argsort(distances)[:30]
    nearest_samples = [
        {
            "d3_index": int(index),
            "point": d3[index].tolist(),
            "distance_to_d5_centerline_m": float(distances[index]),
        }
        for index in nearest_indices
    ]

    report = {
        "widths_m": {"D3": float(module.WIDTHS["D3"]), "D5": float(module.WIDTHS["D5"])},
        "d3": {
            "point_count": int(len(d3)),
            "start": d3[0].tolist(),
            "end": d3[-1].tolist(),
            "bounds": list(d3_line.bounds),
            "crossings_y_189": crossing_rows(d3, 189.0),
            "crossings_y_176": crossing_rows(d3, 176.0),
            "crossings_y_163": crossing_rows(d3, 163.0),
        },
        "d5": {
            "path_count": len(d5_paths),
            "paths": [
                {
                    "index": index,
                    "point_count": int(len(path)),
                    "start": path[0].tolist(),
                    "end": path[-1].tolist(),
                    "bounds": list(d5_lines[index].bounds),
                }
                for index, path in enumerate(d5_paths)
            ],
            "final_endpoint": [d5_endpoint.x, d5_endpoint.y],
        },
        "line_intersections": intersections,
        "raw_centerline_polygon_overlap_m2": float(d3_polygon.intersection(d5_polygon).area),
        "historical_failed_geometry_reference": {
            "overlap_m2": 243.92970324611497,
            "coincident_centerline_length_m": 19.0,
            "location": "y=189, x=571..590",
            "status": "REMOVED_BY_ENGINEERED_TRANSVERSE_BUTT_JUNCTION",
        },
        "engineered_junction_qa": engineered_qa,
        "nearest_from_d5_endpoint_to_d3_centerline": {
            "on_d3": [nearest_on_d3_line.x, nearest_on_d3_line.y],
            "on_d5_endpoint": [nearest_from_d5_endpoint.x, nearest_from_d5_endpoint.y],
            "distance_m": float(d5_endpoint.distance(d3_line)),
        },
        "nearest_from_d5_endpoint_to_d3_road_boundary": {
            "on_d3_boundary": [nearest_on_d3_boundary.x, nearest_on_d3_boundary.y],
            "on_d5_endpoint": [nearest_from_d5_endpoint_to_boundary.x, nearest_from_d5_endpoint_to_boundary.y],
            "distance_m": float(d5_endpoint.distance(d3_polygon.boundary)),
        },
        "nearest_d3_samples_to_d5": nearest_samples,
    }

    output = Path("audit/revp5_d3_d5_junction.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
