from __future__ import annotations

import json
import os
import re
from pathlib import Path

import bpy
from mathutils.bvhtree import BVHTree

ROOT = Path(os.environ.get("OUT_ROOT", "revp3_output"))
GLB = ROOT / "20_Модель_A1_RevP3_RoadQA.glb"
QA_PATH = ROOT / "20_Road_QA_Report_RevP3.json"
REPORT_PATH = ROOT / "20_Blender_Mesh_QA_RevP3.json"


def world_vertices(obj):
    matrix = obj.matrix_world
    return [matrix @ vertex.co for vertex in obj.data.vertices]


def polygon_vertex_sets(obj):
    return [set(polygon.vertices) for polygon in obj.data.polygons]


def non_adjacent_bvh_overlaps(obj) -> tuple[int, list[dict]]:
    vertices = world_vertices(obj)
    polygons = [tuple(polygon.vertices) for polygon in obj.data.polygons]
    if not vertices or not polygons:
        return 0, []
    tree = BVHTree.FromPolygons(vertices, polygons, all_triangles=True, epsilon=1.0e-7)
    overlaps = tree.overlap(tree)
    vertex_sets = polygon_vertex_sets(obj)
    non_adjacent = []
    seen = set()
    for first, second in overlaps:
        if first >= second:
            continue
        pair = (int(first), int(second))
        if pair in seen:
            continue
        seen.add(pair)
        if vertex_sets[first] & vertex_sets[second]:
            continue
        non_adjacent.append({"faces": [int(first), int(second)]})
    return len(non_adjacent), non_adjacent[:200]


def mesh_object_metrics(obj) -> dict:
    zero_area = [int(polygon.index) for polygon in obj.data.polygons if polygon.area <= 1.0e-10]
    degenerate_edges = [int(edge.index) for edge in obj.data.edges if edge.calc_length() <= 1.0e-9]
    count, examples = non_adjacent_bvh_overlaps(obj)
    return {
        "vertices": len(obj.data.vertices),
        "edges": len(obj.data.edges),
        "faces": len(obj.data.polygons),
        "zero_area_faces": len(zero_area),
        "zero_area_examples": zero_area[:100],
        "zero_length_edges": len(degenerate_edges),
        "zero_length_edge_examples": degenerate_edges[:100],
        "non_adjacent_triangle_self_intersections": count,
        "self_intersection_examples": examples,
    }


def main():
    if not GLB.exists():
        raise FileNotFoundError(GLB)
    if not QA_PATH.exists():
        raise FileNotFoundError(QA_PATH)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(GLB.resolve()))

    road_objects = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if re.match(r"REV_P3_EXT_D[1-6]_ROAD", obj.name, re.I):
            road_objects.append(obj)

    if len(road_objects) != 6:
        raise RuntimeError(f"Expected six Rev.P3 road objects, found {len(road_objects)}: {[obj.name for obj in road_objects]}")

    object_reports = {}
    total_self_intersections = 0
    total_zero_area = 0
    total_zero_edges = 0
    for obj in sorted(road_objects, key=lambda item: item.name):
        metrics = mesh_object_metrics(obj)
        object_reports[obj.name] = metrics
        total_self_intersections += metrics["non_adjacent_triangle_self_intersections"]
        total_zero_area += metrics["zero_area_faces"]
        total_zero_edges += metrics["zero_length_edges"]

    report = {
        "revision": "A.1/Rev.P3 Road & Apron Coordination",
        "file": GLB.name,
        "engine": "Blender BVHTree overlap with shared-vertex adjacency excluded",
        "road_object_count": len(road_objects),
        "objects": object_reports,
        "non_adjacent_road_triangle_self_intersections": total_self_intersections,
        "zero_area_faces": total_zero_area,
        "zero_length_edges": total_zero_edges,
        "status": "PASS" if total_self_intersections == 0 and total_zero_area == 0 and total_zero_edges == 0 else "FAIL",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    qa["triangle_self_intersections"] = report
    qa["acceptance"]["non_adjacent_road_triangle_self_intersections"] = total_self_intersections
    qa["acceptance"]["blender_zero_area_faces"] = total_zero_area
    qa["acceptance"]["blender_zero_length_edges"] = total_zero_edges
    if report["status"] != "PASS":
        qa["acceptance"]["status"] = "FAIL"
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    if report["status"] != "PASS":
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    print("REV_P3_BLENDER_MESH_QA_PASS")


if __name__ == "__main__":
    main()
