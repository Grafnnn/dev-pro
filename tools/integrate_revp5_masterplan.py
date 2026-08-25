from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import trimesh
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

ROOT = Path("revp5_output")
ROAD_ROOT = Path("revp3_output")
ROOT.mkdir(parents=True, exist_ok=True)

ROAD_GLB = ROAD_ROOT / "20_Модель_A1_RevP3_RoadQA.glb"
ROAD_QA = ROAD_ROOT / "20_Road_QA_Report_RevP3.json"
SOURCE_REVP2_GLB = Path("work_revp3/20_Source_RevP2_ExteriorQA.glb")
OUT_GLB = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
OUT_OBJ = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.obj"
OUT_QA = ROOT / "26_Integrated_QA_Report_RevP5.json"
OUT_REGISTER_JSON = ROOT / "26_Masterplan_Change_Register_RevP5.json"
OUT_REGISTER_CSV = ROOT / "26_Masterplan_Change_Register_RevP5.csv"

sys.path.insert(0, str(Path("tools").resolve()))
import build_revp3_roadqa as roadmod  # noqa: E402

COLORS = {
    "assembly": (196, 157, 92, 255),
    "haul": (236, 126, 39, 105),
    "haul_center": (236, 96, 24, 255),
    "crane": (230, 178, 36, 255),
    "quarantine": (182, 73, 58, 230),
    "pedestrian": (48, 169, 196, 255),
    "emergency": (236, 85, 64, 255),
    "emergency_base": (148, 66, 52, 255),
    "cooler": (72, 152, 174, 205),
    "snow_clean": (191, 224, 241, 210),
    "snow_dirty": (116, 146, 164, 220),
    "stub_fw": (220, 53, 46, 255),
    "stub_cw": (0, 150, 190, 255),
    "stub_pg": (232, 142, 36, 255),
    "stub_power": (241, 174, 36, 255),
    "stub_control": (210, 55, 170, 255),
    "laboratory": (105, 122, 178, 220),
    "los": (60, 132, 118, 220),
    "dgups": (91, 91, 103, 230),
    "hvac": (156, 99, 167, 220),
    "safety": (238, 80, 45, 55),
    "ramp": (170, 173, 176, 255),
    "fence": (62, 70, 74, 255),
    "arrow": (245, 225, 90, 255),
}

