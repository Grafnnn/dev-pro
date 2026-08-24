from __future__ import annotations

import json
import os
import re
from pathlib import Path

import bpy
from mathutils.bvhtree import BVHTree

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
MODEL = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
QA_PATH = ROOT / "26_Integrated_QA_Report_RevP5.json"
REPORT_PATH = ROOT / "26_Blender_Road_Mesh_QA_RevP5.json"


def world_vertices(obj):
    matrix = obj.matrix_world
    return [matrix @ vertex.co for vertex in obj.data.vertices]


def non_adjacent_overlaps(obj) -> tuple[int, list[dict]]:
    vertices = world_vertices(obj)
    polygons = [tuple(polygon.vertices) for polygon in obj.data.polygons]
    if not vertices or not polygons:
        return 0, []
    tree = BVHTree.FromPolygons(vertices, polygons, all_triangles=True, epsilon=1.0e-7)
    vertex_sets = [set(polygon) for polygon in polygons]
    found = []
    seen = set()
    for first, second in tree.overlap(tree):
        if first >= second:
            continue
        pair = (int(first), int(second))
        if pair in seen:
            continue
        seen.add(pair)
        if vertex_sets[first] & vertex_sets[second]:
            continue
        found.append({"faces": [int(first), int(second)]})
    return len(found), found[:200]


def object_metrics(obj) -> dict:
    zero_area = [int(p.index) for p in obj.data.polygons if p.area <= 1.0e-10]
    zero_length = [int(e.index) for e in obj.data.edges if e.calc_length() <= 1.0e-9]
    self_count, examples = non_adjacent_overlaps(obj)
    return {
        "vertices": len(obj.data.vertices),
        "edges": len(obj.data.edges),
        "faces": len(obj.data.polygons),
        "zero_area_faces": len(zero_area),
        "zero_length_edges": len(zero_length),
        "non_adjacent_triangle_self_intersections": self_count,
        "self_intersection_examples": examples,
    }


def main() -> None:
    if not MODEL.exists():
        raise FileNotFoundError(MODEL)
    if not QA_PATH.exists():
        raise FileNotFoundError(QA_PATH)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(MODEL.resolve()))

    roads = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH" and re.match(r"REV_P5_EXT_D[1-6]_ROAD", obj.name, re.I)
    ]
    if len(roads) != 6:
        raise RuntimeError(f"Expected six integrated Rev.P5 road objects, found {len(roads)}: {[obj.name for obj in roads]}")

    objects = {}
    self_total = 0
    zero_area_total = 0
    zero_length_total = 0
    for obj in sorted(roads, key=lambda item: item.name):
        result = object_metrics(obj)
        objects[obj.name] = result
        self_total += result["non_adjacent_triangle_self_intersections"]
        zero_area_total += result["zero_area_faces"]
        zero_length_total += result["zero_length_edges"]

    report = {
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "file": MODEL.name,
        "engine": "Blender BVHTree; shared-vertex adjacent faces excluded",
        "road_object_count": len(roads),
        "objects": objects,
        "non_adjacent_road_triangle_self_intersections": self_total,
        "zero_area_faces": zero_area_total,
        "zero_length_edges": zero_length_total,
        "status": "PASS" if self_total == 0 and zero_area_total == 0 and zero_length_total == 0 else "FAIL",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    qa["blender_road_mesh_qa"] = report
    qa["acceptance"]["blender_non_adjacent_road_triangle_self_intersections"] = self_total
    qa["acceptance"]["blender_zero_area_faces"] = zero_area_total
    qa["acceptance"]["blender_zero_length_edges"] = zero_length_total
    if report["status"] != "PASS":
        qa["status"] = "FAIL"
        qa["acceptance"]["masterplan_status"] = "FAIL"
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    if report["status"] != "PASS":
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    print("REV_P5_BLENDER_ROAD_MESH_QA_PASS")


if __name__ == "__main__":
    main()
