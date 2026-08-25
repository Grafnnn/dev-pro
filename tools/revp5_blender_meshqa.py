from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
MODEL = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
QA_PATH = ROOT / "26_Integrated_QA_Report_RevP5.json"
REPORT_PATH = ROOT / "26_Blender_Road_Mesh_QA_RevP5.json"
MIN_MODEL_BYTES = 1_000_000
SIGNIFICANT_PLAN_FACE_AREA_M2 = 1.0e-4
D5_EXPORT_FACET_GRADE_LIMIT_PCT = 100.0 * math.hypot(0.06, 0.02)
GEOMETRIC_EXACT_EPSILON_M = 1.0e-9
MATERIAL_INTERSECTION_CLEARANCE_M = 1.0e-4

REQUIRED_FEATURES = {
    "REV_P5_MP_ASSEMBLY_PAD_60x40",
    "REV_P5_MP_HEAVY_HAUL_ROUTE",
    "REV_P5_MP_CRANE_PAD_01",
    "REV_P5_MP_CRANE_PAD_02",
    "REV_P5_MP_D3_EMERGENCY_BAY",
    "REV_P5_MP_TIRE_QUARANTINE",
    "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE",
    "REV_P5_MP_DRY_HYBRID_COOLER_RESERVE_40x25",
    "REV_P5_MP_CLEAN_SNOW_CONTAINMENT",
    "REV_P5_MP_DIRTY_SNOW_CONTAINMENT",
    "REV_P5_MP_PHASE2_CAPPED_STUBS",
    "REV_P5_MP_RAW_LOOP_ONE_WAY_MARKINGS",
    "REV_P5_MP_PRODUCT_LOOP_ONE_WAY_MARKINGS",
    "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3",
    "REV_P5_MP_LABORATORY_RESERVE",
    "REV_P5_MP_WASTEWATER_TREATMENT_RESERVE",
    "REV_P5_MP_DG_UPS_RESERVE",
    "REV_P5_MP_HVAC_HEAT_SOURCE_RESERVE",
    "REV_P5_SAFETY_PRELIM_PYROLYSIS_ZONE",
}