REQUIRED_FEATURES = [
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
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def color_mesh(mesh: trimesh.Trimesh, rgba: Sequence[int]) -> trimesh.Trimesh:
    mesh.visual.face_colors = np.tile(np.asarray(rgba, dtype=np.uint8), (len(mesh.faces), 1))
    return mesh


def add_mesh(scene: trimesh.Scene, name: str, mesh: trimesh.Trimesh, metadata: dict | None = None) -> None:
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise RuntimeError(f"Empty geometry for {name}")
    mesh.metadata = dict(mesh.metadata or {})
    if metadata:
        mesh.metadata.update(metadata)
    mesh.metadata.setdefault("Revision", "A.1/Rev.P5")
    mesh.metadata.setdefault("Data_Status", "CONTROLLED_PRE_FEED")
    scene.add_geometry(mesh, geom_name=name, node_name=name)


def flat_solid(poly: Polygon, top_z: float, thickness: float, rgba: Sequence[int]) -> trimesh.Trimesh:
    mesh = trimesh.creation.extrude_polygon(poly, height=thickness, engine="earcut")
    mesh.apply_translation([0.0, 0.0, top_z - thickness])
    trimesh.repair.fix_normals(mesh, multibody=True)
    return color_mesh(mesh, rgba)


def solid_between_surfaces(
    geometry,
    top_function,
    bottom_function,
    rgba: Sequence[int],
    max_edge: float = 2.5,
) -> trimesh.Trimesh:
    """Build a closed variable-depth solid using the accepted robust shell.

    The unit shell is refined before its Z coordinates are mapped between the
    supplied top and bottom surfaces.  This preserves identical top/bottom
    topology and a watertight side wall while allowing the emergency-bay
    foundation to deepen locally to competent original ground.
    """
    meshes = []
    for component in roadmod.iter_polygons(geometry):
        unit = roadmod._conforming_watertight_solid(  # noqa: SLF001 - controlled release primitive
            component=component,
            z_function=lambda x, y: 1.0,
            thickness=1.0,
            max_edge=max_edge,
        )
        vertices = np.asarray(unit.vertices, dtype=float)
        local = np.clip(vertices[:, 2], 0.0, 1.0)
        top = np.asarray([top_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
        bottom = np.asarray([bottom_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
        thickness = top - bottom
        if not np.isfinite(top).all() or not np.isfinite(bottom).all() or float(np.min(thickness)) <= 0.05:
            raise RuntimeError(
                "Variable-depth foundation has invalid surfaces: "
                f"minimum_thickness={float(np.min(thickness)):.6f} m"
            )
        vertices[:, 2] = bottom + local * thickness
        unit.vertices = vertices
        trimesh.repair.fix_normals(unit, multibody=True)
        meshes.append(color_mesh(unit, rgba))
    if not meshes:
        raise RuntimeError("Variable-depth solid input is empty")
    result = meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)
    trimesh.repair.fix_normals(result, multibody=True)
    return result


def bottom_mesh_ground_interface_qa(
    mesh: trimesh.Trimesh,
    ground_function,
    barycentric_divisions: int = 6,
) -> dict:
    """Prove the triangulated foundation bottom is supported by source ground.

    Checking the analytic bottom function alone is insufficient: its triangles
    do not share the Rev.P2 terrain breaklines and may interpolate above ground
    between vertices.  This gate samples every downward face on a barycentric
    lattice and compares the actual mesh surface with the immutable Rev.P2
    LinearND terrain surface.
    """
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    normals = np.asarray(mesh.face_normals, dtype=float)
    bottom_faces = faces[normals[:, 2] < -0.50]
    if len(bottom_faces) == 0:
        raise RuntimeError("Variable-depth foundation contains no downward bottom faces")
    differences = []
    divisions = max(2, int(barycentric_divisions))
    for face in bottom_faces:
        triangle = vertices[face]
        for first in range(divisions + 1):
            for second in range(divisions + 1 - first):
                a = first / divisions
                b = second / divisions
                c = 1.0 - a - b
                point = a * triangle[0] + b * triangle[1] + c * triangle[2]
                ground = float(ground_function(float(point[0]), float(point[1])))
                differences.append(float(point[2] - ground))
    if not differences:
        raise RuntimeError("Variable-depth foundation mesh/ground QA sample is empty")
    maximum_bottom_minus_ground = float(max(differences))
    minimum_bottom_minus_ground = float(min(differences))
    return {
        "method": "all downward faces; barycentric lattice against verified Rev.P2 LinearND terrain",
        "bottom_face_count": int(len(bottom_faces)),
        "barycentric_divisions": divisions,
        "sample_count": int(len(differences)),
        "maximum_mesh_bottom_above_ground_m": max(maximum_bottom_minus_ground, 0.0),
        "minimum_residual_ground_key_in_m": -maximum_bottom_minus_ground,
        "maximum_actual_cut_below_ground_m": max(-minimum_bottom_minus_ground, 0.0),
    }


def segment_box(p0: Sequence[float], p1: Sequence[float], width: float, height: float, rgba: Sequence[int]) -> trimesh.Trimesh:
    mesh = roadmod.segment_box(p0, p1, width, height, rgba)
    if mesh is None:
        raise RuntimeError("Zero-length segment")
    return mesh


def iter_world_geometry(scene: trimesh.Scene) -> Iterable[tuple[str, trimesh.Trimesh]]:
    used: dict[str, int] = {}
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        mesh = scene.geometry[geometry_name].copy()
        if not np.allclose(transform, np.eye(4), atol=1e-10):
            mesh.apply_transform(transform)
        base = str(geometry_name)
        count = used.get(base, 0)
        used[base] = count + 1
        name = base if count == 0 else f"{base}__INSTANCE_{count:02d}"
        yield name, mesh


def polygon_from_mesh_xy(mesh: trimesh.Trimesh) -> Polygon:
    return Polygon(np.asarray(mesh.vertices, dtype=float)[:, :2]).convex_hull


def mesh_quality(mesh: trimesh.Trimesh) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    areas = np.asarray(mesh.area_faces, dtype=float) if len(faces) else np.zeros(0)
    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1) if len(mesh.edges) else np.empty((0, 2), int)
    _, counts = np.unique(edge_rows, axis=0, return_counts=True) if len(edge_rows) else (np.empty((0, 2)), np.zeros(0))
    return {
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "finite_coordinates": bool(np.isfinite(vertices).all()),
        "zero_area_faces": int(np.count_nonzero(areas <= 1e-10)),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "open_or_nonmanifold_edges": int(np.count_nonzero(counts != 2)),
        "bounds": np.asarray(mesh.bounds, dtype=float).tolist(),
    }


def build_terrain_sampler(scene: trimesh.Scene):
    candidates = []
    for name, mesh in scene.geometry.items():
        if "finished_design_surface" in name.lower():
            candidates.append((name, mesh))
    if not candidates:
        raise RuntimeError("Finished design surface not found in road model")
    terrain_name, terrain = max(candidates, key=lambda item: len(item[1].vertices))
    vertices = np.asarray(terrain.vertices, dtype=float)
    tree = cKDTree(vertices[:, :2])

    def z_at(x: float, y: float) -> float:
        _, indexes = tree.query(np.array([x, y], dtype=float), k=min(8, len(vertices)))
        indexes = np.atleast_1d(indexes)
        return float(np.max(vertices[indexes, 2]))

    return z_at, np.asarray(terrain.bounds, dtype=float), terrain_name


def build_verified_source_terrain_sampler():
    if not SOURCE_REVP2_GLB.is_file():
        raise FileNotFoundError(SOURCE_REVP2_GLB)
    source_sha = sha256_file(SOURCE_REVP2_GLB)
    if source_sha != roadmod.SOURCE_SHA256:
        raise RuntimeError(
            "Original Rev.P2 terrain source SHA mismatch: "
            f"expected={roadmod.SOURCE_SHA256}; actual={source_sha}"
        )
    source = trimesh.load(str(SOURCE_REVP2_GLB), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)
    candidates = [
        (name, mesh)
        for name, mesh in iter_world_geometry(source)
        if "finished_design_surface" in name.lower()
    ]
    if not candidates:
        raise RuntimeError("Original Rev.P2 finished design surface is missing")
    terrain_name, terrain = max(candidates, key=lambda item: len(item[1].vertices))
    vertices = np.asarray(terrain.vertices, dtype=float)
    rounded = np.round(vertices[:, :2], 4)
    order = np.lexsort((rounded[:, 1], rounded[:, 0]))
    rounded = rounded[order]
    elevations = vertices[order, 2]
    xy_values = []
    z_values = []
    index = 0
    while index < len(rounded):
        stop = index + 1
        while stop < len(rounded) and np.allclose(rounded[stop], rounded[index], atol=1.0e-8):
            stop += 1
        xy_values.append(rounded[index])
        z_values.append(float(np.max(elevations[index:stop])))
        index = stop
    xy = np.asarray(xy_values, dtype=float)
    zz = np.asarray(z_values, dtype=float)
    interpolator = LinearNDInterpolator(xy, zz, fill_value=np.nan)
    tree = cKDTree(xy)

    def sample(x, y):
        points = np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])
        values = np.asarray(interpolator(points), dtype=float).reshape(-1)
        bad = ~np.isfinite(values)
        if np.any(bad):
            _, nearest = tree.query(points[bad], k=1)
            values[bad] = zz[nearest]
        if np.isscalar(x) and np.isscalar(y):
            return float(values[0])
        return values

    return (
        sample,
        np.asarray(terrain.bounds, dtype=float),
        terrain_name,
        source_sha,
        {
            "xy": xy,
            "z": zz,
            "simplices": np.asarray(interpolator.tri.simplices, dtype=int),
        },
    )


def clipped_linear_tin_plane_qa(
    geometry,
    source_tin: dict,
    ground_function,
    bottom_function,
) -> tuple[dict, np.ndarray]:
    """Evaluate exact linear extrema over a footprint clipped to the source TIN.

    Ground and foundation bottom are both linear inside every Delaunay triangle,
    so their difference reaches its extrema at vertices of the clipped cells.
    This is the controlling analytic proof; dense and mesh barycentric checks
    remain independent corroboration.
    """
    xy = np.asarray(source_tin["xy"], dtype=float)
    simplices = np.asarray(source_tin["simplices"], dtype=int)
    minx, miny, maxx, maxy = geometry.bounds
    triangle_xy = xy[simplices]
    candidate_mask = (
        (np.max(triangle_xy[:, :, 0], axis=1) >= minx)
        & (np.min(triangle_xy[:, :, 0], axis=1) <= maxx)
        & (np.max(triangle_xy[:, :, 1], axis=1) >= miny)
        & (np.min(triangle_xy[:, :, 1], axis=1) <= maxy)
    )
    clipped_triangle_count = 0
    clipped_area_sum = 0.0
    coordinate_keys: set[tuple[float, float]] = set()
    for triangle in triangle_xy[candidate_mask]:
        clipped = Polygon(triangle).intersection(geometry)
        if clipped.is_empty or float(clipped.area) <= 1.0e-12:
            continue
        clipped_triangle_count += 1
        clipped_area_sum += float(clipped.area)
        for component in roadmod.iter_polygons(clipped):
            rings = [component.exterior, *component.interiors]
            for ring in rings:
                for x, y in list(ring.coords)[:-1]:
                    coordinate_keys.add((round(float(x), 10), round(float(y), 10)))
    for component in roadmod.iter_polygons(geometry):
        for x, y in list(component.exterior.coords)[:-1]:
            coordinate_keys.add((round(float(x), 10), round(float(y), 10)))
    if not coordinate_keys or clipped_triangle_count == 0:
        raise RuntimeError("Emergency-bay footprint has no positive-area source TIN coverage")
    points = np.asarray(sorted(coordinate_keys), dtype=float)
    samples = []
    for x, y in points:
        ground = float(ground_function(x, y))
        bottom = float(bottom_function(x, y))
        samples.append({"xy": [x, y], "ground_minus_bottom_m": ground - bottom})
    minimum = min(samples, key=lambda item: item["ground_minus_bottom_m"])
    maximum = max(samples, key=lambda item: item["ground_minus_bottom_m"])
    coverage_delta = abs(clipped_area_sum - float(geometry.area))
    if coverage_delta > 1.0e-6:
        raise RuntimeError(
            "Emergency-bay exact source TIN coverage is incomplete: "
            f"clipped={clipped_area_sum:.9f} m2; footprint={float(geometry.area):.9f} m2"
        )
    return {
        "method": "exact extrema at vertices of outer-foundation footprint clipped by verified Rev.P2 LinearND Delaunay cells",
        "source_control_point_count": int(len(xy)),
        "source_tin_triangle_count": int(len(simplices)),
        "clipped_triangle_count": clipped_triangle_count,
        "clipped_area_sum_m2": clipped_area_sum,
        "coverage_delta_m2": coverage_delta,
        "unique_extrema_candidate_count": len(samples),
        "minimum_ground_key_in_m": float(minimum["ground_minus_bottom_m"]),
        "minimum_ground_key_in_xy": minimum["xy"],
        "maximum_actual_cut_below_ground_m": float(maximum["ground_minus_bottom_m"]),
        "maximum_actual_cut_xy": maximum["xy"],
        "maximum_bottom_above_ground_m": max(-float(minimum["ground_minus_bottom_m"]), 0.0),
        "status": "PASS",
    }, points


def top_for_polygon(poly: Polygon, z_at, clearance: float = 0.18) -> float:
    minx, miny, maxx, maxy = poly.bounds
    xs = np.linspace(minx, maxx, 7)
    ys = np.linspace(miny, maxy, 7)
    values = [z_at(float(x), float(y)) for x in xs for y in ys if poly.buffer(1e-6).contains(Point(float(x), float(y)))]
    values.append(z_at(poly.centroid.x, poly.centroid.y))
    return float(max(values) + clearance)


def perimeter_boxes(poly: Polygon, z: float, rgba: Sequence[int], height: float = 1.8, width: float = 0.10) -> trimesh.Trimesh:
    coords = list(poly.exterior.coords)
    parts = []
    for a, b in zip(coords[:-1], coords[1:]):
        parts.append(segment_box((a[0], a[1], z + height / 2), (b[0], b[1], z + height / 2), width, height, rgba))
    return trimesh.util.concatenate(parts)


def route_ribbon(points: list[tuple[float, float]], z_func, width: float, rgba: Sequence[int], height: float = 0.045) -> trimesh.Trimesh:
    parts = []
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        z0 = z_func(x0, y0)
        z1 = z_func(x1, y1)
        parts.append(segment_box((x0, y0, z0), (x1, y1, z1), width, height, rgba))
    return trimesh.util.concatenate(parts)


def protected_route_posts(
    points: list[tuple[float, float]],
    z_func,
    road_union,
    route_width: float = 2.5,
    spacing: float = 4.0,
) -> tuple[trimesh.Trimesh, int]:
    parts = []
    count = 0
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        vector = np.array([x1 - x0, y1 - y0], dtype=float)
        length = float(np.linalg.norm(vector))
        if length < 1.0e-9:
            continue
        tangent = vector / length
        normal = np.array([-tangent[1], tangent[0]], dtype=float)
        stations = np.linspace(0.0, length, max(2, int(math.floor(length / spacing)) + 1))
        for station in stations:
            center = np.array([x0, y0], dtype=float) + tangent * station
            for side in (-1.0, 1.0):
                xy = center + normal * side * (route_width / 2.0 + 0.18)
                point = Point(float(xy[0]), float(xy[1]))
                # Road crossings remain unobstructed and are expressed by the
                # cyan elevated walking strip only.
                if road_union.buffer(0.60).contains(point):
                    continue
                base_z = float(z_func(point.x, point.y))
                post = trimesh.creation.cylinder(radius=0.11, height=1.10, sections=12)
                post.apply_translation([point.x, point.y, base_z + 0.55])
                color_mesh(post, COLORS["pedestrian"])
                parts.append(post)
                count += 1
    if not parts:
        raise RuntimeError("Protected pedestrian route generated no protection posts")
    return trimesh.util.concatenate(parts), count


def arrow_mesh(x: float, y: float, z: float, heading: float, rgba: Sequence[int]) -> trimesh.Trimesh:
    local = Polygon([(-2.2, -0.42), (0.4, -0.42), (0.4, -1.05), (2.45, 0.0), (0.4, 1.05), (0.4, 0.42), (-2.2, 0.42)])
    mesh = trimesh.creation.extrude_polygon(local, height=0.035, engine="earcut")
    transform = trimesh.transformations.rotation_matrix(heading, [0, 0, 1])
    mesh.apply_transform(transform)
    mesh.apply_translation([x, y, z])
    return color_mesh(mesh, rgba)


def profile_tangent(path: np.ndarray, index: int) -> float:
    if index <= 0:
        vector = path[1, :2] - path[0, :2]
    elif index >= len(path) - 1:
        vector = path[-1, :2] - path[-2, :2]
    else:
        vector = path[index + 1, :2] - path[index - 1, :2]
    return float(math.atan2(vector[1], vector[0]))


def physical_feature_check(name: str, poly: Polygon, buildings, roads, allow_road_touch: bool = False) -> dict:
    building_area = float(poly.intersection(buildings).area)
    road_area = float(poly.intersection(roads).area)
    if building_area > 1e-6:
        raise RuntimeError(f"{name} intersects fixed building by {building_area:.6f} m2")
    if not allow_road_touch and road_area > 1e-6:
        raise RuntimeError(f"{name} intersects primary road by {road_area:.6f} m2")
    return {"building_intersection_m2": building_area, "road_intersection_m2": road_area}


def main() -> None:
    if not getattr(roadmod, "REV_P5_ROBUST_EXTRUSION_ACTIVE", False):
        raise RuntimeError(
            "Rev.P5 integration requires the complete accepted road patch chain, "
            "including patch_revp5_robust_extrusion.py"
        )
    if not ROAD_GLB.exists() or not ROAD_QA.exists():
        raise FileNotFoundError("Rev.P3 road build outputs are missing")
    road_qa = json.loads(ROAD_QA.read_text(encoding="utf-8"))
    road_acceptance = road_qa.get("acceptance", {})
    if road_acceptance.get("status") != "PASS":
        raise RuntimeError("Road QA is not PASS; integration prohibited")
    if road_acceptance.get("road_layer_quality_triangulation_status") != "PASS":
        raise RuntimeError("Road source-surface triangulation QA is missing or not PASS")
    if road_acceptance.get("exported_road_layer_quality_status") != "PASS":
        raise RuntimeError("Exact exported-road GLB QA is missing or not PASS")
    if float(road_acceptance["road_layer_maximum_chord_residual_m"]) > float(
        road_acceptance["road_layer_maximum_chord_residual_limit_m"]
    ) + 1.0e-9:
        raise RuntimeError("Road source-surface chord residual exceeds its declared limit")
    if float(
        road_acceptance["exported_road_layer_maximum_all_retained_chord_residual_m"]
    ) > float(
        road_acceptance["exported_road_layer_maximum_chord_residual_limit_m"]
    ) + 1.0e-7:
        raise RuntimeError("Exact exported-road GLB chord residual exceeds its declared limit")
    if int(
        road_acceptance[
            "exported_road_layer_significant_top_face_nonpositive_normal_count"
        ]
    ) != 0:
        raise RuntimeError("Exact exported-road GLB has inverted significant top faces")
    if int(road_acceptance["exported_road_layer_plan_collapsed_top_face_count"]) != 0:
        raise RuntimeError("Exact exported-road GLB has plan-collapsed top faces")
    if int(road_acceptance["exported_road_layer_zero_3d_area_face_count"]) != 0:
        raise RuntimeError("Exact exported-road GLB has zero-area road-layer faces")
    if int(road_acceptance["exported_road_layer_open_or_nonmanifold_edge_count"]) != 0:
        raise RuntimeError("Exact exported-road GLB has open/non-manifold road-layer edges")
    if float(
        road_acceptance["exported_d5_layer_maximum_significant_facet_grade_pct"]
    ) > float(road_acceptance["d5_layer_export_facet_grade_limit_pct"]) + 1.0e-6:
        raise RuntimeError("Exact exported D5 facet grade exceeds its declared limit")
    d3_d5_qa = road_qa.get("d3_d5_junction_geometry", {})
    if d3_d5_qa.get("status") != "PASS":
        raise RuntimeError("Engineered D3-D5 junction QA is missing or not PASS")

    source = trimesh.load(str(ROAD_GLB), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)

    target = trimesh.Scene()
    source_names = []
    relocated_source_snow = []
    for old_name, mesh in iter_world_geometry(source):
        if old_name.lower() in {"clean_snow", "dirty_snow"}:
            relocated_source_snow.append(old_name)
            continue
        new_name = old_name.replace("REV_P3_", "REV_P5_")
        add_mesh(target, new_name, mesh)
        source_names.append(new_name)

    target.metadata = dict(source.metadata or {})
    target.metadata.update({
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "variant": "A.1/Rev.P5",
        "stage": "Integrated pre-FEED coordination model; not for construction",
        "model_status": "CONTROLLED_PRE_FEED_COORDINATION_NOT_FOR_CONSTRUCTION",
        "base_masterplan": "A.1",
        "road_source": "A.1/Rev.P3 RoadQA generated inside Rev.P5 workflow",
        "technological_source": "A.1/Rev.P2 exterior based on LOD400-P/RFI",
        "coordinate_system": "Local project coordinates; survey CRS pending HP-01",
        "date_cut": "2026-08-25",
    })

    z_at, terrain_bounds, terrain_name = build_terrain_sampler(target)
    source_ground_z, source_terrain_bounds, source_terrain_name, source_terrain_sha, source_terrain_tin = (
        build_verified_source_terrain_sampler()
    )
    paths = roadmod.build_paths()
    profiles = {code: roadmod.RoadProfile(code=code, width=roadmod.WIDTHS[code], paths=road_paths) for code, road_paths in paths.items()}
    roadmod.coordinate_revp5_d3_d5_profiles(profiles)
    road_polys = {code: profile.polygon(roadmod.WIDTHS[code]) for code, profile in profiles.items()}
    road_shoulder_polys = {
        code: profile.polygon(roadmod.WIDTHS[code] + 1.5)
        for code, profile in profiles.items()
    }
    road_subbase_polys = {
        code: profile.polygon(roadmod.WIDTHS[code] + 3.0)
        for code, profile in profiles.items()
    }
    road_union = unary_union(list(road_polys.values())).buffer(0)
    road_subbase_union = unary_union(list(road_subbase_polys.values())).buffer(0)

    foundations = {}
    walls = {}
    for name, mesh in target.geometry.items():
        base_name = name.replace("REV_P5_", "")
        if re.match(r"BLD_.*_FOUNDATION(?:_DECK)?$", base_name, re.I):
            foundations[base_name] = polygon_from_mesh_xy(mesh)
        elif re.match(r"BLD_.*_(?:WALL_PANELS|SHELL)$", base_name, re.I):
            walls[base_name] = polygon_from_mesh_xy(mesh)
    building_union = unary_union(list(foundations.values()) + list(walls.values())).buffer(0)

    deck_mesh = target.geometry.get("BLD_05_FOUNDATION_DECK")
    if deck_mesh is None:
        raise RuntimeError("BLD_05_FOUNDATION_DECK not found")
    deck_poly = polygon_from_mesh_xy(deck_mesh)
    deck_top = float(deck_mesh.bounds[1, 2]) + 0.01
    safety_poly = deck_poly.buffer(12.0, join_style=2).difference(deck_poly).buffer(0)

    register = []
    checks = {}
    new_mesh_names = []
    feature_footprints: dict[str, Polygon] = {}
    physical_footprints: dict[str, Polygon] = {}
    feature_roles: dict[str, str] = {}

    def register_feature(
        name: str,
        category: str,
        status: str,
        poly: Polygon | None,
        note: str,
        mesh: trimesh.Trimesh,
        metadata: dict | None = None,
        spatial_role: str = "PHYSICAL",
    ):
        add_mesh(target, name, mesh, metadata)
        new_mesh_names.append(name)
        feature_roles[name] = spatial_role
        if poly is not None:
            feature_footprints[name] = poly
            if spatial_role in {"PHYSICAL", "SPATIAL_RESERVE", "PERSONNEL_ROUTE"}:
                physical_footprints[name] = poly
        row = {
            "Object_Name": name,
            "Category": category,
            "Data_Status": status,
            "Area_m2": float(poly.area) if poly is not None else None,
            "Bounds_XY": list(poly.bounds) if poly is not None else None,
            "Description": note,
            "Spatial_Role": spatial_role,
        }
        register.append(row)

    # 1. West construction/assembly area 60 x 40 m.
    assembly = box(70.0, 190.0, 130.0, 230.0)
    checks["assembly"] = physical_feature_check("assembly", assembly, building_union, road_union)
    assembly_z = top_for_polygon(assembly, z_at, 0.35)
    register_feature(
        "REV_P5_MP_ASSEMBLY_PAD_60x40", "Construction logistics", "CONTROLLED_PRE_FEED", assembly,
        "Montage and pre-assembly platform in the west logistics reserve; 60 x 40 m.",
        flat_solid(assembly, assembly_z, 0.35, COLORS["assembly"]),
        {"Dimensions": "60x40 m", "Phase": "Construction", "WBS": "WP-01/WP-09"},
    )

    # 2. Temporary heavy-haul route: lower entry -> west assembly area, plus
    # a preliminary 9 m swept-envelope overlay along D4/D6/D3. The envelope is
    # physical geometry for coordination evidence, but is not a certified
    # AutoTURN result.
    spur_points = [(177.0, 105.0), (153.0, 118.0), (145.0, 155.0), (145.0, 215.0), (130.0, 220.0)]
    haul_width = 9.0
    haul_lines = [LineString(spur_points)]
    haul_parts = [
        route_ribbon(spur_points, lambda x, y: z_at(x, y) + 0.16, haul_width, COLORS["haul"], 0.025),
        route_ribbon(spur_points, lambda x, y: z_at(x, y) + 0.19, 0.65, COLORS["haul_center"], 0.035),
    ]
    for code in ("D4", "D6"):
        for path in profiles[code].paths:
            haul_lines.append(LineString(path[:, :2]))
            for a, b in zip(path[:-1], path[1:]):
                haul_parts.append(segment_box((a[0], a[1], profiles[code].surface_z(a[0], a[1]) + 0.08),
                                              (b[0], b[1], profiles[code].surface_z(b[0], b[1]) + 0.08),
                                              haul_width, 0.025, COLORS["haul"]))
    d3_path = max(profiles["D3"].paths, key=len)
    d3_haul_points = []
    for a, b in zip(d3_path[:-1], d3_path[1:]):
        if min(a[1], b[1]) < 205.0:
            continue
        if not d3_haul_points:
            d3_haul_points.append(tuple(a[:2]))
        d3_haul_points.append(tuple(b[:2]))
        haul_parts.append(segment_box((a[0], a[1], profiles["D3"].surface_z(a[0], a[1]) + 0.08),
                                      (b[0], b[1], profiles["D3"].surface_z(b[0], b[1]) + 0.08),
                                      haul_width, 0.025, COLORS["haul"]))
    if len(d3_haul_points) > 1:
        haul_lines.append(LineString(d3_haul_points))
    haul_envelope = unary_union([line.buffer(haul_width / 2.0, cap_style=1, join_style=1) for line in haul_lines]).buffer(0)
    haul_building_overlap = float(haul_envelope.intersection(building_union).area)
    if haul_building_overlap > 1.0e-6:
        raise RuntimeError(f"Heavy-haul 9 m envelope intersects fixed buildings by {haul_building_overlap:.6f} m2")
    checks["heavy_haul"] = {
        "preliminary_envelope_width_m": haul_width,
        "building_intersection_m2": haul_building_overlap,
        "certified_swept_path_pending": True,
    }
    register_feature(
        "REV_P5_MP_HEAVY_HAUL_ROUTE", "Construction logistics", "CONTROLLED_PRE_FEED", haul_envelope,
        "Preliminary 9 m heavy-haul swept envelope for a 16.5 m articulated screening vehicle; final certified swept path remains HP-07.",
        trimesh.util.concatenate(haul_parts),
        {"Vehicle": "16.5 m screening vehicle", "Envelope_Width": "9.0 m", "Gate": "HP-07"},
        spatial_role="CLEARANCE_ENVELOPE",
    )

    # 3. Crane setup positions around the pyrolysis building.
    crane_polys = [box(326.0, 207.0, 344.0, 221.0), box(315.0, 232.0, 333.0, 246.0)]
    for index, poly in enumerate(crane_polys, start=1):
        checks[f"crane_{index}"] = physical_feature_check(f"crane_{index}", poly, building_union, road_union)
        top = top_for_polygon(poly, z_at, 0.25)
        register_feature(
            f"REV_P5_MP_CRANE_PAD_{index:02d}", "Construction logistics", "CONTROLLED_PRE_FEED", poly,
            "Temporary crane outrigger platform adjacent to the pyrolysis terrace.",
            flat_solid(poly, top, 0.30, COLORS["crane"]),
            {
                "Phase": "Construction",
                "Data_Status": "CONTROLLED_PRE_FEED",
                "Gate": "HP-07",
                "Safety_Zone_Coordination": "Temporary construction use only; removed before operational hazardous-area controls",
            },
        )

    # 4. D3 emergency lay-by. The original rectangle crossed D3 and split into
    # two slabs. A first replacement at y=296 was plan-connected, but its
    # earthwork gate sampled the already-cut Rev.P3 surface and the pavement
    # top rather than formation. The controlled candidate below is on another
    # straight D3 reach with materially better original-ground balance. Its
    # surface is the exact continuation of the D3 design surface across the
    # shoulder/subbase support.  Its independent outer foundation uses one
    # engineered formation plane, not a terrain-following underside: the plane
    # is proven against every clipped cell of the immutable Rev.P2 terrain TIN.
    bay_seam_y = 244.0
    bay_outer_y = 250.0
    bay_seam_start_x = 541.0
    bay_seam_end_x = 565.0
    bay_outer_base_nominal_thickness = 0.50
    bay_minimum_ground_key_in = 0.10
    bay_foundation_bottom_plane = {
        "constant_m": 121.536920,
        "x_coefficient": -0.032870,
        "y_coefficient": 0.049000,
    }
    bay_foundation_bottom_plane_grade_pct = float(
        100.0 * math.hypot(
            bay_foundation_bottom_plane["x_coefficient"],
            bay_foundation_bottom_plane["y_coefficient"],
        )
    )
    if bay_foundation_bottom_plane_grade_pct > 6.000001:
        raise RuntimeError(
            "D3 emergency bay foundation-bottom plane exceeds 6%: "
            f"{bay_foundation_bottom_plane_grade_pct:.6f}%"
        )
    bay_poly = Polygon([
        (bay_seam_start_x, bay_seam_y),
        (bay_seam_end_x, bay_seam_y),
        (563.0, bay_outer_y),
        (543.0, bay_outer_y),
    ])
    bay_components = 1 if isinstance(bay_poly, Polygon) else len(getattr(bay_poly, "geoms", []))
    bay_road_overlap = float(bay_poly.intersection(road_union).area)
    bay_d3_gap = float(bay_poly.distance(road_polys["D3"]))
    bay_d3_seam = float(bay_poly.boundary.intersection(road_polys["D3"].boundary).length)
    if bay_components != 1:
        raise RuntimeError(f"D3 emergency bay must be one plan component, got {bay_components}")
    if bay_road_overlap > 1.0e-6 or bay_d3_gap > 1.0e-6 or bay_d3_seam < 12.0:
        raise RuntimeError(
            "D3 emergency bay connection failed: "
            f"road_overlap={bay_road_overlap:.9f} m2; gap={bay_d3_gap:.9f} m; "
            f"shared_seam={bay_d3_seam:.6f} m"
        )

    def bay_surface_z(x: float, y: float) -> float:
        return float(profiles["D3"].surface_z(float(x), float(y)))

    bay_seam_samples = np.linspace(bay_seam_start_x, bay_seam_end_x, 97)
    bay_vertical_steps = [
        abs(bay_surface_z(float(x), bay_seam_y) - profiles["D3"].surface_z(float(x), bay_seam_y))
        for x in bay_seam_samples
    ]
    bay_max_vertical_step = float(max(bay_vertical_steps, default=math.inf))
    bay_longitudinal_grade = 100.0 * abs(
        bay_surface_z(bay_seam_end_x, bay_seam_y)
        - bay_surface_z(bay_seam_start_x, bay_seam_y)
    ) / 24.0
    bay_crossfall_pct = 100.0 * abs(
        bay_surface_z(553.0, bay_outer_y) - bay_surface_z(553.0, bay_seam_y)
    ) / (bay_outer_y - bay_seam_y)
    bay_resultant_grade = float(math.hypot(bay_longitudinal_grade, bay_crossfall_pct))
    if bay_max_vertical_step > 0.020001 or bay_resultant_grade > 6.000001:
        raise RuntimeError(
            "D3 emergency bay vertical/grade gate failed: "
            f"step={bay_max_vertical_step:.6f} m; grade={bay_resultant_grade:.6f}%"
        )

    # Road-layer integration without volume overlap: a 120 mm surface course
    # continues directly from the D3 asphalt. It rests on the existing shoulder;
    # a 240 mm levelling layer occupies only the subbase-only strip. Outside the
    # complete D3 subbase a separate granular foundation is formed to one
    # constructible plane with at least 100 mm key-in to original Rev.P2 ground.
    bay_subbase_only = (
        bay_poly.intersection(road_subbase_polys["D3"])
        .difference(road_shoulder_polys["D3"])
        .buffer(0)
    )
    bay_outer_foundation = bay_poly.difference(road_subbase_union).buffer(0)
    shoulder_support_poly = (
        bay_poly.intersection(road_shoulder_polys["D3"])
        .difference(road_polys["D3"])
        .buffer(0)
    )
    if bay_subbase_only.is_empty or bay_outer_foundation.is_empty:
        raise RuntimeError("D3 emergency bay layer-support polygons are empty")
    bay_support_parts = [shoulder_support_poly, bay_subbase_only, bay_outer_foundation]
    bay_support_pairwise_overlap = max(
        float(first.intersection(second).area)
        for index, first in enumerate(bay_support_parts)
        for second in bay_support_parts[index + 1:]
    )
    bay_support_coverage_gap = float(bay_poly.symmetric_difference(unary_union(bay_support_parts)).area)
    if bay_support_pairwise_overlap > 1.0e-6 or bay_support_coverage_gap > 1.0e-6:
        raise RuntimeError(
            "D3 emergency bay support partition is not exclusive and complete: "
            f"overlap={bay_support_pairwise_overlap:.9f} m2; "
            f"coverage_gap={bay_support_coverage_gap:.9f} m2"
        )

    source_site = box(
        source_terrain_bounds[0, 0],
        source_terrain_bounds[0, 1],
        source_terrain_bounds[1, 0],
        source_terrain_bounds[1, 1],
    )
    bay_outside_source_area = float(bay_poly.difference(source_site).area)
    if bay_outside_source_area > 1.0e-6:
        raise RuntimeError(f"D3 emergency bay escapes original Rev.P2 terrain by {bay_outside_source_area:.6f} m2")

    def bay_outer_top_z(x: float, y: float) -> float:
        return bay_surface_z(x, y) - 0.12

    def bay_nominal_formation_z(x: float, y: float) -> float:
        return bay_outer_top_z(x, y) - bay_outer_base_nominal_thickness

    def bay_actual_foundation_bottom_z(x: float, y: float) -> float:
        return float(
            bay_foundation_bottom_plane["constant_m"]
            + bay_foundation_bottom_plane["x_coefficient"] * float(x)
            + bay_foundation_bottom_plane["y_coefficient"] * float(y)
        )

    bay_exact_tin_base_qa, bay_exact_tin_points = clipped_linear_tin_plane_qa(
        bay_outer_foundation,
        source_terrain_tin,
        source_ground_z,
        bay_actual_foundation_bottom_z,
    )
    exact_x = bay_exact_tin_points[:, 0]
    exact_y = bay_exact_tin_points[:, 1]
    exact_ground = np.asarray(source_ground_z(exact_x, exact_y), dtype=float)
    exact_top = np.asarray([
        bay_outer_top_z(float(x), float(y)) for x, y in bay_exact_tin_points
    ], dtype=float)
    top_affine_design = np.column_stack([
        exact_x,
        exact_y,
        np.ones(len(bay_exact_tin_points), dtype=float),
    ])
    top_affine_coefficients, _, _, _ = np.linalg.lstsq(
        top_affine_design,
        exact_top,
        rcond=None,
    )
    top_affine_residual = float(np.max(np.abs(
        exact_top - top_affine_design @ top_affine_coefficients
    )))
    if top_affine_residual > 1.0e-8:
        raise RuntimeError(
            "D3 emergency bay top is not affine over the exact TIN footprint; "
            f"residual={top_affine_residual:.12f} m"
        )
    exact_nominal = exact_top - bay_outer_base_nominal_thickness
    exact_bottom = (
        bay_foundation_bottom_plane["constant_m"]
        + bay_foundation_bottom_plane["x_coefficient"] * exact_x
        + bay_foundation_bottom_plane["y_coefficient"] * exact_y
    )
    exact_nominal_delta = exact_nominal - exact_ground
    exact_ground_key_in = exact_ground - exact_bottom
    exact_thickness = exact_top - exact_bottom
    exact_unsupported_gap = np.maximum(exact_bottom - exact_ground, 0.0)
    exact_arrays = (
        exact_ground,
        exact_top,
        exact_nominal,
        exact_bottom,
        exact_nominal_delta,
        exact_ground_key_in,
        exact_thickness,
        exact_unsupported_gap,
    )
    if not all(np.isfinite(values).all() for values in exact_arrays):
        raise RuntimeError("D3 emergency bay exact clipped-TIN formation QA contains non-finite values")

    nominal_fill_index = int(np.argmax(exact_nominal_delta))
    nominal_cut_index = int(np.argmin(exact_nominal_delta))
    minimum_key_index = int(np.argmin(exact_ground_key_in))
    maximum_actual_cut_index = int(np.argmax(exact_ground_key_in))
    minimum_thickness_index = int(np.argmin(exact_thickness))
    maximum_thickness_index = int(np.argmax(exact_thickness))
    bay_max_fill_depth = float(max(exact_nominal_delta[nominal_fill_index], 0.0))
    bay_max_cut_depth = float(max(-exact_nominal_delta[nominal_cut_index], 0.0))
    bay_min_actual_foundation_thickness = float(exact_thickness[minimum_thickness_index])
    bay_max_actual_foundation_thickness = float(exact_thickness[maximum_thickness_index])
    bay_analytic_max_unsupported_gap = float(np.max(exact_unsupported_gap))
    bay_exact_tin_formation_qa = {
        "method": "AFFINE_EXTREMA_AT_CLIPPED_REVP2_LINEAR_ND_TIN_VERTICES",
        "source_control_point_count": bay_exact_tin_base_qa["source_control_point_count"],
        "source_tin_triangle_count": bay_exact_tin_base_qa["source_tin_triangle_count"],
        "intersected_triangle_count": bay_exact_tin_base_qa["clipped_triangle_count"],
        "extrema_vertex_count": bay_exact_tin_base_qa["unique_extrema_candidate_count"],
        "clipped_area_sum_m2": bay_exact_tin_base_qa["clipped_area_sum_m2"],
        "coverage_delta_m2": bay_exact_tin_base_qa["coverage_delta_m2"],
        "plane": {
            "equation": "B(x,y) = 121.536920 - 0.032870*x + 0.049000*y",
            "z_intercept_m": bay_foundation_bottom_plane["constant_m"],
            "dz_dx": bay_foundation_bottom_plane["x_coefficient"],
            "dz_dy": bay_foundation_bottom_plane["y_coefficient"],
            "grade_pct": bay_foundation_bottom_plane_grade_pct,
        },
        "top_surface_affinity": {
            "z_intercept_m": float(top_affine_coefficients[2]),
            "dz_dx": float(top_affine_coefficients[0]),
            "dz_dy": float(top_affine_coefficients[1]),
            "maximum_fit_residual_m": top_affine_residual,
            "status": "PASS",
        },
        "nominal": {
            "maximum_fill_m": bay_max_fill_depth,
            "maximum_fill_xy": bay_exact_tin_points[nominal_fill_index].tolist(),
            "maximum_cut_m": bay_max_cut_depth,
            "maximum_cut_xy": bay_exact_tin_points[nominal_cut_index].tolist(),
        },
        "actual": {
            "minimum_ground_key_in_m": float(exact_ground_key_in[minimum_key_index]),
            "minimum_ground_key_in_xy": bay_exact_tin_points[minimum_key_index].tolist(),
            "maximum_cut_below_ground_m": float(exact_ground_key_in[maximum_actual_cut_index]),
            "maximum_cut_xy": bay_exact_tin_points[maximum_actual_cut_index].tolist(),
            "minimum_thickness_m": bay_min_actual_foundation_thickness,
            "minimum_thickness_xy": bay_exact_tin_points[minimum_thickness_index].tolist(),
            "maximum_thickness_m": bay_max_actual_foundation_thickness,
            "maximum_thickness_xy": bay_exact_tin_points[maximum_thickness_index].tolist(),
            "maximum_unsupported_gap_m": bay_analytic_max_unsupported_gap,
        },
        "status": "PASS",
    }
    if bay_max_cut_depth > 1.000001 or bay_max_fill_depth > 0.500001:
        raise RuntimeError(
            "D3 emergency bay exact nominal formation gate failed: "
            f"cut={bay_max_cut_depth:.6f} m; fill={bay_max_fill_depth:.6f} m"
        )
    if bay_exact_tin_formation_qa["actual"]["minimum_ground_key_in_m"] < bay_minimum_ground_key_in - 1.0e-6:
        raise RuntimeError(
            "D3 emergency bay engineered bottom plane misses the 100 mm exact TIN key-in gate: "
            f"{bay_exact_tin_formation_qa['actual']['minimum_ground_key_in_m']:.9f} m"
        )
    if bay_exact_tin_formation_qa["actual"]["maximum_cut_below_ground_m"] > 0.950001:
        raise RuntimeError(
            "D3 emergency bay engineered bottom plane exceeds the 0.95 m exact TIN cut gate: "
            f"{bay_exact_tin_formation_qa['actual']['maximum_cut_below_ground_m']:.9f} m"
        )
    if bay_analytic_max_unsupported_gap > 1.0e-6:
        raise RuntimeError(
            "D3 emergency bay exact engineered plane floats above source ground by "
            f"{bay_analytic_max_unsupported_gap:.9f} m"
        )
    if (
        bay_min_actual_foundation_thickness < 0.499999
        or bay_max_actual_foundation_thickness > 1.050001
    ):
        raise RuntimeError(
            "D3 emergency bay exact foundation thickness gate failed: "
            f"min={bay_min_actual_foundation_thickness:.6f} m; "
            f"max={bay_max_actual_foundation_thickness:.6f} m"
        )

    bay_formation_anchors = []
    for label, x, y in (
        ("controlling_nominal_fill", 541.5, 245.5),
        ("controlling_nominal_cut", 563.0, 250.0),
    ):
        ground = float(source_ground_z(x, y))
        nominal = float(bay_nominal_formation_z(x, y))
        bay_formation_anchors.append({
            "label": label,
            "xy": [x, y],
            "source_ground_z_m": ground,
            "surface_z_m": float(bay_surface_z(x, y)),
            "nominal_formation_z_m": nominal,
            "nominal_formation_minus_ground_m": nominal - ground,
        })
    if (
        bay_formation_anchors[0]["nominal_formation_minus_ground_m"] <= 0.0
        or bay_formation_anchors[1]["nominal_formation_minus_ground_m"] >= 0.0
    ):
        raise RuntimeError("D3 emergency bay controlling formation anchors changed sign")

    dense_formation_differences = []
    dense_actual_foundation_thicknesses = []
    dense_actual_unsupported_gaps = []
    for y in np.linspace(bay_seam_y, bay_outer_y, 97):
        for x in np.linspace(bay_seam_start_x, bay_seam_end_x, 193):
            point = Point(float(x), float(y))
            if not bay_outer_foundation.buffer(1.0e-9).contains(point):
                continue
            ground = float(source_ground_z(float(x), float(y)))
            nominal_bottom = bay_nominal_formation_z(float(x), float(y))
            actual_bottom = bay_actual_foundation_bottom_z(float(x), float(y))
            dense_formation_differences.append(nominal_bottom - ground)
            dense_actual_foundation_thicknesses.append(bay_outer_top_z(float(x), float(y)) - actual_bottom)
            dense_actual_unsupported_gaps.append(max(actual_bottom - ground, 0.0))
    if not dense_formation_differences:
        raise RuntimeError("D3 emergency bay original-ground formation sample is empty")
    dense_max_fill_depth = float(max(max(dense_formation_differences), 0.0))
    dense_max_cut_depth = float(max(-min(dense_formation_differences), 0.0))
    dense_max_unsupported_gap = float(max(dense_actual_unsupported_gaps, default=math.inf))
    dense_min_actual_thickness = float(min(dense_actual_foundation_thicknesses))
    dense_max_actual_thickness = float(max(dense_actual_foundation_thicknesses))
    if (
        dense_max_fill_depth > bay_max_fill_depth + 1.0e-6
        or dense_max_cut_depth > bay_max_cut_depth + 1.0e-6
        or dense_max_unsupported_gap > bay_analytic_max_unsupported_gap + 1.0e-6
        or dense_min_actual_thickness < bay_min_actual_foundation_thickness - 1.0e-6
        or dense_max_actual_thickness > bay_max_actual_foundation_thickness + 1.0e-6
    ):
        raise RuntimeError(
            "D3 emergency bay dense formation diagnostic exceeds controlling exact TIN extrema"
        )
    bay_exact_tin_formation_qa["secondary_dense_diagnostic"] = {
        "sample_count": len(dense_formation_differences),
        "maximum_nominal_fill_m": dense_max_fill_depth,
        "maximum_nominal_cut_m": dense_max_cut_depth,
        "maximum_unsupported_gap_m": dense_max_unsupported_gap,
        "minimum_actual_thickness_m": dense_min_actual_thickness,
        "maximum_actual_thickness_m": dense_max_actual_thickness,
        "status": "PASS",
    }

    terrain_cut_corridor = bay_poly.buffer(0.40, join_style=2)
    terrain_before_cut = target.geometry[terrain_name]
    terrain_after_cut, bay_terrain_cut_stats = roadmod.cut_finished_surface(
        terrain_before_cut,
        terrain_cut_corridor,
    )
    cut_vertices = np.asarray(terrain_after_cut.vertices, dtype=float)
    terrain_vertices_inside_bay = int(np.count_nonzero(
        roadmod.contains_xy(bay_poly.buffer(-1.0e-6), cut_vertices[:, 0], cut_vertices[:, 1])
    ))
    if terrain_vertices_inside_bay != 0 or bay_terrain_cut_stats["removed_faces"] <= 0:
        raise RuntimeError(
            "D3 emergency bay terrain cut failed: "
            f"remaining_inside_vertices={terrain_vertices_inside_bay}; "
            f"removed_faces={bay_terrain_cut_stats['removed_faces']}"
        )
    target.geometry[terrain_name] = terrain_after_cut

    checks["emergency_bay"] = physical_feature_check("emergency_bay", bay_poly, building_union, road_union)

    bay_surface_mesh = roadmod.solid_from_polygon(
        bay_poly,
        bay_surface_z,
        0.12,
        COLORS["emergency"],
        2.5,
    )
    bay_transition_mesh = roadmod.solid_from_polygon(
        bay_subbase_only,
        lambda x, y: bay_surface_z(x, y) - 0.12,
        0.24,
        COLORS["emergency_base"],
        2.5,
    )
    bay_outer_base_mesh = solid_between_surfaces(
        bay_outer_foundation,
        bay_outer_top_z,
        bay_actual_foundation_bottom_z,
        COLORS["emergency_base"],
        1.0,
    )
    bay_bottom_mesh_ground_qa = bottom_mesh_ground_interface_qa(
        bay_outer_base_mesh,
        source_ground_z,
        barycentric_divisions=6,
    )
    bay_mesh_max_unsupported_gap = float(
        bay_bottom_mesh_ground_qa["maximum_mesh_bottom_above_ground_m"]
    )
    bay_mesh_max_actual_foundation_cut = float(
        bay_bottom_mesh_ground_qa["maximum_actual_cut_below_ground_m"]
    )
    bay_mesh_min_residual_ground_key_in = float(
        bay_bottom_mesh_ground_qa["minimum_residual_ground_key_in_m"]
    )
    bay_max_unsupported_gap = max(
        bay_analytic_max_unsupported_gap,
        bay_mesh_max_unsupported_gap,
    )
    bay_max_actual_foundation_cut = max(
        float(bay_exact_tin_formation_qa["actual"]["maximum_cut_below_ground_m"]),
        bay_mesh_max_actual_foundation_cut,
    )
    bay_min_residual_ground_key_in = min(
        float(bay_exact_tin_formation_qa["actual"]["minimum_ground_key_in_m"]),
        bay_mesh_min_residual_ground_key_in,
    )
    bay_outer_vertices = np.asarray(bay_outer_base_mesh.vertices, dtype=float)
    bay_outer_faces = np.asarray(bay_outer_base_mesh.faces, dtype=int)
    bay_outer_normals = np.asarray(bay_outer_base_mesh.face_normals, dtype=float)
    bay_bottom_vertex_ids = np.unique(bay_outer_faces[bay_outer_normals[:, 2] < -0.50].reshape(-1))
    bay_bottom_planarity_residual = float(max(
        (
            abs(
                float(bay_outer_vertices[index, 2])
                - bay_actual_foundation_bottom_z(
                    float(bay_outer_vertices[index, 0]),
                    float(bay_outer_vertices[index, 1]),
                )
            )
            for index in bay_bottom_vertex_ids
        ),
        default=math.inf,
    ))
    if bay_max_unsupported_gap > 1.0e-6:
        raise RuntimeError(
            "D3 emergency bay triangulated foundation floats above original ground by "
            f"{bay_max_unsupported_gap:.9f} m"
        )
    if bay_max_actual_foundation_cut > 0.950001:
        raise RuntimeError(
            "D3 emergency bay triangulated foundation exceeds the 0.95 m cut gate: "
            f"{bay_max_actual_foundation_cut:.6f} m"
        )
    if bay_min_residual_ground_key_in < bay_minimum_ground_key_in - 1.0e-6:
        raise RuntimeError(
            "D3 emergency bay triangulated foundation misses the 100 mm key-in gate: "
            f"{bay_min_residual_ground_key_in:.9f} m"
        )
    if bay_bottom_planarity_residual > 1.0e-8:
        raise RuntimeError(
            "D3 emergency bay foundation underside is not one plane: "
            f"maximum residual={bay_bottom_planarity_residual:.12f} m"
        )
    bay_outer_base_quality = mesh_quality(bay_outer_base_mesh)
    bay_outer_base_components = len(bay_outer_base_mesh.split(only_watertight=False))
    bay_outer_base_quality["connected_components"] = bay_outer_base_components
    if (
        not bay_outer_base_quality["watertight"]
        or not bay_outer_base_quality["winding_consistent"]
        or bay_outer_base_quality["open_or_nonmanifold_edges"] != 0
        or bay_outer_base_quality["zero_area_faces"] != 0
        or bay_outer_base_components != 1
    ):
        raise RuntimeError(
            "D3 emergency bay outer foundation mesh quality failed: "
            + json.dumps(bay_outer_base_quality, ensure_ascii=False)
        )
    bay_mesh = bay_surface_mesh
    bay_mesh_components = len(bay_mesh.split(only_watertight=False))
    if bay_mesh_components != 1:
        raise RuntimeError(f"D3 emergency bay mesh must be one connected component, got {bay_mesh_components}")
    shoulder_support_steps = []
    transition_support_steps = []
    for y in np.linspace(bay_seam_y, bay_outer_y, 49):
        for x in np.linspace(bay_seam_start_x, bay_seam_end_x, 97):
            point = Point(float(x), float(y))
            if shoulder_support_poly.buffer(1.0e-9).contains(point):
                shoulder_support_steps.append(
                    abs((bay_surface_z(x, y) - 0.12) - (profiles["D3"].surface_z(x, y) - 0.12))
                )
            if bay_subbase_only.buffer(1.0e-9).contains(point):
                transition_support_steps.append(
                    abs((bay_surface_z(x, y) - 0.36) - (profiles["D3"].surface_z(x, y) - 0.36))
                )
    bay_shoulder_support_step = float(max(shoulder_support_steps, default=math.inf))
    bay_transition_support_step = float(max(transition_support_steps, default=math.inf))
    if max(bay_shoulder_support_step, bay_transition_support_step) > 0.005001:
        raise RuntimeError(
            "D3 emergency bay existing-layer support mismatch: "
            f"shoulder={bay_shoulder_support_step:.6f} m; "
            f"subbase={bay_transition_support_step:.6f} m"
        )

    nominal_outer_volume = float(bay_outer_foundation.area * bay_outer_base_nominal_thickness)
    actual_outer_volume = float(abs(bay_outer_base_mesh.volume))
    bay_layer_support = {
        "surface_course_thickness_m": 0.12,
        "existing_shoulder_support_overlap_m2": float(shoulder_support_poly.area),
        "levelling_layer_area_m2": float(bay_subbase_only.area),
        "levelling_layer_thickness_m": 0.24,
        "outer_foundation_area_m2": float(bay_outer_foundation.area),
        "outer_foundation_nominal_thickness_m": bay_outer_base_nominal_thickness,
        "outer_foundation_required_minimum_ground_key_in_m": bay_minimum_ground_key_in,
        "outer_foundation_verified_exact_tin_minimum_ground_key_in_m": float(
            bay_exact_tin_formation_qa["actual"]["minimum_ground_key_in_m"]
        ),
        "outer_foundation_bottom_geometry": "SINGLE_ENGINEERED_PLANE",
        "outer_foundation_bottom_plane": bay_foundation_bottom_plane,
        "outer_foundation_bottom_plane_grade_pct": bay_foundation_bottom_plane_grade_pct,
        "outer_foundation_bottom_planarity_residual_m": bay_bottom_planarity_residual,
        "outer_foundation_minimum_actual_thickness_m": bay_min_actual_foundation_thickness,
        "outer_foundation_maximum_actual_thickness_m": bay_max_actual_foundation_thickness,
        "outer_foundation_nominal_volume_m3": nominal_outer_volume,
        "outer_foundation_actual_volume_m3": actual_outer_volume,
        "outer_foundation_local_deepening_volume_m3": max(actual_outer_volume - nominal_outer_volume, 0.0),
        "surface_to_d3_asphalt_step_m": bay_max_vertical_step,
        "surface_bottom_to_shoulder_top_step_m": bay_shoulder_support_step,
        "levelling_bottom_to_subbase_top_step_m": bay_transition_support_step,
        "outer_foundation_overlap_with_road_subbase_m2": float(
            bay_outer_foundation.intersection(road_subbase_union).area
        ),
        "support_partition_maximum_pairwise_overlap_m2": bay_support_pairwise_overlap,
        "support_partition_coverage_gap_m2": bay_support_coverage_gap,
        "maximum_actual_unsupported_gap_m": bay_max_unsupported_gap,
        "maximum_actual_foundation_cut_m": bay_max_actual_foundation_cut,
        "exact_source_tin_formation_qa": bay_exact_tin_formation_qa,
        "mesh_to_original_ground_qa": bay_bottom_mesh_ground_qa,
        "outer_foundation_mesh_quality": bay_outer_base_quality,
        "formation_control_anchors": bay_formation_anchors,
    }
    if bay_layer_support["outer_foundation_overlap_with_road_subbase_m2"] > 1.0e-6:
        raise RuntimeError("D3 emergency bay outer foundation overlaps the road subbase")
    emergency_bay_coordination = {
        "overall_dimensions_m": [24.0, 6.0],
        "outer_stopping_edge_length_m": 20.0,
        "design_vehicle_length_m": 16.5,
        "area_m2": float(bay_poly.area),
        "plan_component_count": bay_components,
        "mesh_component_count": bay_mesh_components,
        "primary_road_overlap_m2": bay_road_overlap,
        "d3_gap_m": bay_d3_gap,
        "shared_d3_seam_m": bay_d3_seam,
        "maximum_vertical_step_m": bay_max_vertical_step,
        "longitudinal_grade_pct": bay_longitudinal_grade,
        "crossfall_pct": bay_crossfall_pct,
        "maximum_resultant_grade_pct": bay_resultant_grade,
        "original_ground_reference": {
            "file": SOURCE_REVP2_GLB.name,
            "sha256": source_terrain_sha,
            "surface_object": source_terrain_name,
            "method": "Rev.P2 LinearND terrain interpolation; exact clipped-TIN extrema plus independent mesh barycentric QA",
        },
        "maximum_nominal_formation_cut_depth_m": bay_max_cut_depth,
        "maximum_nominal_formation_fill_depth_m": bay_max_fill_depth,
        "maximum_actual_unsupported_gap_m": bay_max_unsupported_gap,
        "maximum_actual_foundation_cut_m": bay_max_actual_foundation_cut,
        "foundation_bottom_geometry": "SINGLE_ENGINEERED_PLANE",
        "foundation_bottom_plane_grade_pct": bay_foundation_bottom_plane_grade_pct,
        "foundation_bottom_planarity_residual_m": bay_bottom_planarity_residual,
        "exact_source_tin_formation_qa": bay_exact_tin_formation_qa,
        "mesh_to_original_ground_qa": bay_bottom_mesh_ground_qa,
        "outer_foundation_mesh_quality": bay_outer_base_quality,
        "terrain_cut_stats": bay_terrain_cut_stats,
        "terrain_vertices_remaining_inside_bay": terrain_vertices_inside_bay,
        "road_layer_support": bay_layer_support,
        "status": "PASS",
    }
    register_feature(
        "REV_P5_MP_D3_EMERGENCY_BAY", "Road safety", "CONTROLLED_PRE_FEED", bay_poly,
        "Connected tapered 24 x 6 m emergency lay-by on the terrain-balanced y=244 D3 reach, with a 20 m stopping edge, full D3 surface continuation and a single engineered foundation plane keyed at least 100 mm into verified source ground.",
        bay_surface_mesh,
        {
            "Road": "D3",
            "Use": "Emergency stop / passing bay",
            "Dimensions": "24x6 m overall; 20 m outer stopping edge",
            "Crossfall": f"{bay_crossfall_pct:.3f}% continuation of D3 design surface",
            "Layering": "120 mm surface over existing shoulder / levelling strip / variable-depth outer foundation to one engineered plane with at least 100 mm source-ground key-in",
        },
    )
    add_mesh(
        target,
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_TRANSITION",
        bay_transition_mesh,
        {"Parent": "REV_P5_MP_D3_EMERGENCY_BAY", "Layer": "Levelling over D3 subbase-only strip"},
    )
    add_mesh(
        target,
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_OUTER",
        bay_outer_base_mesh,
        {"Parent": "REV_P5_MP_D3_EMERGENCY_BAY", "Layer": "Independent outer pavement foundation"},
    )
    new_mesh_names.extend([
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_TRANSITION",
        "REV_P5_MP_D3_EMERGENCY_BAY_BASE_OUTER",
    ])

    # 5. Quarantine area for nonconforming incoming tyres.
    quarantine = box(178.0, 350.0, 238.0, 385.0)
    checks["quarantine"] = physical_feature_check("quarantine", quarantine, building_union, road_union)
    quarantine_z = top_for_polygon(quarantine, z_at, 0.30)
    q_slab = flat_solid(quarantine, quarantine_z, 0.28, COLORS["quarantine"])
    q_fence = perimeter_boxes(quarantine, quarantine_z, COLORS["fence"], 2.0, 0.10)
    register_feature(
        "REV_P5_MP_TIRE_QUARANTINE", "Raw material logistics", "CONTROLLED_PRE_FEED", quarantine,
        "Fenced quarantine area for nonconforming tyre batches with segregated dirty drainage requirement.",
        trimesh.util.concatenate([q_slab, q_fence]),
        {"Area_Type": "Quarantine", "Drainage": "Dirty / isolated", "Gate": "Environmental basis"},
    )

    # 6. Protected pedestrian route. It passes north of the relocated clean-snow
    # area, west of both crane pads and terminates at the access-control point
    # outside the preliminary process-safety envelope. Road crossings are
    # intentional; edge posts are omitted only across the carriageway.
    ped_points = [(177.0, 92.0), (177.0, 115.0), (250.0, 115.0), (250.0, 140.0), (300.0, 140.0), (300.0, 195.0), (310.0, 202.0), (310.0, 252.0), (335.0, 252.0)]
    def ped_z(x: float, y: float) -> float:
        point = Point(x, y)
        candidates = []
        for code, poly in road_polys.items():
            if poly.buffer(0.05).contains(point):
                candidates.append(profiles[code].surface_z(x, y) + 0.09)
        return float(max(candidates) if candidates else z_at(x, y) + 0.18)
    ped_line = LineString(ped_points)
    ped_poly = ped_line.buffer(1.25, cap_style=2, join_style=2)
    ped_walkway = route_ribbon(ped_points, ped_z, 2.5, COLORS["pedestrian"], 0.06)
    ped_posts, ped_post_count = protected_route_posts(ped_points, ped_z, road_union, route_width=2.5)
    ped_mesh = trimesh.util.concatenate([ped_walkway, ped_posts])
    ped_building_overlap = float(ped_poly.intersection(building_union).area)
    ped_safety_overlap = float(ped_poly.intersection(safety_poly).area)
    ped_crane_overlap = float(ped_poly.intersection(unary_union(crane_polys)).area)
    if max(ped_building_overlap, ped_safety_overlap, ped_crane_overlap) > 1.0e-6:
        raise RuntimeError(
            "Protected pedestrian route conflict: "
            + json.dumps(
                {
                    "building_m2": ped_building_overlap,
                    "preliminary_safety_zone_m2": ped_safety_overlap,
                    "crane_pad_m2": ped_crane_overlap,
                },
                ensure_ascii=False,
            )
        )
    checks["protected_pedestrian_route"] = {
        "width_m": 2.5,
        "protection_post_count": ped_post_count,
        "building_intersection_m2": ped_building_overlap,
        "preliminary_safety_zone_intersection_m2": ped_safety_overlap,
        "crane_pad_intersection_m2": ped_crane_overlap,
        "intentional_road_crossing_area_m2": float(ped_poly.intersection(road_union).area),
    }
    register_feature(
        "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE", "Personnel safety", "CONTROLLED_PRE_FEED", ped_poly,
        "Protected 2.5 m pedestrian corridor with edge bollards from the lower checkpoint to the controlled boundary of the pyrolysis safety zone.",
        ped_mesh,
        {"Width": "2.5 m", "Protection": "Twin edge bollards outside road crossings", "Gate": "Rev.P5 Integrated"},
        spatial_role="PERSONNEL_ROUTE",
    )

    # 7. Dry/hybrid cooler reserve 40 x 25 m in the lower utility zone.
    cooler = box(420.0, 45.0, 460.0, 70.0)
    checks["cooler"] = physical_feature_check("cooler", cooler, building_union, road_union)
    cooler_z = top_for_polygon(cooler, z_at, 0.22)
    register_feature(
        "REV_P5_MP_DRY_HYBRID_COOLER_RESERVE_40x25", "Utilities", "OPEN_RFI", cooler,
        "Controlled 40 x 25 m reserve for dry/hybrid cooling equipment; final duty and type require heat balance.",
        flat_solid(cooler, cooler_z, 0.20, COLORS["cooler"]),
        {"Dimensions": "40x25 m", "RFI": "RFI-A-07", "Data_Status": "OPEN_RFI"},
    )

    # 8. Coordinated clean and dirty snow areas. The inherited Rev.P2 footprints
    # became incompatible with the corrected roads (clean/D4 and dirty/D3-D5),
    # so they are physically relocated without changing their accepted areas.
    snow_found = {}
    snow_specs = [
        ("clean_snow", box(60.0, 35.0, 140.0, 87.0), "REV_P5_MP_CLEAN_SNOW_CONTAINMENT", COLORS["snow_clean"]),
        ("dirty_snow", box(560.0, 25.0, 590.0, 60.0), "REV_P5_MP_DIRTY_SNOW_CONTAINMENT", COLORS["snow_dirty"]),
    ]
    snow_polys = {}
    for source_name, poly, name, color in snow_specs:
        checks[source_name] = physical_feature_check(source_name, poly, building_union, road_union)
        z = top_for_polygon(poly, z_at, 0.20)
        snow_polys[source_name] = poly
        snow_found[source_name] = list(poly.bounds)
        snow_slab = flat_solid(poly, z, 0.18, color)
        snow_berm = perimeter_boxes(poly, z, color, 0.55, 0.18)
        register_feature(
            name,
            "Winter operation",
            "CONTROLLED_PRE_FEED",
            poly,
            "Relocated graded snow-management pad with raised containment, separated from the corrected road system.",
            trimesh.util.concatenate([snow_slab, snow_berm]),
            {
                "Snow_Class": "Clean" if source_name == "clean_snow" else "Contaminated",
                "Relocated_From_RevP2": source_name,
                "Relocation_Reason": "Corrected road and internal masterplan coordination",
            },
        )

    # 9. Physical capped phase-2 utility stubs at the western boundary of the
    # future 1.595 ha expansion reserve. The caps are placed north of D2/D3,
    # outside road, shoulder and vehicle-clearance envelopes.
    stub_parts = []
    stub_specs = [
        ("FW", 462.0, 400.0, 0.30, COLORS["stub_fw"]),
        ("CW-S", 462.0, 405.0, 0.24, COLORS["stub_cw"]),
        ("CW-R", 462.0, 410.0, 0.24, COLORS["stub_cw"]),
        ("PG", 462.0, 415.0, 0.20, COLORS["stub_pg"]),
    ]
    stub_footprints = []
    for system, x, y, radius, color in stub_specs:
        stub_footprints.append(Point(x, y).buffer(radius * 1.35, resolution=12))
        base_z = z_at(x, y) + 0.15
        pipe = trimesh.creation.cylinder(radius=radius, height=2.2, sections=20)
        pipe.apply_translation([x, y, base_z + 1.1])
        color_mesh(pipe, color)
        stub_parts.append(pipe)
        cap = trimesh.creation.cylinder(radius=radius * 1.35, height=0.15, sections=20)
        cap.apply_translation([x, y, base_z + 2.25])
        color_mesh(cap, color)
        stub_parts.append(cap)
    electrical_specs = (("10KV", 467.0, 420.0, COLORS["stub_power"]), ("CONTROL", 467.0, 425.0, COLORS["stub_control"]))
    for system, x, y, color in electrical_specs:
        stub_footprints.append(box(x - 0.6, y - 0.6, x + 0.6, y + 0.6))
        z = z_at(x, y) + 0.75
        marker = trimesh.creation.box(extents=(1.2, 1.2, 1.5))
        marker.apply_translation([x, y, z])
        color_mesh(marker, color)
        stub_parts.append(marker)
    stub_zone = unary_union(stub_footprints).buffer(0)
    checks["phase2_capped_stubs"] = physical_feature_check("phase2_capped_stubs", stub_zone, building_union, road_union)
    register_feature(
        "REV_P5_MP_PHASE2_CAPPED_STUBS", "Phase 2 interfaces", "CONTROLLED_PRE_FEED", stub_zone,
        "Visible capped reserves for FW, CW supply/return, pyrolysis gas, 10 kV and control at the phase-2 boundary, north of all active road corridors.",
        trimesh.util.concatenate(stub_parts),
        {
            "Phase": "2",
            "Capacity_Increment": "+10,000 t/y",
            "Reserve_Area": "1.595 ha",
            "Systems": [system for system, *_ in stub_specs] + [system for system, *_ in electrical_specs],
            "Road_Clearance_Status": "PASS",
        },
    )

    # 10. One-way circulation arrows on raw and product loops.
    for code, object_name in (("D2", "REV_P5_MP_RAW_LOOP_ONE_WAY_MARKINGS"), ("D5", "REV_P5_MP_PRODUCT_LOOP_ONE_WAY_MARKINGS")):
        path = max(profiles[code].paths, key=lambda p: roadmod.cumulative_xy(p)[-1])
        stations = roadmod.cumulative_xy(path)
        arrow_parts = []
        arrow_footprints = []
        arrow_local = np.asarray([(-2.2, -0.42), (0.4, -0.42), (0.4, -1.05), (2.45, 0.0), (0.4, 1.05), (0.4, 0.42), (-2.2, 0.42)], dtype=float)
        for fraction in (0.18, 0.38, 0.58, 0.78):
            target_station = stations[-1] * fraction
            index = int(np.argmin(np.abs(stations - target_station)))
            x, y = path[index, :2]
            z = profiles[code].surface_z(x, y) + 0.045
            heading = profile_tangent(path, index)
            arrow_parts.append(arrow_mesh(float(x), float(y), float(z), heading, COLORS["arrow"]))
            rotation = np.asarray([[math.cos(heading), -math.sin(heading)], [math.sin(heading), math.cos(heading)]])
            arrow_xy = arrow_local @ rotation.T + np.asarray([x, y])
            arrow_footprints.append(Polygon(arrow_xy))
        arrow_zone = unary_union(arrow_footprints).buffer(0)
        arrow_outside_road = float(arrow_zone.difference(road_polys[code].buffer(0.05)).area)
        if arrow_outside_road > 1.0e-6:
            raise RuntimeError(f"{object_name} leaves {code} pavement by {arrow_outside_road:.6f} m2")
        checks[f"one_way_{code}"] = {"arrow_count": len(arrow_parts), "outside_designated_road_m2": arrow_outside_road}
        register_feature(object_name, "Traffic management", "CONTROLLED_PRE_FEED", arrow_zone,
                         f"One-way circulation markings derived from the accepted {code} axis.",
                         trimesh.util.concatenate(arrow_parts), {"Road": code, "Direction": "Along model axis"},
                         spatial_role="TRAFFIC_MARKING")

    # 11. Dedicated BLD_05 high-level service ramp to D3. It is deliberately
    # not connected to the lower D5 product loop.
    start = Point(deck_poly.bounds[2], deck_poly.centroid.y)
    d3_boundary = road_polys["D3"].boundary
    seam = nearest_points(start, d3_boundary)[1]
    ramp_line = LineString([(start.x, start.y), (seam.x, seam.y)])
    if ramp_line.length < 30.0:
        raise RuntimeError("BLD_05 ramp did not select the eastern D3 interface")
    other_buildings = building_union.difference(deck_poly)
    ramp_poly = ramp_line.buffer(3.5, cap_style=2, join_style=2).difference(deck_poly).difference(road_union).difference(other_buildings.buffer(0.05)).buffer(0)
    ramp_end_z = profiles["D3"].surface_z(seam.x, seam.y)
    ramp_grade = abs(deck_top - ramp_end_z) / ramp_line.length
    if ramp_grade > 0.06:
        raise RuntimeError(f"BLD_05 service ramp grade {100*ramp_grade:.3f}% exceeds 6%")
    def ramp_z(x: float, y: float) -> float:
        t = max(0.0, min(1.0, ramp_line.project(Point(x, y)) / ramp_line.length))
        smooth = t * t * (3.0 - 2.0 * t)
        return float(deck_top + (ramp_end_z - deck_top) * smooth)
    checks["bld05_ramp"] = physical_feature_check("bld05_ramp", ramp_poly, other_buildings, road_union)
    register_feature(
        "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3", "Service access", "CONTROLLED_PRE_FEED", ramp_poly,
        "Dedicated high-level ramp from BLD_05 pyrolysis terrace to D3; replaces the invalid short link to lower D5.",
        roadmod.solid_from_polygon(ramp_poly, ramp_z, 0.30, COLORS["ramp"], 2.0),
        {"Road": "D3", "Length_m": ramp_line.length, "Grade_pct": 100.0 * ramp_grade},
    )

    # 12. Controlled spatial reserves for systems missing from the prior model.
    reserve_specs = [
        ("REV_P5_MP_LABORATORY_RESERVE", box(352.0, 70.0, 364.0, 78.0), COLORS["laboratory"], "Quality laboratory reserve for feedstock, oil and rCB testing; relocated clear of clean-snow storage."),
        ("REV_P5_MP_WASTEWATER_TREATMENT_RESERVE", box(500.0, 25.0, 540.0, 45.0), COLORS["los"], "Reserve for local treatment of process, storm and oily wastewater."),
        ("REV_P5_MP_DG_UPS_RESERVE", box(395.0, 70.0, 415.0, 85.0), COLORS["dgups"], "Reserve for emergency generator and UPS supporting safety loads."),
        ("REV_P5_MP_HVAC_HEAT_SOURCE_RESERVE", box(340.0, 50.0, 358.0, 66.0), COLORS["hvac"], "Reserve for heat source, HVAC and emergency ventilation equipment; coordinated outside retaining walls and snow storage."),
    ]
    for name, poly, color, note in reserve_specs:
        checks[name] = physical_feature_check(name, poly, building_union, road_union)
        z = top_for_polygon(poly, z_at, 0.20)
        register_feature(name, "Missing system spatial reserve", "OPEN_CRITICAL", poly, note,
                         flat_solid(poly, z, 0.18, color), {"Data_Status": "OPEN_CRITICAL", "Gate": "FG-06/FG-07"})

    # 13. Preliminary process-safety envelope around the pyrolysis building.
    safety_z = deck_top + 0.08
    register_feature(
        "REV_P5_SAFETY_PRELIM_PYROLYSIS_ZONE", "Safety annotation", "OPEN_CRITICAL", safety_poly,
        "Preliminary spatial envelope for Ex/fire/F&G coordination. It is not a final hazardous-area classification.",
        roadmod.solid_from_polygon(safety_poly, lambda x, y: safety_z, 0.05, COLORS["safety"], 4.0),
        {
            "Data_Status": "OPEN_CRITICAL",
            "Disclaimer": "Not final Ex classification",
            "Crane_Pad_Overlap": "Accepted only by phase separation: temporary construction before commissioning",
            "Ramp_Overlap": "Controlled permanent access crossing; operational permit and final HAZID remain hold points",
        },
        spatial_role="SAFETY_ANNOTATION",
    )

    # Cross-coordinate every physical Rev.P5 addition against every other one.
    # Annotation-only overlays (safety envelope, traffic arrows and the
    # preliminary heavy-haul clearance envelope) are controlled separately.
    physical_pairwise = []
    unapproved_pairwise = []
    physical_names = sorted(physical_footprints)
    for first_index, first in enumerate(physical_names):
        for second in physical_names[first_index + 1:]:
            overlap = float(physical_footprints[first].intersection(physical_footprints[second]).area)
            if overlap <= 1.0e-6:
                continue
            row = {
                "objects": [first, second],
                "plan_overlap_m2": overlap,
                "status": "FAIL_UNAPPROVED_PHYSICAL_OVERLAP",
            }
            physical_pairwise.append(row)
            unapproved_pairwise.append(row)
    if unapproved_pairwise:
        raise RuntimeError("Unapproved Rev.P5 physical overlaps: " + json.dumps(unapproved_pairwise, ensure_ascii=False))

    # The heavy-haul object is a preliminary swept-clearance overlay, not a
    # second physical slab.  Every overlap with a physical Rev.P5 feature is
    # nevertheless recorded and must have an explicit coordination basis.
    haul_allowed_bases = {
        "REV_P5_MP_ASSEMBLY_PAD_60x40": "INTENTIONAL_ROUTE_TERMINUS_AT_ASSEMBLY_PAD",
        "REV_P5_MP_D3_EMERGENCY_BAY": "CONTROLLED_SHARED_D3_RECOVERY_SEGMENT__CERTIFIED_SWEPT_PATH_HOLD_POINT",
        "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE": "CONTROLLED_GRADE_SEPARATION_OR_MARKED_CROSSING__TRAFFIC_PLAN_HOLD_POINT",
        "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3": "CONTROLLED_COMMON_D3_ACCESS__TRAFFIC_PLAN_HOLD_POINT",
    }
    heavy_haul_clearance_coordination = []
    unexpected_haul_overlaps = []
    for name in physical_names:
        overlap = float(feature_footprints[name].intersection(haul_envelope).area)
        if overlap <= 1.0e-6:
            continue
        basis = haul_allowed_bases.get(name)
        row = {
            "object": name,
            "plan_overlap_m2": overlap,
            "coordination_basis": basis or "UNAPPROVED_CLEARANCE_CONFLICT",
        }
        heavy_haul_clearance_coordination.append(row)
        if basis is None:
            unexpected_haul_overlaps.append(row)
    if unexpected_haul_overlaps:
        raise RuntimeError(
            "Unexpected heavy-haul clearance overlaps: "
            + json.dumps(unexpected_haul_overlaps, ensure_ascii=False)
        )

    safety_coordination = []
    for name in ("REV_P5_MP_CRANE_PAD_01", "REV_P5_MP_CRANE_PAD_02", "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3", "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE"):
        overlap = float(feature_footprints[name].intersection(safety_poly).area)
        if name == "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE" and overlap > 1.0e-6:
            raise RuntimeError(f"Protected personnel route enters preliminary safety zone by {overlap:.6f} m2")
        if "CRANE_PAD" in name and overlap > 1.0e-6:
            basis = "ACCEPTED_PHASE_SEPARATED_CONSTRUCTION_BEFORE_COMMISSIONING"
        elif "SERVICE_RAMP" in name and overlap > 1.0e-6:
            basis = "CONTROLLED_OPERATIONAL_ACCESS__FINAL_HAZID_HOLD_POINT"
        else:
            basis = "NO_PLAN_OVERLAP"
        safety_coordination.append({"object": name, "overlap_m2": overlap, "coordination_basis": basis})

    dimension_checks = {
        "assembly_pad": {
            "required_m": [60.0, 40.0],
            "actual_m": [float(assembly.bounds[2] - assembly.bounds[0]), float(assembly.bounds[3] - assembly.bounds[1])],
            "area_m2": float(assembly.area),
        },
        "cooler_reserve": {
            "required_m": [40.0, 25.0],
            "actual_m": [float(cooler.bounds[2] - cooler.bounds[0]), float(cooler.bounds[3] - cooler.bounds[1])],
            "area_m2": float(cooler.area),
        },
        "crane_pads": {
            "required_each_m": [18.0, 14.0],
            "actual_each_m": [[float(poly.bounds[2] - poly.bounds[0]), float(poly.bounds[3] - poly.bounds[1])] for poly in crane_polys],
        },
        "protected_pedestrian_width_m": 2.5,
        "heavy_haul_preliminary_envelope_width_m": haul_width,
        "clean_snow_area_m2": float(snow_polys["clean_snow"].area),
        "dirty_snow_area_m2": float(snow_polys["dirty_snow"].area),
    }
    if dimension_checks["assembly_pad"]["actual_m"] != [60.0, 40.0]:
        raise RuntimeError("Assembly pad dimension drift")
    if dimension_checks["cooler_reserve"]["actual_m"] != [40.0, 25.0]:
        raise RuntimeError("Cooler reserve dimension drift")
    if any(value != [18.0, 14.0] for value in dimension_checks["crane_pads"]["actual_each_m"]):
        raise RuntimeError("Crane pad dimension drift")

    # Required-feature and mesh QA.
    missing = [name for name in REQUIRED_FEATURES if name not in target.geometry]
    if missing:
        raise RuntimeError(f"Required masterplan features missing: {missing}")

    mesh_qa = {}
    for name in new_mesh_names:
        quality = mesh_quality(target.geometry[name])
        mesh_qa[name] = quality
        if not quality["finite_coordinates"] or quality["zero_area_faces"] != 0 or not quality["winding_consistent"]:
            raise RuntimeError(f"Invalid Rev.P5 mesh {name}: {quality}")

    # Site bounds and reservation dimensions.
    site_xy = box(terrain_bounds[0, 0], terrain_bounds[0, 1], terrain_bounds[1, 0], terrain_bounds[1, 1])
    out_of_site = []
    for row in register:
        if row["Bounds_XY"] is None:
            continue
        poly = box(*row["Bounds_XY"])
        outside = float(poly.difference(site_xy).area)
        if outside > 1e-6:
            out_of_site.append({"object": row["Object_Name"], "outside_m2": outside})
    if out_of_site:
        raise RuntimeError(f"Rev.P5 additions outside site surface: {out_of_site}")

    qa = {
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "status": "PASS_CONTROLLED_PRE_FEED",
        "not_for_construction": True,
        "source_road_qa": road_qa,
        "d3_d5_junction_geometry": d3_d5_qa,
        "road_acceptance_reused": road_qa.get("acceptance", {}),
        "masterplan_changes": register,
        "required_features": REQUIRED_FEATURES,
        "missing_required_features": missing,
        "physical_feature_checks": checks,
        "physical_feature_pairwise_coordination": {
            "checked_feature_count": len(physical_names),
            "overlaps": physical_pairwise,
            "unapproved_overlap_count": len(unapproved_pairwise),
            "status": "PASS" if not unapproved_pairwise else "FAIL",
        },
        "safety_annotation_coordination": safety_coordination,
        "heavy_haul_clearance_coordination": heavy_haul_clearance_coordination,
        "dimension_checks": dimension_checks,
        "emergency_bay_coordination": emergency_bay_coordination,
        "relocated_source_snow_objects": relocated_source_snow,
        "bld05_service_ramp": {
            "line_length_m": float(ramp_line.length),
            "deck_top_z_m": deck_top,
            "d3_seam_z_m": float(ramp_end_z),
            "grade_pct": float(100.0 * ramp_grade),
            "road_overlap_m2": float(ramp_poly.intersection(road_union).area),
            "other_building_overlap_m2": float(ramp_poly.intersection(other_buildings).area),
        },
        "snow_zone_bounds": snow_found,
        "site_bounds": terrain_bounds.tolist(),
        "out_of_site_features": out_of_site,
        "mesh_quality_new_features": mesh_qa,
        "acceptance": {
            "road_building_clashes": road_qa.get("road_building_clashes", []),
            "d3_d5_junction_status": d3_d5_qa.get("status"),
            "d3_d5_road_final_overlap_m2": float(d3_d5_qa["layers"]["ROAD"]["final_overlap_m2"]),
            "d3_d5_maximum_full_seam_vertical_step_m": float(
                d3_d5_qa["maximum_full_seam_vertical_step_m"]
            ),
            "d3_d5_blended_maximum_centerline_grade_pct": float(
                d3_d5_qa["d5_blended_maximum_centerline_grade_pct"]
            ),
            "d3_d5_maximum_resultant_surface_grade_pct": float(
                d3_d5_qa["d5_maximum_resultant_surface_grade_pct"]
            ),
            "d3_d5_minimum_road_shoulder_vertical_overlap_m": float(
                d3_d5_qa["layer_nesting"]["minimum_road_shoulder_vertical_overlap_m"]
            ),
            "d3_d5_maximum_road_shoulder_vertical_overlap_m": float(
                d3_d5_qa["layer_nesting"]["maximum_road_shoulder_vertical_overlap_m"]
            ),
            "d3_d5_minimum_shoulder_subbase_vertical_overlap_m": float(
                d3_d5_qa["layer_nesting"]["minimum_shoulder_subbase_vertical_overlap_m"]
            ),
            "d3_d5_maximum_shoulder_subbase_vertical_overlap_m": float(
                d3_d5_qa["layer_nesting"]["maximum_shoulder_subbase_vertical_overlap_m"]
            ),
            "d3_d5_reverse_grade_sample_count": int(sum(
                d3_d5_qa["d5_blended_reverse_grade_sample_count_by_layer"].values()
            )),
            "d3_d5_maximum_interlayer_design_surface_divergence_m": float(
                d3_d5_qa["layer_nesting"]["maximum_interlayer_design_surface_divergence_m"]
            ),
            "d3_d5_protected_sliver_removals": len(d3_d5_qa.get("protected_sliver_removals", [])),
            "open_external_critical_clashes": int(road_qa["acceptance"].get("open_external_critical_clashes", -1)),
            "terrain_above_road_points": int(road_qa["acceptance"].get("terrain_above_road_points", -1)),
            "non_adjacent_road_triangle_self_intersections": int(road_qa["acceptance"].get("non_adjacent_road_triangle_self_intersections", -1)),
            "duplicated_top_faces": int(road_qa["acceptance"].get("duplicated_top_faces", -1)),
            "non_manifold_edges": int(road_qa["acceptance"].get("non_manifold_edges", -1)),
            "road_layer_quality_triangulation_status": road_acceptance[
                "road_layer_quality_triangulation_status"
            ],
            "road_layer_maximum_chord_residual_m": float(
                road_acceptance["road_layer_maximum_chord_residual_m"]
            ),
            "road_layer_maximum_chord_residual_limit_m": float(
                road_acceptance["road_layer_maximum_chord_residual_limit_m"]
            ),
            "d5_layer_maximum_significant_facet_grade_pct": float(
                road_acceptance["d5_layer_maximum_significant_facet_grade_pct"]
            ),
            "d5_layer_maximum_all_retained_facet_grade_pct": float(
                road_acceptance["d5_layer_maximum_all_retained_facet_grade_pct"]
            ),
            "d5_layer_export_facet_grade_limit_pct": float(
                road_acceptance["d5_layer_export_facet_grade_limit_pct"]
            ),
            "significant_plan_face_area_threshold_m2": float(
                road_acceptance["significant_plan_face_area_threshold_m2"]
            ),
            "road_layer_microscopic_retained_top_face_count": int(
                road_acceptance["road_layer_microscopic_retained_top_face_count"]
            ),
            "road_layer_microscopic_retained_top_face_area_m2": float(
                road_acceptance["road_layer_microscopic_retained_top_face_area_m2"]
            ),
            "road_layer_pslg_precision_grid_m": float(
                road_acceptance["road_layer_pslg_precision_grid_m"]
            ),
            "road_layer_precision_snap_area_delta_m2": float(
                road_acceptance["road_layer_precision_snap_area_delta_m2"]
            ),
            "road_layer_maximum_component_precision_snap_area_delta_m2": float(
                road_acceptance[
                    "road_layer_maximum_component_precision_snap_area_delta_m2"
                ]
            ),
            "road_layer_maximum_component_precision_snap_area_tolerance_m2": float(
                road_acceptance[
                    "road_layer_maximum_component_precision_snap_area_tolerance_m2"
                ]
            ),
            "exported_road_layer_quality_status": road_acceptance[
                "exported_road_layer_quality_status"
            ],
            "exported_road_layer_maximum_significant_chord_residual_m": float(
                road_acceptance[
                    "exported_road_layer_maximum_significant_chord_residual_m"
                ]
            ),
            "exported_road_layer_maximum_all_retained_chord_residual_m": float(
                road_acceptance[
                    "exported_road_layer_maximum_all_retained_chord_residual_m"
                ]
            ),
            "exported_road_layer_maximum_chord_residual_limit_m": float(
                road_acceptance[
                    "exported_road_layer_maximum_chord_residual_limit_m"
                ]
            ),
            "exported_road_layer_top_vertex_design_surface_tolerance_m": float(
                road_acceptance[
                    "exported_road_layer_top_vertex_design_surface_tolerance_m"
                ]
            ),
            "exported_d5_layer_maximum_significant_facet_grade_pct": float(
                road_acceptance[
                    "exported_d5_layer_maximum_significant_facet_grade_pct"
                ]
            ),
            "exported_d5_layer_maximum_all_retained_facet_grade_pct": float(
                road_acceptance[
                    "exported_d5_layer_maximum_all_retained_facet_grade_pct"
                ]
            ),
            "exported_road_layer_significant_top_face_nonpositive_normal_count": int(
                road_acceptance[
                    "exported_road_layer_significant_top_face_nonpositive_normal_count"
                ]
            ),
            "exported_road_layer_microscopic_top_face_nonpositive_normal_count": int(
                road_acceptance[
                    "exported_road_layer_microscopic_top_face_nonpositive_normal_count"
                ]
            ),
            "exported_road_layer_plan_collapsed_top_face_count": int(
                road_acceptance[
                    "exported_road_layer_plan_collapsed_top_face_count"
                ]
            ),
            "exported_road_layer_plan_collapsed_top_face_3d_area_m2": float(
                road_acceptance[
                    "exported_road_layer_plan_collapsed_top_face_3d_area_m2"
                ]
            ),
            "exported_road_layer_zero_3d_area_face_count": int(
                road_acceptance["exported_road_layer_zero_3d_area_face_count"]
            ),
            "exported_road_layer_open_or_nonmanifold_edge_count": int(
                road_acceptance[
                    "exported_road_layer_open_or_nonmanifold_edge_count"
                ]
            ),
            "required_masterplan_features_present": len(missing) == 0,
            "new_physical_feature_building_overlap_m2": float(max((value.get("building_intersection_m2", 0.0) for value in checks.values()), default=0.0)),
            "new_physical_feature_unintended_road_overlap_m2": float(max((value.get("road_intersection_m2", 0.0) for value in checks.values()), default=0.0)),
            "new_feature_unapproved_pairwise_overlap_count": len(unapproved_pairwise),
            "protected_pedestrian_conflict_count": int(
                checks["protected_pedestrian_route"]["building_intersection_m2"] > 1.0e-6
                or checks["protected_pedestrian_route"]["preliminary_safety_zone_intersection_m2"] > 1.0e-6
                or checks["protected_pedestrian_route"]["crane_pad_intersection_m2"] > 1.0e-6
            ),
            "phase2_surface_road_overlap_m2": checks["phase2_capped_stubs"]["road_intersection_m2"],
            "snow_zone_road_overlap_m2": max(checks["clean_snow"]["road_intersection_m2"], checks["dirty_snow"]["road_intersection_m2"]),
            "emergency_bay_plan_component_count": bay_components,
            "emergency_bay_mesh_component_count": bay_mesh_components,
            "emergency_bay_shared_d3_seam_m": bay_d3_seam,
            "emergency_bay_gap_m": bay_d3_gap,
            "emergency_bay_maximum_vertical_step_m": bay_max_vertical_step,
            "emergency_bay_maximum_resultant_grade_pct": bay_resultant_grade,
            "emergency_bay_maximum_nominal_formation_fill_m": bay_max_fill_depth,
            "emergency_bay_maximum_nominal_formation_cut_m": bay_max_cut_depth,
            "emergency_bay_maximum_actual_unsupported_gap_m": bay_max_unsupported_gap,
            "emergency_bay_maximum_actual_foundation_cut_m": bay_max_actual_foundation_cut,
            "emergency_bay_minimum_residual_ground_key_in_m": bay_min_residual_ground_key_in,
            "emergency_bay_minimum_exact_tin_ground_key_in_m": float(
                bay_exact_tin_formation_qa["actual"]["minimum_ground_key_in_m"]
            ),
            "emergency_bay_maximum_exact_tin_foundation_cut_m": float(
                bay_exact_tin_formation_qa["actual"]["maximum_cut_below_ground_m"]
            ),
            "emergency_bay_foundation_method": "SINGLE_ENGINEERED_AFFINE_PLANE_VERIFIED_AGAINST_CLIPPED_REVP2_TIN",
            "emergency_bay_foundation_bottom_is_single_plane": True,
            "emergency_bay_foundation_bottom_plane_grade_pct": bay_foundation_bottom_plane_grade_pct,
            "emergency_bay_foundation_bottom_planarity_residual_m": bay_bottom_planarity_residual,
            "emergency_bay_top_affine_residual_m": top_affine_residual,
            "emergency_bay_exact_tin_triangle_count": int(
                bay_exact_tin_formation_qa["intersected_triangle_count"]
            ),
            "emergency_bay_exact_tin_extrema_vertex_count": int(
                bay_exact_tin_formation_qa["extrema_vertex_count"]
            ),
            "emergency_bay_exact_tin_coverage_delta_m2": float(
                bay_exact_tin_formation_qa["coverage_delta_m2"]
            ),
            "emergency_bay_outer_foundation_watertight": bool(
                bay_outer_base_quality["watertight"]
            ),
            "emergency_bay_outer_foundation_open_or_nonmanifold_edges": int(
                bay_outer_base_quality["open_or_nonmanifold_edges"]
            ),
            "emergency_bay_outer_foundation_connected_components": bay_outer_base_components,
            "emergency_bay_minimum_actual_foundation_thickness_m": bay_min_actual_foundation_thickness,
            "emergency_bay_maximum_actual_foundation_thickness_m": bay_max_actual_foundation_thickness,
            "emergency_bay_support_partition_pairwise_overlap_m2": bay_support_pairwise_overlap,
            "emergency_bay_support_partition_coverage_gap_m2": bay_support_coverage_gap,
            "emergency_bay_source_terrain_sha_verified": source_terrain_sha == roadmod.SOURCE_SHA256,
            "heavy_haul_unapproved_clearance_overlap_count": len(unexpected_haul_overlaps),
            "scene_metadata_status": "PASS",
            "bld05_ramp_grade_pct": float(100.0 * ramp_grade),
            "masterplan_status": "PASS_CONTROLLED_PRE_FEED",
        },
        "remaining_hold_points": [
            "Survey CRS/DTM and engineering surveys are pending.",
            "Vendor-frozen GA/PFD/P&ID/load data are pending.",
            "HAZID/HAZOP, final Ex/fire/F&G/ESD classification is pending.",
            "Certified AutoTURN or equivalent swept-path report is pending.",
            "The laboratory, wastewater, HVAC and DG/UPS objects are spatial reserves, not detailed systems.",
        ],
    }

    target.metadata["masterplan_change_count"] = len(register)
    target.metadata["masterplan_change_register"] = [row["Object_Name"] for row in register]

    OUT_GLB.write_bytes(target.export(file_type="glb"))
    target.export(OUT_OBJ)

    export_checks = {}
    for path in (OUT_GLB, OUT_OBJ):
        imported = trimesh.load(str(path), force="scene", process=False)
        if not isinstance(imported, trimesh.Scene):
            imported = trimesh.Scene(imported)
        vertices = [np.asarray(mesh.vertices, dtype=float) for mesh in imported.geometry.values() if len(mesh.vertices)]
        all_vertices = np.vstack(vertices) if vertices else np.empty((0, 3))
        if len(all_vertices) == 0 or not np.isfinite(all_vertices).all():
            raise RuntimeError(f"Invalid export {path.name}")
        export_checks[path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "geometry_count": len(imported.geometry),
            "bounds": np.asarray(imported.bounds, dtype=float).tolist(),
        }
        if path.suffix.lower() == ".glb":
            imported_metadata = dict(imported.metadata or {})
            expected_metadata = {
                "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
                "variant": "A.1/Rev.P5",
                "stage": "Integrated pre-FEED coordination model; not for construction",
                "model_status": "CONTROLLED_PRE_FEED_COORDINATION_NOT_FOR_CONSTRUCTION",
            }
            mismatches = {
                key: {"expected": value, "actual": imported_metadata.get(key)}
                for key, value in expected_metadata.items()
                if imported_metadata.get(key) != value
            }
            if mismatches:
                raise RuntimeError("Exported GLB metadata mismatch: " + json.dumps(mismatches, ensure_ascii=False))
            export_checks[path.name]["metadata_identity"] = expected_metadata
    qa["exports"] = export_checks

    OUT_QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_REGISTER_JSON.write_text(json.dumps(register, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_REGISTER_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Object_Name", "Category", "Data_Status", "Area_m2", "Bounds_XY", "Description", "Spatial_Role"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in register:
            csv_row = dict(row)
            csv_row["Bounds_XY"] = json.dumps(csv_row["Bounds_XY"], ensure_ascii=False)
            writer.writerow(csv_row)

    print("REV_P5_INTEGRATED_MASTERPLAN_PASS")


if __name__ == "__main__":
    main()
