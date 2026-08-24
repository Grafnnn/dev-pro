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
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

ROOT = Path("revp5_output")
ROAD_ROOT = Path("revp3_output")
ROOT.mkdir(parents=True, exist_ok=True)

ROAD_GLB = ROAD_ROOT / "20_Модель_A1_RevP3_RoadQA.glb"
ROAD_QA = ROAD_ROOT / "20_Road_QA_Report_RevP3.json"
OUT_GLB = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
OUT_OBJ = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.obj"
OUT_QA = ROOT / "26_Integrated_QA_Report_RevP5.json"
OUT_REGISTER_JSON = ROOT / "26_Masterplan_Change_Register_RevP5.json"
OUT_REGISTER_CSV = ROOT / "26_Masterplan_Change_Register_RevP5.csv"

sys.path.insert(0, str(Path("tools").resolve()))
import build_revp3_roadqa as roadmod  # noqa: E402

COLORS = {
    "assembly": (196, 157, 92, 255),
    "haul": (236, 126, 39, 255),
    "crane": (230, 178, 36, 255),
    "quarantine": (182, 73, 58, 230),
    "pedestrian": (48, 169, 196, 255),
    "emergency": (236, 85, 64, 255),
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
            candidates.append(mesh)
    if not candidates:
        raise RuntimeError("Finished design surface not found in road model")
    terrain = max(candidates, key=lambda item: len(item.vertices))
    vertices = np.asarray(terrain.vertices, dtype=float)
    tree = cKDTree(vertices[:, :2])

    def z_at(x: float, y: float) -> float:
        _, indexes = tree.query(np.array([x, y], dtype=float), k=min(8, len(vertices)))
        indexes = np.atleast_1d(indexes)
        return float(np.max(vertices[indexes, 2]))

    return z_at, np.asarray(terrain.bounds, dtype=float)


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
    if not ROAD_GLB.exists() or not ROAD_QA.exists():
        raise FileNotFoundError("Rev.P3 road build outputs are missing")
    road_qa = json.loads(ROAD_QA.read_text(encoding="utf-8"))
    if road_qa.get("acceptance", {}).get("status") != "PASS":
        raise RuntimeError("Road QA is not PASS; integration prohibited")

    source = trimesh.load(str(ROAD_GLB), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)

    target = trimesh.Scene()
    source_names = []
    for old_name, mesh in iter_world_geometry(source):
        new_name = old_name.replace("REV_P3_", "REV_P5_")
        add_mesh(target, new_name, mesh)
        source_names.append(new_name)

    target.metadata = dict(source.metadata or {})
    target.metadata.update({
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "model_status": "CONTROLLED_PRE_FEED_COORDINATION_NOT_FOR_CONSTRUCTION",
        "base_masterplan": "A.1",
        "road_source": "A.1/Rev.P3 RoadQA generated inside Rev.P5 workflow",
        "technological_source": "A.1/Rev.P2 exterior based on LOD400-P/RFI",
        "coordinate_system": "Local project coordinates; survey CRS pending HP-01",
        "date_cut": "2026-08-25",
    })

    z_at, terrain_bounds = build_terrain_sampler(target)
    paths = roadmod.build_paths()
    profiles = {code: roadmod.RoadProfile(code=code, width=roadmod.WIDTHS[code], paths=road_paths) for code, road_paths in paths.items()}
    road_polys = {code: profile.polygon(roadmod.WIDTHS[code]) for code, profile in profiles.items()}
    road_union = unary_union(list(road_polys.values())).buffer(0)

    foundations = {}
    walls = {}
    for name, mesh in target.geometry.items():
        base_name = name.replace("REV_P5_", "")
        if re.match(r"BLD_.*_FOUNDATION(?:_DECK)?$", base_name, re.I):
            foundations[base_name] = polygon_from_mesh_xy(mesh)
        elif re.match(r"BLD_.*_(?:WALL_PANELS|SHELL)$", base_name, re.I):
            walls[base_name] = polygon_from_mesh_xy(mesh)
    building_union = unary_union(list(foundations.values()) + list(walls.values())).buffer(0)

    register = []
    checks = {}
    new_mesh_names = []

    def register_feature(name: str, category: str, status: str, poly: Polygon | None, note: str, mesh: trimesh.Trimesh, metadata: dict | None = None):
        add_mesh(target, name, mesh, metadata)
        new_mesh_names.append(name)
        row = {
            "Object_Name": name,
            "Category": category,
            "Data_Status": status,
            "Area_m2": float(poly.area) if poly is not None else None,
            "Bounds_XY": list(poly.bounds) if poly is not None else None,
            "Description": note,
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
    # controlled route overlay along the accepted D4/D6/D3 alignment.
    spur_points = [(177.0, 105.0), (153.0, 118.0), (145.0, 155.0), (145.0, 215.0), (130.0, 220.0)]
    spur = route_ribbon(spur_points, lambda x, y: z_at(x, y) + 0.18, 0.85, COLORS["haul"], 0.055)
    haul_parts = [spur]
    for code in ("D4", "D6"):
        for path in profiles[code].paths:
            for a, b in zip(path[:-1], path[1:]):
                haul_parts.append(segment_box((a[0], a[1], profiles[code].surface_z(a[0], a[1]) + 0.08),
                                              (b[0], b[1], profiles[code].surface_z(b[0], b[1]) + 0.08),
                                              0.55, 0.04, COLORS["haul"]))
    d3_path = max(profiles["D3"].paths, key=len)
    for a, b in zip(d3_path[:-1], d3_path[1:]):
        if min(a[1], b[1]) < 205.0:
            continue
        haul_parts.append(segment_box((a[0], a[1], profiles["D3"].surface_z(a[0], a[1]) + 0.08),
                                      (b[0], b[1], profiles["D3"].surface_z(b[0], b[1]) + 0.08),
                                      0.55, 0.04, COLORS["haul"]))
    register_feature(
        "REV_P5_MP_HEAVY_HAUL_ROUTE", "Construction logistics", "CONTROLLED_PRE_FEED", None,
        "Heavy-haul route annotation for a 16.5 m articulated vehicle; final certified swept path remains HP-07.",
        trimesh.util.concatenate(haul_parts), {"Vehicle": "16.5 m screening vehicle", "Gate": "HP-07"},
    )

    # 3. Crane setup positions around the pyrolysis building.
    crane_polys = [box(326.0, 207.0, 344.0, 221.0), box(429.0, 227.0, 447.0, 241.0)]
    for index, poly in enumerate(crane_polys, start=1):
        checks[f"crane_{index}"] = physical_feature_check(f"crane_{index}", poly, building_union, road_union)
        top = top_for_polygon(poly, z_at, 0.25)
        register_feature(
            f"REV_P5_MP_CRANE_PAD_{index:02d}", "Construction logistics", "CONTROLLED_PRE_FEED", poly,
            "Temporary crane outrigger platform adjacent to the pyrolysis terrace.",
            flat_solid(poly, top, 0.30, COLORS["crane"]),
            {"Phase": "Construction", "Data_Status": "CONTROLLED_PRE_FEED", "Gate": "HP-07"},
        )

    # 4. D3 emergency lay-by connected without overlapping the primary road.
    bay_rect = box(550.5, 235.0, 566.5, 248.0)
    bay_target = nearest_points(bay_rect, road_polys["D3"].boundary)[1]
    bay_anchor = nearest_points(bay_rect.boundary, bay_target)[0]
    bay_connector = LineString([(bay_anchor.x, bay_anchor.y), (bay_target.x, bay_target.y)]).buffer(3.0, cap_style=2)
    bay_poly = unary_union([bay_rect, bay_connector]).difference(road_polys["D3"]).difference(building_union).buffer(0)
    checks["emergency_bay"] = physical_feature_check("emergency_bay", bay_poly, building_union, road_union)
    bay_z = profiles["D3"].surface_z(bay_target.x, bay_target.y) + 0.02
    register_feature(
        "REV_P5_MP_D3_EMERGENCY_BAY", "Road safety", "CONTROLLED_PRE_FEED", bay_poly,
        "Emergency lay-by on the eastern service serpentine, with a common non-overlapping seam to D3.",
        roadmod.solid_from_polygon(bay_poly, lambda x, y: bay_z, 0.28, COLORS["emergency"], 2.5),
        {"Road": "D3", "Use": "Emergency stop / passing bay"},
    )

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

    # 6. Protected pedestrian route. Road crossings are intentional and lifted
    # above the carriageway to avoid coplanar z-fighting.
    ped_points = [(177.0, 92.0), (250.0, 92.0), (315.0, 92.0), (325.0, 135.0), (325.0, 195.0), (338.0, 202.0), (338.0, 252.0), (352.0, 260.0)]
    def ped_z(x: float, y: float) -> float:
        point = Point(x, y)
        candidates = []
        for code, poly in road_polys.items():
            if poly.buffer(0.05).contains(point):
                candidates.append(profiles[code].surface_z(x, y) + 0.09)
        return float(max(candidates) if candidates else z_at(x, y) + 0.18)
    ped_mesh = route_ribbon(ped_points, ped_z, 2.5, COLORS["pedestrian"], 0.06)
    register_feature(
        "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE", "Personnel safety", "CONTROLLED_PRE_FEED", None,
        "Protected pedestrian corridor from lower checkpoint/ABK toward production buildings; crossings are explicit elevated marking zones.",
        ped_mesh, {"Width": "2.5 m", "Gate": "Rev.P5 Integrated"},
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

    # 8. Clean and dirty snow areas: keep source zones and add visible berms.
    snow_found = {}
    for source_name in ("clean_snow", "dirty_snow"):
        matches = [(name, mesh) for name, mesh in target.geometry.items() if name.lower() == source_name]
        if not matches:
            raise RuntimeError(f"Source snow zone {source_name} not found")
        mesh = matches[0][1]
        b = np.asarray(mesh.bounds, dtype=float)
        poly = box(b[0, 0], b[0, 1], b[1, 0], b[1, 1])
        z = float(b[1, 2] + 0.05)
        snow_found[source_name] = list(poly.bounds)
        name = "REV_P5_MP_CLEAN_SNOW_CONTAINMENT" if source_name == "clean_snow" else "REV_P5_MP_DIRTY_SNOW_CONTAINMENT"
        color = COLORS["snow_clean"] if source_name == "clean_snow" else COLORS["snow_dirty"]
        register_feature(name, "Winter operation", "CONTROLLED_PRE_FEED", poly,
                         "Raised containment/identification boundary for separated snow management.",
                         perimeter_boxes(poly, z, color, 0.55, 0.18),
                         {"Snow_Class": "Clean" if source_name == "clean_snow" else "Contaminated"})

    # 9. Physical capped phase-2 utility stubs at the western boundary of the
    # future 1.595 ha expansion reserve.
    stub_parts = []
    stub_specs = [
        ("FW", 460.0, 337.0, 0.30, COLORS["stub_fw"]),
        ("CW-S", 460.0, 342.0, 0.24, COLORS["stub_cw"]),
        ("CW-R", 460.0, 347.0, 0.24, COLORS["stub_cw"]),
        ("PG", 460.0, 352.0, 0.20, COLORS["stub_pg"]),
    ]
    for system, x, y, radius, color in stub_specs:
        base_z = z_at(x, y) + 0.15
        pipe = trimesh.creation.cylinder(radius=radius, height=2.2, sections=20)
        pipe.apply_translation([x, y, base_z + 1.1])
        color_mesh(pipe, color)
        stub_parts.append(pipe)
        cap = trimesh.creation.cylinder(radius=radius * 1.35, height=0.15, sections=20)
        cap.apply_translation([x, y, base_z + 2.25])
        color_mesh(cap, color)
        stub_parts.append(cap)
    for system, x, y, color in (("10KV", 464.0, 357.0, COLORS["stub_power"]), ("CONTROL", 464.0, 362.0, COLORS["stub_control"])):
        z = z_at(x, y) + 0.75
        marker = trimesh.creation.box(extents=(1.2, 1.2, 1.5))
        marker.apply_translation([x, y, z])
        color_mesh(marker, color)
        stub_parts.append(marker)
    register_feature(
        "REV_P5_MP_PHASE2_CAPPED_STUBS", "Phase 2 interfaces", "CONTROLLED_PRE_FEED", None,
        "Visible capped reserves for FW, CW supply/return, pyrolysis gas, 10 kV and control at the phase-2 boundary.",
        trimesh.util.concatenate(stub_parts),
        {"Phase": "2", "Capacity_Increment": "+10,000 t/y", "Reserve_Area": "1.595 ha"},
    )

    # 10. One-way circulation arrows on raw and product loops.
    for code, object_name in (("D2", "REV_P5_MP_RAW_LOOP_ONE_WAY_MARKINGS"), ("D5", "REV_P5_MP_PRODUCT_LOOP_ONE_WAY_MARKINGS")):
        path = max(profiles[code].paths, key=lambda p: roadmod.cumulative_xy(p)[-1])
        stations = roadmod.cumulative_xy(path)
        arrow_parts = []
        for fraction in (0.18, 0.38, 0.58, 0.78):
            target_station = stations[-1] * fraction
            index = int(np.argmin(np.abs(stations - target_station)))
            x, y = path[index, :2]
            z = profiles[code].surface_z(x, y) + 0.045
            arrow_parts.append(arrow_mesh(float(x), float(y), float(z), profile_tangent(path, index), COLORS["arrow"]))
        register_feature(object_name, "Traffic management", "CONTROLLED_PRE_FEED", None,
                         f"One-way circulation markings derived from the accepted {code} axis.",
                         trimesh.util.concatenate(arrow_parts), {"Road": code, "Direction": "Along model axis"})

    # 11. Dedicated BLD_05 high-level service ramp to D3. It is deliberately
    # not connected to the lower D5 product loop.
    deck_mesh = target.geometry.get("BLD_05_FOUNDATION_DECK")
    if deck_mesh is None:
        raise RuntimeError("BLD_05_FOUNDATION_DECK not found")
    deck_poly = polygon_from_mesh_xy(deck_mesh)
    deck_top = float(deck_mesh.bounds[1, 2]) + 0.01
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
        ("REV_P5_MP_LABORATORY_RESERVE", box(310.0, 76.0, 322.0, 84.0), COLORS["laboratory"], "Quality laboratory reserve for feedstock, oil and rCB testing."),
        ("REV_P5_MP_WASTEWATER_TREATMENT_RESERVE", box(500.0, 25.0, 540.0, 45.0), COLORS["los"], "Reserve for local treatment of process, storm and oily wastewater."),
        ("REV_P5_MP_DG_UPS_RESERVE", box(395.0, 70.0, 415.0, 85.0), COLORS["dgups"], "Reserve for emergency generator and UPS supporting safety loads."),
        ("REV_P5_MP_HVAC_HEAT_SOURCE_RESERVE", box(330.0, 70.0, 348.0, 86.0), COLORS["hvac"], "Reserve for heat source, HVAC and emergency ventilation equipment."),
    ]
    for name, poly, color, note in reserve_specs:
        checks[name] = physical_feature_check(name, poly, building_union, road_union)
        z = top_for_polygon(poly, z_at, 0.20)
        register_feature(name, "Missing system spatial reserve", "OPEN_CRITICAL", poly, note,
                         flat_solid(poly, z, 0.18, color), {"Data_Status": "OPEN_CRITICAL", "Gate": "FG-06/FG-07"})

    # 13. Preliminary process-safety envelope around the pyrolysis building.
    safety_poly = deck_poly.buffer(12.0, join_style=2).difference(deck_poly).buffer(0)
    safety_z = deck_top + 0.08
    register_feature(
        "REV_P5_SAFETY_PRELIM_PYROLYSIS_ZONE", "Safety annotation", "OPEN_CRITICAL", safety_poly,
        "Preliminary spatial envelope for Ex/fire/F&G coordination. It is not a final hazardous-area classification.",
        roadmod.solid_from_polygon(safety_poly, lambda x, y: safety_z, 0.05, COLORS["safety"], 4.0),
        {"Data_Status": "OPEN_CRITICAL", "Disclaimer": "Not final Ex classification"},
    )

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
        "road_acceptance_reused": road_qa.get("acceptance", {}),
        "masterplan_changes": register,
        "required_features": REQUIRED_FEATURES,
        "missing_required_features": missing,
        "physical_feature_checks": checks,
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
            "open_external_critical_clashes": int(road_qa["acceptance"].get("open_external_critical_clashes", -1)),
            "terrain_above_road_points": int(road_qa["acceptance"].get("terrain_above_road_points", -1)),
            "non_adjacent_road_triangle_self_intersections": int(road_qa["acceptance"].get("non_adjacent_road_triangle_self_intersections", -1)),
            "duplicated_top_faces": int(road_qa["acceptance"].get("duplicated_top_faces", -1)),
            "non_manifold_edges": int(road_qa["acceptance"].get("non_manifold_edges", -1)),
            "required_masterplan_features_present": len(missing) == 0,
            "new_physical_feature_building_overlap_m2": float(max((value.get("building_intersection_m2", 0.0) for value in checks.values()), default=0.0)),
            "new_physical_feature_unintended_road_overlap_m2": float(max((value.get("road_intersection_m2", 0.0) for value in checks.values()), default=0.0)),
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
    qa["exports"] = export_checks

    OUT_QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_REGISTER_JSON.write_text(json.dumps(register, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_REGISTER_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Object_Name", "Category", "Data_Status", "Area_m2", "Bounds_XY", "Description"])
        writer.writeheader()
        for row in register:
            csv_row = dict(row)
            csv_row["Bounds_XY"] = json.dumps(csv_row["Bounds_XY"], ensure_ascii=False)
            writer.writerow(csv_row)

    print("REV_P5_INTEGRATED_MASTERPLAN_PASS")


if __name__ == "__main__":
    main()