def ensure_numpy_for_gltf() -> None:
    """Expose an ABI-compatible NumPy installation to Blender's glTF add-on."""
    try:
        importlib.import_module("numpy")
        return
    except ModuleNotFoundError:
        pass

    major, minor = sys.version_info[:2]
    version = f"python{major}.{minor}"
    candidates = [
        Path("/usr/lib/python3/dist-packages"),
        Path("/usr/local/lib") / version / "dist-packages",
        Path.home() / ".local" / "lib" / version / "site-packages",
    ]
    toolcache = Path("/opt/hostedtoolcache/Python")
    if toolcache.exists():
        candidates.extend(toolcache.glob(f"{major}.{minor}*/x64/lib/{version}/site-packages"))

    attempted = []
    for candidate in candidates:
        if not candidate.exists() or not (candidate / "numpy").exists():
            continue
        attempted.append(str(candidate))
        sys.path.insert(0, str(candidate))
        importlib.invalidate_caches()
        try:
            importlib.import_module("numpy")
            return
        except (ImportError, ModuleNotFoundError):
            sys.path.remove(str(candidate))

    raise RuntimeError(
        "Blender glTF import requires NumPy built for its embedded Python "
        f"{major}.{minor}; no compatible package was found. Checked: {attempted or candidates}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_numeric_qa() -> dict:
    if not MODEL.is_file() or MODEL.stat().st_size < MIN_MODEL_BYTES:
        size = MODEL.stat().st_size if MODEL.exists() else 0
        raise RuntimeError(f"Integrated GLB is missing or unexpectedly small: {MODEL} ({size} bytes)")
    if not QA_PATH.is_file() or QA_PATH.stat().st_size == 0:
        raise FileNotFoundError(QA_PATH)
    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    if qa.get("status") != "PASS_CONTROLLED_PRE_FEED":
        raise RuntimeError(f"Blender QA requires a passing numerical candidate, got {qa.get('status')}")
    if qa.get("acceptance", {}).get("masterplan_status") != "PASS_CONTROLLED_PRE_FEED":
        raise RuntimeError("Integrated acceptance block is not PASS_CONTROLLED_PRE_FEED")
    acceptance = qa.get("acceptance", {})
    if acceptance.get("exported_road_layer_quality_status") != "PASS":
        raise RuntimeError("Exact exported-road numerical QA is missing or not PASS")
    if int(
        acceptance.get(
            "exported_road_layer_significant_top_face_nonpositive_normal_count", -1
        )
    ) != 0:
        raise RuntimeError("Exact exported-road QA reports inverted significant top faces")
    if int(acceptance.get("exported_road_layer_plan_collapsed_top_face_count", -1)) != 0:
        raise RuntimeError("Exact exported-road QA reports plan-collapsed top faces")
    declared_precision_grid = float(
        acceptance.get("road_layer_pslg_precision_grid_m", math.nan)
    )
    if not math.isclose(
        declared_precision_grid,
        MATERIAL_INTERSECTION_CLEARANCE_M,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise RuntimeError(
            "Blender intersection classifier must use the declared road PSLG precision grid: "
            f"declared={declared_precision_grid!r}, "
            f"classifier={MATERIAL_INTERSECTION_CLEARANCE_M!r}"
        )
    declared = set(qa.get("required_features", []))
    if declared != REQUIRED_FEATURES:
        raise RuntimeError(
            "Numerical QA required-feature declaration differs from Blender QA: "
            f"missing={sorted(REQUIRED_FEATURES - declared)}, unexpected={sorted(declared - REQUIRED_FEATURES)}"
        )
    return qa


def world_vertices(obj) -> list[Vector]:
    matrix = obj.matrix_world
    return [matrix @ vertex.co for vertex in obj.data.vertices]


def blender_to_project(vertex: Vector) -> tuple[float, float, float]:
    """Convert Blender's imported glTF axes back to project X/Y/Z."""
    return float(vertex.x), float(vertex.z), -float(vertex.y)


def upward_facet_grade_metrics(vertices: list[Vector], polygons: list[tuple[int, ...]]) -> dict:
    significant_grades = []
    all_upward_grades = []
    upward_face_count = 0
    microscopic_upward_face_count = 0
    for polygon in polygons:
        if len(polygon) != 3:
            continue
        points = [blender_to_project(vertices[index]) for index in polygon]
        first, second, third = points
        ab = tuple(second[index] - first[index] for index in range(3))
        ac = tuple(third[index] - first[index] for index in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if normal[2] <= 1.0e-12:
            continue
        upward_face_count += 1
        plan_area = 0.5 * normal[2]
        grade = 100.0 * math.hypot(normal[0], normal[1]) / normal[2]
        all_upward_grades.append(grade)
        if plan_area >= SIGNIFICANT_PLAN_FACE_AREA_M2:
            significant_grades.append(grade)
        else:
            microscopic_upward_face_count += 1
    if not significant_grades:
        raise RuntimeError("Road layer has no significant upward top facets")
    return {
        "significant_plan_face_area_threshold_m2": SIGNIFICANT_PLAN_FACE_AREA_M2,
        "upward_plan_resolvable_face_count": upward_face_count,
        "significant_upward_face_count": len(significant_grades),
        "microscopic_upward_face_count": microscopic_upward_face_count,
        "maximum_significant_upward_facet_grade_pct": max(significant_grades),
        "maximum_all_upward_plan_resolvable_facet_grade_pct": max(all_upward_grades),
    }


def _point3(point: Vector) -> tuple[float, float, float]:
    return float(point[0]), float(point[1]), float(point[2])


def _sub3(first, second):
    return tuple(first[index] - second[index] for index in range(3))


def _add_scaled3(first, direction, scale: float):
    return tuple(first[index] + scale * direction[index] for index in range(3))


def _dot3(first, second) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _cross3(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _length3(vector) -> float:
    return math.sqrt(_dot3(vector, vector))


def _distance3(first, second) -> float:
    return _length3(_sub3(first, second))


def _segment_triangle_hit(start, end, triangle):
    """Return an exact float32-geometry edge/triangle hit, evaluated in Python doubles."""
    direction = _sub3(end, start)
    edge_first = _sub3(triangle[1], triangle[0])
    edge_second = _sub3(triangle[2], triangle[0])
    cross = _cross3(direction, edge_second)
    determinant = _dot3(edge_first, cross)
    determinant_scale = _length3(direction) * _length3(edge_first) * _length3(edge_second)
    if abs(determinant) <= 1.0e-12 * max(determinant_scale, 1.0e-30):
        return None
    inverse = 1.0 / determinant
    relative = _sub3(start, triangle[0])
    u = inverse * _dot3(relative, cross)
    q = _cross3(relative, edge_first)
    v = inverse * _dot3(direction, q)
    station = inverse * _dot3(edge_second, q)
    parameter_epsilon = 1.0e-10
    if (
        u < -parameter_epsilon
        or v < -parameter_epsilon
        or u + v > 1.0 + parameter_epsilon
        or station < -parameter_epsilon
        or station > 1.0 + parameter_epsilon
    ):
        return None
    return _add_scaled3(start, direction, station)


def _triangle_barycentric(point, triangle):
    first = _sub3(triangle[1], triangle[0])
    second = _sub3(triangle[2], triangle[0])
    relative = _sub3(point, triangle[0])
    dot00 = _dot3(first, first)
    dot01 = _dot3(first, second)
    dot11 = _dot3(second, second)
    dot20 = _dot3(relative, first)
    dot21 = _dot3(relative, second)
    denominator = dot00 * dot11 - dot01 * dot01
    if abs(denominator) <= 1.0e-30:
        return None
    second_weight = (dot11 * dot20 - dot01 * dot21) / denominator
    third_weight = (dot00 * dot21 - dot01 * dot20) / denominator
    return 1.0 - second_weight - third_weight, second_weight, third_weight


def _triangle_altitudes(triangle):
    double_area = _length3(
        _cross3(_sub3(triangle[1], triangle[0]), _sub3(triangle[2], triangle[0]))
    )
    opposite_lengths = (
        _distance3(triangle[1], triangle[2]),
        _distance3(triangle[2], triangle[0]),
        _distance3(triangle[0], triangle[1]),
    )
    return tuple(
        double_area / max(length, 1.0e-30) for length in opposite_lengths
    )


def _maximum_joint_segment_clearance(start, end, triangles) -> float:
    """Maximum distance at which the intersection enters both triangle interiors.

    Barycentric edge clearances are affine along a triangle-intersection segment.
    The lower envelope of the six edge-clearance lines is concave, so its maximum
    occurs at an endpoint or at a pairwise line intersection.
    """
    clearance_lines = []
    for triangle in triangles:
        start_weights = _triangle_barycentric(start, triangle)
        end_weights = _triangle_barycentric(end, triangle)
        if start_weights is None or end_weights is None:
            return math.inf
        altitudes = _triangle_altitudes(triangle)
        for index in range(3):
            clearance_lines.append(
                (
                    start_weights[index] * altitudes[index],
                    end_weights[index] * altitudes[index],
                )
            )

    stations = {0.0, 1.0}
    for index, first in enumerate(clearance_lines):
        first_slope = first[1] - first[0]
        for second in clearance_lines[index + 1 :]:
            denominator = first_slope - (second[1] - second[0])
            if abs(denominator) <= 1.0e-30:
                continue
            station = (second[0] - first[0]) / denominator
            if 0.0 <= station <= 1.0:
                stations.add(float(station))
    maximum = 0.0
    for station in stations:
        minimum = min(
            start_value + station * (end_value - start_value)
            for start_value, end_value in clearance_lines
        )
        maximum = max(maximum, minimum)
    return max(0.0, float(maximum))


def _orientation_2d(first, second, third) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _signed_polygon_area_2d(polygon) -> float:
    return 0.5 * sum(
        polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
        - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
        for index in range(len(polygon))
    )


def _ccw_polygon(polygon):
    result = list(polygon)
    if _signed_polygon_area_2d(result) < 0.0:
        result.reverse()
    return result


def _clip_polygon_to_edge(polygon, first, second, inward_offset: float):
    if not polygon:
        return []
    edge_length = math.hypot(second[0] - first[0], second[1] - first[1])
    threshold = inward_offset * edge_length

    def signed(point) -> float:
        return _orientation_2d(first, second, point) - threshold

    result = []
    previous = polygon[-1]
    previous_value = signed(previous)
    for current in polygon:
        current_value = signed(current)
        previous_inside = previous_value >= -GEOMETRIC_EXACT_EPSILON_M * edge_length
        current_inside = current_value >= -GEOMETRIC_EXACT_EPSILON_M * edge_length
        if previous_inside != current_inside:
            denominator = previous_value - current_value
            if abs(denominator) > 1.0e-30:
                station = previous_value / denominator
                result.append(
                    (
                        previous[0] + station * (current[0] - previous[0]),
                        previous[1] + station * (current[1] - previous[1]),
                    )
                )
        if current_inside:
            result.append(current)
        previous = current
        previous_value = current_value
    return result


def _coplanar_intersection_metrics(first_triangle, second_triangle, normal):
    normal_length = _length3(normal)
    unit_normal = tuple(value / normal_length for value in normal)
    reference = min(
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        key=lambda axis: abs(_dot3(axis, unit_normal)),
    )
    first_axis = _cross3(reference, unit_normal)
    first_axis_length = _length3(first_axis)
    first_axis = tuple(value / first_axis_length for value in first_axis)
    second_axis = _cross3(unit_normal, first_axis)

    def project(point):
        return _dot3(point, first_axis), _dot3(point, second_axis)

    first_2d = _ccw_polygon([project(point) for point in first_triangle])
    second_2d = _ccw_polygon([project(point) for point in second_triangle])
    intersection = list(first_2d)
    for index in range(3):
        intersection = _clip_polygon_to_edge(
            intersection,
            second_2d[index],
            second_2d[(index + 1) % 3],
            0.0,
        )
    if not intersection:
        return {
            "kind": "NONE",
            "coplanar": True,
            "intersection_segment_length_m": 0.0,
            "coplanar_overlap_area_m2": 0.0,
            "joint_interior_clearance_m": 0.0,
        }

    segment_length = max(
        (
            math.hypot(first[0] - second[0], first[1] - second[1])
            for index, first in enumerate(intersection)
            for second in intersection[index + 1 :]
        ),
        default=0.0,
    )
    overlap_area = abs(_signed_polygon_area_2d(intersection)) if len(intersection) >= 3 else 0.0

    all_edges = [
        (triangle[index], triangle[(index + 1) % 3])
        for triangle in (first_2d, second_2d)
        for index in range(3)
    ]

    def clearance_feasible(clearance: float) -> bool:
        clipped = list(intersection)
        for edge_first, edge_second in all_edges:
            clipped = _clip_polygon_to_edge(
                clipped, edge_first, edge_second, clearance
            )
            if not clipped:
                return False
        return True

    lower = 0.0
    upper = max(
        (
            math.hypot(first[0] - second[0], first[1] - second[1])
            for triangle in (first_2d, second_2d)
            for first in triangle
            for second in triangle
        ),
        default=0.0,
    )
    for _ in range(60):
        middle = 0.5 * (lower + upper)
        if clearance_feasible(middle):
            lower = middle
        else:
            upper = middle
    kind = (
        "MATERIAL"
        if lower > MATERIAL_INTERSECTION_CLEARANCE_M
        else "BOUNDARY_CONTACT"
    )
    return {
        "kind": kind,
        "coplanar": True,
        "intersection_segment_length_m": float(segment_length),
        "coplanar_overlap_area_m2": float(overlap_area),
        "joint_interior_clearance_m": float(lower),
    }


def _triangle_intersection_metrics(
    first_triangle: list[Vector], second_triangle: list[Vector]
) -> dict:
    first = [_point3(point) for point in first_triangle]
    second = [_point3(point) for point in second_triangle]
    first_normal = _cross3(_sub3(first[1], first[0]), _sub3(first[2], first[0]))
    second_normal = _cross3(_sub3(second[1], second[0]), _sub3(second[2], second[0]))
    first_length = _length3(first_normal)
    second_length = _length3(second_normal)
    if first_length <= 1.0e-14 or second_length <= 1.0e-14:
        return {
            "kind": "MATERIAL",
            "coplanar": False,
            "intersection_segment_length_m": 0.0,
            "coplanar_overlap_area_m2": 0.0,
            "joint_interior_clearance_m": 2.0
            * MATERIAL_INTERSECTION_CLEARANCE_M,
        }

    parallel_measure = _length3(_cross3(first_normal, second_normal))
    if parallel_measure <= 1.0e-10 * first_length * second_length:
        plane_distance = max(
            abs(_dot3(first_normal, _sub3(point, first[0]))) / first_length
            for point in second
        )
        if plane_distance > GEOMETRIC_EXACT_EPSILON_M:
            return {
                "kind": "NONE",
                "coplanar": False,
                "intersection_segment_length_m": 0.0,
                "coplanar_overlap_area_m2": 0.0,
                "joint_interior_clearance_m": 0.0,
            }
        return _coplanar_intersection_metrics(first, second, first_normal)

    hits = []
    for source, target in ((first, second), (second, first)):
        for index in range(3):
            hit = _segment_triangle_hit(
                source[index], source[(index + 1) % 3], target
            )
            if hit is not None and not any(
                _distance3(hit, existing) <= GEOMETRIC_EXACT_EPSILON_M
                for existing in hits
            ):
                hits.append(hit)
    if not hits:
        return {
            "kind": "NONE",
            "coplanar": False,
            "intersection_segment_length_m": 0.0,
            "coplanar_overlap_area_m2": 0.0,
            "joint_interior_clearance_m": 0.0,
        }
    if len(hits) == 1:
        return {
            "kind": "BOUNDARY_CONTACT",
            "coplanar": False,
            "intersection_segment_length_m": 0.0,
            "coplanar_overlap_area_m2": 0.0,
            "joint_interior_clearance_m": 0.0,
        }

    start, end = max(
        (
            (first_point, second_point)
            for index, first_point in enumerate(hits)
            for second_point in hits[index + 1 :]
        ),
        key=lambda pair: _distance3(pair[0], pair[1]),
    )
    segment_length = _distance3(start, end)
    clearance = _maximum_joint_segment_clearance(start, end, (first, second))
    kind = (
        "MATERIAL"
        if clearance > MATERIAL_INTERSECTION_CLEARANCE_M
        else "BOUNDARY_CONTACT"
    )
    return {
        "kind": kind,
        "coplanar": False,
        "intersection_segment_length_m": float(segment_length),
        "coplanar_overlap_area_m2": 0.0,
        "joint_interior_clearance_m": float(clearance),
    }


def non_adjacent_overlaps(
    obj, vertices: list[Vector], polygons: list[tuple[int, ...]]
) -> dict:
    if not vertices or not polygons:
        return {
            "bvh_candidate_pair_count": 0,
            "exact_triangle_contact_count": 0,
            "boundary_contact_count": 0,
            "boundary_point_contact_count": 0,
            "boundary_segment_contact_count": 0,
            "material_intersection_count": 0,
            "maximum_contact_segment_length_m": 0.0,
            "maximum_joint_interior_clearance_m": 0.0,
            "boundary_contact_examples": [],
            "material_intersection_examples": [],
        }
    if any(len(polygon) != 3 for polygon in polygons):
        raise RuntimeError(f"BVH QA requires triangulated GLB geometry: {obj.name}")
    tree = BVHTree.FromPolygons(vertices, polygons, all_triangles=True, epsilon=1.0e-7)
    vertex_sets = [set(polygon) for polygon in polygons]
    found = []
    contacts = []
    bvh_candidate_count = 0
    exact_contact_count = 0
    maximum_segment_length = 0.0
    maximum_clearance = 0.0
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
        bvh_candidate_count += 1
        first_triangle = [vertices[index] for index in polygons[first]]
        second_triangle = [vertices[index] for index in polygons[second]]
        metrics = _triangle_intersection_metrics(first_triangle, second_triangle)
        if metrics["kind"] == "NONE":
            continue
        exact_contact_count += 1
        maximum_segment_length = max(
            maximum_segment_length, metrics["intersection_segment_length_m"]
        )
        maximum_clearance = max(
            maximum_clearance, metrics["joint_interior_clearance_m"]
        )
        record = {
            "faces": [int(first), int(second)],
            "contact_geometry": (
                "SEGMENT"
                if metrics["intersection_segment_length_m"]
                > GEOMETRIC_EXACT_EPSILON_M
                else "POINT_OR_SUB_EPSILON"
            ),
            **metrics,
        }
        if metrics["kind"] == "MATERIAL":
            found.append(record)
        else:
            contacts.append(record)
    return {
        "bvh_candidate_pair_count": int(bvh_candidate_count),
        "exact_triangle_contact_count": int(exact_contact_count),
        "boundary_contact_count": int(len(contacts)),
        "boundary_point_contact_count": int(
            sum(item["contact_geometry"] == "POINT_OR_SUB_EPSILON" for item in contacts)
        ),
        "boundary_segment_contact_count": int(
            sum(item["contact_geometry"] == "SEGMENT" for item in contacts)
        ),
        "material_intersection_count": int(len(found)),
        "maximum_contact_segment_length_m": float(maximum_segment_length),
        "maximum_joint_interior_clearance_m": float(maximum_clearance),
        "boundary_contact_examples": contacts[:200],
        "material_intersection_examples": found[:200],
    }


def mesh_component_metrics(obj) -> tuple[int, int]:
    vertex_count = len(obj.data.vertices)
    parent = list(range(vertex_count))
    degree = [0] * vertex_count

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for edge in obj.data.edges:
        first, second = (int(value) for value in edge.vertices)
        degree[first] += 1
        degree[second] += 1
        union(first, second)
    loose_vertices = sum(value == 0 for value in degree)
    roots = {find(index) for index, value in enumerate(degree) if value > 0}
    return len(roots), loose_vertices


def object_metrics(obj) -> dict:
    obj.data.update()
    vertices = world_vertices(obj)
    polygons = [tuple(int(value) for value in polygon.vertices) for polygon in obj.data.polygons]
    finite_world_coordinates = all(
        math.isfinite(float(coordinate))
        for vertex in vertices
        for coordinate in vertex
    )
    zero_area = [int(polygon.index) for polygon in obj.data.polygons if polygon.area <= 1.0e-10]
    zero_length = []
    for edge in obj.data.edges:
        first = vertices[int(edge.vertices[0])]
        second = vertices[int(edge.vertices[1])]
        if (second - first).length <= 1.0e-9:
            zero_length.append(int(edge.index))

    face_keys = [tuple(sorted(polygon)) for polygon in polygons]
    duplicate_faces = len(face_keys) - len(set(face_keys))
    non_triangle_faces = sum(len(polygon) != 3 for polygon in polygons)
    edge_face_count: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        for first, second in polygon.edge_keys:
            key = tuple(sorted((int(first), int(second))))
            edge_face_count[key] = edge_face_count.get(key, 0) + 1
    non_manifold_edges = sum(count != 2 for count in edge_face_count.values())
    connected_components, loose_vertices = mesh_component_metrics(obj)
    intersection_metrics = non_adjacent_overlaps(obj, vertices, polygons)
    facet_grade = upward_facet_grade_metrics(vertices, polygons)

    minimum = [min(float(vertex[axis]) for vertex in vertices) for axis in range(3)]
    maximum = [max(float(vertex[axis]) for vertex in vertices) for axis in range(3)]
    return {
        "vertices": len(obj.data.vertices),
        "edges": len(obj.data.edges),
        "faces": len(obj.data.polygons),
        "bounds": [minimum, maximum],
        "finite_world_coordinates": finite_world_coordinates,
        "connected_components": connected_components,
        "loose_vertices": loose_vertices,
        "non_manifold_edges": non_manifold_edges,
        "non_triangle_faces": non_triangle_faces,
        "duplicate_faces": duplicate_faces,
        "zero_area_faces": len(zero_area),
        "zero_length_edges": len(zero_length),
        "non_adjacent_triangle_self_intersections": intersection_metrics[
            "material_intersection_count"
        ],
        "self_intersection_examples": intersection_metrics[
            "material_intersection_examples"
        ],
        "non_adjacent_triangle_bvh_candidate_pairs": intersection_metrics[
            "bvh_candidate_pair_count"
        ],
        "non_adjacent_triangle_exact_contacts": intersection_metrics[
            "exact_triangle_contact_count"
        ],
        "non_adjacent_triangle_boundary_contacts": intersection_metrics[
            "boundary_contact_count"
        ],
        "non_adjacent_triangle_boundary_point_contacts": intersection_metrics[
            "boundary_point_contact_count"
        ],
        "non_adjacent_triangle_boundary_segment_contacts": intersection_metrics[
            "boundary_segment_contact_count"
        ],
        "boundary_contact_examples": intersection_metrics[
            "boundary_contact_examples"
        ],
        "maximum_contact_segment_length_m": intersection_metrics[
            "maximum_contact_segment_length_m"
        ],
        "maximum_joint_interior_clearance_m": intersection_metrics[
            "maximum_joint_interior_clearance_m"
        ],
        "upward_facet_grade": facet_grade,
    }


def imported_scene_metrics() -> dict:
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(mesh_objects) < 100:
        raise RuntimeError(f"Incomplete GLB import: only {len(mesh_objects)} mesh objects")
    names = {obj.name for obj in mesh_objects}
    missing = sorted(REQUIRED_FEATURES - names)
    if missing:
        raise RuntimeError(f"Integrated GLB is missing required Rev.P5 objects: {missing}")

    total_vertices = 0
    empty = []
    non_finite = []
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    for obj in mesh_objects:
        total_vertices += len(obj.data.vertices)
        if not obj.data.vertices or not obj.data.polygons:
            empty.append(obj.name)
            continue
        if not all(math.isfinite(float(value)) for vertex in obj.data.vertices for value in vertex.co):
            non_finite.append(obj.name)
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                value = float(point[axis])
                minimum[axis] = min(minimum[axis], value)
                maximum[axis] = max(maximum[axis], value)

    if empty:
        raise RuntimeError(f"Imported empty mesh objects: {empty[:20]}")
    if non_finite:
        raise RuntimeError(f"Imported non-finite mesh objects: {non_finite[:20]}")
    if total_vertices < 10_000 or not all(math.isfinite(value) for value in minimum + maximum):
        raise RuntimeError(f"Incomplete or non-finite GLB import: vertices={total_vertices}, bounds={minimum, maximum}")
    span_by_axis = [maximum[index] - minimum[index] for index in range(3)]
    span_sorted_desc = sorted(span_by_axis, reverse=True)
    if (
        span_sorted_desc[0] < 550.0
        or span_sorted_desc[1] < 400.0
        or span_sorted_desc[2] < 40.0
    ):
        raise RuntimeError(
            "Unexpectedly truncated integrated scene bounds: "
            f"bounds={minimum, maximum}, spans_by_axis={span_by_axis}, "
            f"spans_sorted_desc={span_sorted_desc}"
        )
    return {
        "mesh_object_count": len(mesh_objects),
        "total_vertices": total_vertices,
        "bounds": [minimum, maximum],
        "spans_by_axis": span_by_axis,
        "spans_sorted_desc": span_sorted_desc,
        "required_feature_count": len(REQUIRED_FEATURES),
        "required_features_present": True,
    }


def main() -> None:
    qa = load_numeric_qa()
    ensure_numpy_for_gltf()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_result = bpy.ops.import_scene.gltf(filepath=str(MODEL.resolve()))
    if "FINISHED" not in import_result:
        raise RuntimeError(f"Blender did not finish importing {MODEL}: {import_result}")
    import_metrics = imported_scene_metrics()

    road_pattern = re.compile(r"REV_P5_EXT_D([1-6])_(ROAD|SHOULDER|SUBBASE)", re.I)
    road_layers = []
    road_codes = set()
    layer_names = set()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        match = road_pattern.fullmatch(obj.name)
        if match:
            road_layers.append(obj)
            road_codes.add(f"D{match.group(1)}")
            layer_names.add(match.group(2).upper())
    if (
        road_codes != {f"D{index}" for index in range(1, 7)}
        or layer_names != {"ROAD", "SHOULDER", "SUBBASE"}
        or len(road_layers) != 18
    ):
        raise RuntimeError(
            "Expected exactly 18 D1-D6 integrated road-layer objects, "
            f"found codes={sorted(road_codes)}, layers={sorted(layer_names)}, "
            f"objects={[obj.name for obj in road_layers]}"
        )

    objects = {}
    totals = {
        "non_adjacent_road_triangle_self_intersections": 0,
        "zero_area_faces": 0,
        "zero_length_edges": 0,
        "non_manifold_edges": 0,
        "duplicate_faces": 0,
        "non_triangle_faces": 0,
        "loose_vertices": 0,
        "disconnected_road_objects": 0,
        "non_finite_road_objects": 0,
        "d5_significant_facet_grade_failures": 0,
    }
    bvh_candidate_total = 0
    exact_contact_total = 0
    boundary_contact_total = 0
    boundary_point_contact_total = 0
    boundary_segment_contact_total = 0
    maximum_contact_segment_length_m = 0.0
    maximum_joint_interior_clearance_m = 0.0
    for obj in sorted(road_layers, key=lambda item: item.name):
        result = object_metrics(obj)
        objects[obj.name] = result
        totals["non_adjacent_road_triangle_self_intersections"] += result["non_adjacent_triangle_self_intersections"]
        totals["zero_area_faces"] += result["zero_area_faces"]
        totals["zero_length_edges"] += result["zero_length_edges"]
        totals["non_manifold_edges"] += result["non_manifold_edges"]
        totals["duplicate_faces"] += result["duplicate_faces"]
        totals["non_triangle_faces"] += result["non_triangle_faces"]
        totals["loose_vertices"] += result["loose_vertices"]
        totals["disconnected_road_objects"] += int(result["connected_components"] != 1)
        totals["non_finite_road_objects"] += int(not result["finite_world_coordinates"])
        bvh_candidate_total += result["non_adjacent_triangle_bvh_candidate_pairs"]
        exact_contact_total += result["non_adjacent_triangle_exact_contacts"]
        boundary_contact_total += result["non_adjacent_triangle_boundary_contacts"]
        boundary_point_contact_total += result[
            "non_adjacent_triangle_boundary_point_contacts"
        ]
        boundary_segment_contact_total += result[
            "non_adjacent_triangle_boundary_segment_contacts"
        ]
        maximum_contact_segment_length_m = max(
            maximum_contact_segment_length_m,
            result["maximum_contact_segment_length_m"],
        )
        maximum_joint_interior_clearance_m = max(
            maximum_joint_interior_clearance_m,
            result["maximum_joint_interior_clearance_m"],
        )
        if re.fullmatch(r"REV_P5_EXT_D5_(?:ROAD|SHOULDER|SUBBASE)", obj.name, re.I):
            totals["d5_significant_facet_grade_failures"] += int(
                result["upward_facet_grade"][
                    "maximum_significant_upward_facet_grade_pct"
                ]
                > D5_EXPORT_FACET_GRADE_LIMIT_PCT + 1.0e-6
            )

    emergency_bay_names = (
        "REV_P5_MP_D3_EMERGENCY_BAY",
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_TRANSITION",
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_OUTER",
    )
    emergency_bay_objects = {}
    emergency_bay_failure_total = 0
    for name in emergency_bay_names:
        emergency_bay = bpy.context.scene.objects.get(name)
        if emergency_bay is None or emergency_bay.type != "MESH":
            raise RuntimeError(f"Blender import is missing the D3 emergency bay layer: {name}")
        metrics = object_metrics(emergency_bay)
        failures = {
            "connected_components": int(metrics["connected_components"] != 1),
            "non_finite_coordinates": int(not metrics["finite_world_coordinates"]),
            "non_adjacent_triangle_self_intersections": metrics["non_adjacent_triangle_self_intersections"],
            "zero_area_faces": metrics["zero_area_faces"],
            "zero_length_edges": metrics["zero_length_edges"],
            "non_manifold_edges": metrics["non_manifold_edges"],
            "duplicate_faces": metrics["duplicate_faces"],
            "non_triangle_faces": metrics["non_triangle_faces"],
            "loose_vertices": metrics["loose_vertices"],
        }
        layer_status = "PASS" if all(value == 0 for value in failures.values()) else "FAIL"
        emergency_bay_failure_total += sum(failures.values())
        emergency_bay_objects[name] = {
            **metrics,
            "failure_counts": failures,
            "status": layer_status,
        }
    emergency_bay_metrics = emergency_bay_objects["REV_P5_MP_D3_EMERGENCY_BAY"]
    emergency_bay_status = "PASS" if emergency_bay_failure_total == 0 else "FAIL"

    status = "PASS" if all(value == 0 for value in totals.values()) and emergency_bay_status == "PASS" else "FAIL"
    report = {
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "file": MODEL.name,
        "file_size_bytes": MODEL.stat().st_size,
        "sha256": sha256_file(MODEL),
        "engine": "Blender GLB import + strict road topology + BVHTree exact contacts; shared-index adjacent faces excluded; material crossing requires joint interior clearance above the declared road PSLG precision grid",
        "import": import_metrics,
        "road_layer_object_count": len(road_layers),
        "road_codes": sorted(road_codes),
        "road_layers": sorted(layer_names),
        "significant_plan_face_area_threshold_m2": SIGNIFICANT_PLAN_FACE_AREA_M2,
        "geometric_exact_epsilon_m": GEOMETRIC_EXACT_EPSILON_M,
        "material_intersection_clearance_m": MATERIAL_INTERSECTION_CLEARANCE_M,
        "d5_significant_facet_grade_limit_pct": D5_EXPORT_FACET_GRADE_LIMIT_PCT,
        "d5_maximum_significant_facet_grade_pct": max(
            result["upward_facet_grade"]["maximum_significant_upward_facet_grade_pct"]
            for name, result in objects.items()
            if re.fullmatch(r"REV_P5_EXT_D5_(?:ROAD|SHOULDER|SUBBASE)", name, re.I)
        ),
        "d5_maximum_all_upward_plan_resolvable_facet_grade_pct": max(
            result["upward_facet_grade"][
                "maximum_all_upward_plan_resolvable_facet_grade_pct"
            ]
            for name, result in objects.items()
            if re.fullmatch(r"REV_P5_EXT_D5_(?:ROAD|SHOULDER|SUBBASE)", name, re.I)
        ),
        "non_adjacent_road_triangle_bvh_candidate_pairs": bvh_candidate_total,
        "non_adjacent_road_triangle_exact_contacts": exact_contact_total,
        "non_adjacent_road_triangle_boundary_contacts": boundary_contact_total,
        "non_adjacent_road_triangle_boundary_point_contacts": boundary_point_contact_total,
        "non_adjacent_road_triangle_boundary_segment_contacts": boundary_segment_contact_total,
        "maximum_road_triangle_contact_segment_length_m": maximum_contact_segment_length_m,
        "maximum_road_triangle_joint_interior_clearance_m": maximum_joint_interior_clearance_m,
        "objects": objects,
        "critical_feature_objects": {
            **emergency_bay_objects,
        },
        **totals,
        "status": status,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    qa["blender_road_mesh_qa"] = report
    acceptance = qa.setdefault("acceptance", {})
    acceptance["blender_import_integrity"] = status == "PASS"
    acceptance["blender_required_features_present"] = import_metrics["required_features_present"]
    acceptance["blender_non_adjacent_road_triangle_self_intersections"] = totals["non_adjacent_road_triangle_self_intersections"]
    acceptance["blender_zero_area_faces"] = totals["zero_area_faces"]
    acceptance["blender_zero_length_edges"] = totals["zero_length_edges"]
    acceptance["blender_non_manifold_edges"] = totals["non_manifold_edges"]
    acceptance["blender_duplicate_faces"] = totals["duplicate_faces"]
    acceptance["blender_non_triangle_faces"] = totals["non_triangle_faces"]
    acceptance["blender_loose_vertices"] = totals["loose_vertices"]
    acceptance["blender_disconnected_road_objects"] = totals["disconnected_road_objects"]
    acceptance["blender_non_finite_road_objects"] = totals["non_finite_road_objects"]
    acceptance["blender_road_layer_object_count"] = len(road_layers)
    acceptance["blender_d5_maximum_significant_facet_grade_pct"] = report[
        "d5_maximum_significant_facet_grade_pct"
    ]
    acceptance["blender_d5_maximum_all_upward_plan_resolvable_facet_grade_pct"] = report[
        "d5_maximum_all_upward_plan_resolvable_facet_grade_pct"
    ]
    acceptance["blender_d5_significant_facet_grade_limit_pct"] = D5_EXPORT_FACET_GRADE_LIMIT_PCT
    acceptance["blender_d5_significant_facet_grade_failures"] = totals[
        "d5_significant_facet_grade_failures"
    ]
    acceptance["blender_non_adjacent_road_triangle_bvh_candidate_pairs"] = bvh_candidate_total
    acceptance["blender_non_adjacent_road_triangle_exact_contacts"] = exact_contact_total
    acceptance["blender_non_adjacent_road_triangle_boundary_contacts"] = boundary_contact_total
    acceptance["blender_non_adjacent_road_triangle_boundary_point_contacts"] = (
        boundary_point_contact_total
    )
    acceptance["blender_non_adjacent_road_triangle_boundary_segment_contacts"] = (
        boundary_segment_contact_total
    )
    acceptance["blender_maximum_road_triangle_contact_segment_length_m"] = (
        maximum_contact_segment_length_m
    )
    acceptance["blender_maximum_road_triangle_joint_interior_clearance_m"] = (
        maximum_joint_interior_clearance_m
    )
    acceptance["blender_material_intersection_clearance_m"] = (
        MATERIAL_INTERSECTION_CLEARANCE_M
    )
    acceptance["blender_emergency_bay_connected_components"] = emergency_bay_metrics["connected_components"]
    acceptance["blender_emergency_bay_topology_failures"] = emergency_bay_failure_total
    if status != "PASS":
        qa["status"] = "FAIL"
        acceptance["masterplan_status"] = "FAIL"
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    if status != "PASS":
        raise RuntimeError(json.dumps(report, ensure_ascii=False))
    print("REV_P5_BLENDER_IMPORT_AND_ROAD_MESH_QA_PASS")


if __name__ == "__main__":
    main()
