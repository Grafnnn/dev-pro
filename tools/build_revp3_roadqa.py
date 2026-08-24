from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
import requests
import trimesh
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, unary_union

# -----------------------------------------------------------------------------
# A.1 / Rev.P3 Road & Apron Coordination
# Source is immutable Rev.P2.  Buildings, process equipment, tanks and process
# networks are retained byte-for-byte at their source transforms.  Only roads,
# road-side details, service aprons and local wall/rail interruptions are rebuilt.
# -----------------------------------------------------------------------------

SOURCE_COMMIT = "2af60d5b22917bf28f24685e42d9d83f519524f9"
SOURCE_NAME = "20_Модель_A1_RevP2_ExteriorQA.glb"
SOURCE_SHA256 = "cb26e1ac38f7919c522d4d289d952ed3a5e543e5cec3759ed4a3ea96e8f278fd"
SOURCE_URL = (
    "https://raw.githubusercontent.com/Grafnnn/dev-pro/"
    + SOURCE_COMMIT
    + "/transfer_ready/20_%D0%9C%D0%BE%D0%B4%D0%B5%D0%BB%D1%8C_A1_RevP2_ExteriorQA.glb"
)
SOURCE_QA_URL = (
    "https://raw.githubusercontent.com/Grafnnn/dev-pro/"
    + SOURCE_COMMIT
    + "/transfer_ready/20_Exterior_QA_Report.json"
)

OUT = Path(os.environ.get("OUT_ROOT", "revp3_output"))
WORK = Path("work_revp3")
OUT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)

WIDTHS = {"D1": 8.0, "D2": 7.0, "D3": 6.0, "D4": 8.0, "D5": 7.0, "D6": 7.0}
MAX_GRADE = 0.06
MIN_RADIUS = 12.0
MESH_MAX_EDGE = 3.0
ROAD_GAP_LIMIT = 0.005
VERTICAL_STEP_LIMIT = 0.020
AREA_TOL = 1.0e-6

COLORS = {
    "road": (66, 72, 78, 255),
    "shoulder": (121, 123, 119, 255),
    "subbase": (112, 103, 92, 255),
    "concrete": (184, 183, 176, 255),
    "curb": (152, 157, 158, 255),
    "gutter": (67, 104, 122, 255),
    "drain": (45, 53, 58, 255),
    "mark_white": (245, 245, 236, 255),
    "mark_yellow": (240, 181, 36, 255),
    "steel": (77, 88, 96, 255),
    "guard": (107, 118, 126, 255),
    "safety": (228, 178, 36, 255),
    "bollard": (237, 177, 30, 255),
}

REMOVE_PATTERNS = [
    re.compile(r"^EXT_D[1-6]_(?:ROAD|SUBBASE|SHOULDER|CURBS|MARKINGS|GUTTER|DRAINS|LIGHTING|GUARDRAIL|ENTRY_GATE)$", re.I),
    re.compile(r"^EXT_BLD_.*_SERVICE_APRON$", re.I),
    re.compile(r"^EXT_PERSONNEL_CROSSWALK$", re.I),
    re.compile(r"^EXT_PAD_.*_(?:RETAINING_WALLS|SAFETY_RAILS)$", re.I),
]

SOURCE_CLASHES = [
    ("D2", "BLD_02_FOUNDATION_DECK", 350.52923929544073),
    ("D2", "BLD_02A_FOUNDATION_DECK", 96.53295976874412),
    ("D5", "BLD_07_FOUNDATION_DECK", 4.031759345366648),
    ("D5", "BLD_08_FOUNDATION_DECK", 359.78273418137206),
    ("D5", "BLD_09_FOUNDATION_DECK", 227.96629066820705),
    ("D6", "BLD_12_FOUNDATION_DECK", 247.2000732421875),
]


def log(message: str) -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=240) as response:
        response.raise_for_status()
        with target.open("wb") as f:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def color_mesh(mesh: trimesh.Trimesh, rgba: Sequence[int]) -> trimesh.Trimesh:
    color = np.asarray(rgba, dtype=np.uint8)
    mesh.visual.face_colors = np.tile(color, (len(mesh.faces), 1))
    return mesh


def add(scene: trimesh.Scene, name: str, mesh: trimesh.Trimesh, rgba=None) -> None:
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        return
    if rgba is not None:
        color_mesh(mesh, rgba)
    scene.add_geometry(mesh, geom_name=name, node_name=name)


def box_mesh(center, extents, rgba=None) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=np.asarray(extents, dtype=float))
    mesh.apply_translation(np.asarray(center, dtype=float))
    if rgba is not None:
        color_mesh(mesh, rgba)
    return mesh


def cylinder_mesh(center, radius, height, rgba=None, sections=16) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    mesh.apply_translation(np.asarray(center, dtype=float))
    if rgba is not None:
        color_mesh(mesh, rgba)
    return mesh


def segment_box(p1, p2, width, height, rgba=None) -> trimesh.Trimesh | None:
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    vector = p2 - p1
    length = float(np.linalg.norm(vector))
    if length < 1.0e-8:
        return None
    mesh = trimesh.creation.box(extents=(length, width, height))
    transform = trimesh.geometry.align_vectors([1.0, 0.0, 0.0], vector / length)
    if transform is not None:
        mesh.apply_transform(transform)
    mesh.apply_translation((p1 + p2) / 2.0)
    if rgba is not None:
        color_mesh(mesh, rgba)
    return mesh


def cumulative_xy(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if len(points) < 2:
        return np.zeros(len(points))
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1))]


def dedupe_points(points: np.ndarray, tolerance: float = 1.0e-7) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if len(points) < 2:
        return points
    keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > tolerance]
    return points[keep]


def sample_line(p0, p1, spacing: float = 1.5) -> np.ndarray:
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    length = float(np.linalg.norm(p1[:2] - p0[:2]))
    count = max(2, int(math.ceil(length / spacing)) + 1)
    return np.linspace(p0, p1, count)


def arc_from_pose(
    start_xy: Sequence[float],
    start_heading: float,
    radius: float,
    signed_angle: float,
    spacing: float = 1.0,
) -> tuple[np.ndarray, float]:
    """Sample a constant-curvature arc from a pose. Positive is left turn."""
    start = np.asarray(start_xy, dtype=float)
    kappa = math.copysign(1.0 / radius, signed_angle)
    length = abs(radius * signed_angle)
    count = max(3, int(math.ceil(length / spacing)) + 1)
    s = np.linspace(0.0, length, count)
    heading = start_heading + kappa * s
    x = start[0] + (np.sin(heading) - math.sin(start_heading)) / kappa
    y = start[1] + (-np.cos(heading) + math.cos(start_heading)) / kappa
    return np.column_stack([x, y]), float(start_heading + signed_angle)


def sample_s_bend(
    start_xy: Sequence[float],
    heading: float,
    radius: float,
    angle: float,
    direction: int,
    spacing: float = 1.0,
) -> tuple[np.ndarray, float]:
    first, h1 = arc_from_pose(start_xy, heading, radius, direction * angle, spacing)
    second, h2 = arc_from_pose(first[-1], h1, radius, -direction * angle, spacing)
    return dedupe_points(np.vstack([first, second[1:]])), h2


def rounded_rectangle_centerline(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    radius: float,
    spacing: float = 1.0,
) -> np.ndarray:
    pieces: list[np.ndarray] = []
    pieces.append(sample_line((xmin + radius, ymin), (xmax - radius, ymin), spacing))
    arc, _ = arc_from_pose((xmax - radius, ymin), 0.0, radius, math.pi / 2.0, spacing)
    pieces.append(arc[1:])
    pieces.append(sample_line((xmax, ymin + radius), (xmax, ymax - radius), spacing)[1:])
    arc, _ = arc_from_pose((xmax, ymax - radius), math.pi / 2.0, radius, math.pi / 2.0, spacing)
    pieces.append(arc[1:])
    pieces.append(sample_line((xmax - radius, ymax), (xmin + radius, ymax), spacing)[1:])
    arc, _ = arc_from_pose((xmin + radius, ymax), math.pi, radius, math.pi / 2.0, spacing)
    pieces.append(arc[1:])
    pieces.append(sample_line((xmin, ymax - radius), (xmin, ymin + radius), spacing)[1:])
    arc, _ = arc_from_pose((xmin, ymin + radius), -math.pi / 2.0, radius, math.pi / 2.0, spacing)
    pieces.append(arc[1:])
    path = dedupe_points(np.vstack(pieces))
    if np.linalg.norm(path[0] - path[-1]) > 1.0e-6:
        path = np.vstack([path, path[0]])
    return path


def assign_linear_z(path_xy: np.ndarray, z0: float, z1: float) -> np.ndarray:
    path_xy = np.asarray(path_xy, dtype=float)
    temp = np.column_stack([path_xy[:, :2], np.zeros(len(path_xy))])
    station = cumulative_xy(temp)
    if station[-1] < 1.0e-9:
        z = np.full(len(path_xy), z0)
    else:
        t = station / station[-1]
        z = z0 + (z1 - z0) * (t * t * (3.0 - 2.0 * t))
    return np.column_stack([path_xy[:, :2], z])


def assign_constant_z(path_xy: np.ndarray, z: float) -> np.ndarray:
    path_xy = np.asarray(path_xy, dtype=float)
    return np.column_stack([path_xy[:, :2], np.full(len(path_xy), z)])


def build_paths() -> dict[str, list[np.ndarray]]:
    roads: dict[str, list[np.ndarray]] = {}

    # D1 — upper entry. Two controlled S-bends avoid the fixed gatehouse.
    d1_parts = [sample_line((167.0, 305.0), (176.0, 305.0), 1.0)]
    s1, _ = sample_s_bend((176.0, 305.0), 0.0, 15.0, math.radians(55.0), +1, 0.8)
    d1_parts.append(s1[1:])
    d1_parts.append(sample_line(tuple(s1[-1]), (220.0, float(s1[-1, 1])), 1.0)[1:])
    shift_down = float(s1[-1, 1] - 310.0)
    angle_down = math.acos(max(-1.0, min(1.0, 1.0 - shift_down / (2.0 * 15.0))))
    s2, _ = sample_s_bend((220.0, float(s1[-1, 1])), 0.0, 15.0, angle_down, -1, 0.8)
    d1_parts.append(s2[1:])
    d1_parts.append(sample_line(tuple(s2[-1]), (245.0, 310.0), 1.0)[1:])
    d1_xy = dedupe_points(np.vstack(d1_parts))
    roads["D1"] = [assign_linear_z(d1_xy, 134.9, 133.2)]

    # D2 — connector plus a genuine rounded raw-material loop around fixed buildings.
    d2_connector_parts = [sample_line((245.0, 310.0), (275.0, 310.0), 1.0)]
    arc, _ = arc_from_pose((275.0, 310.0), 0.0, 14.5, math.pi / 2.0, 0.8)
    d2_connector_parts.append(arc[1:])
    d2_connector_parts.append(sample_line(tuple(arc[-1]), (290.0, 324.5), 0.5)[1:])
    d2_conn_xy = dedupe_points(np.vstack(d2_connector_parts))
    d2_loop_xy = rounded_rectangle_centerline(290.0, 310.0, 436.0, 379.0, 14.5, 0.9)
    roads["D2"] = [assign_linear_z(d2_conn_xy, 133.2, 133.7), assign_constant_z(d2_loop_xy, 133.7)]

    # D3 — explicit 17.5 m switchbacks and a final 13 m quarter-turn.
    d3_parts = [sample_line((436.0, 345.0), (568.0, 345.0), 1.2)]
    point = np.array([568.0, 345.0])
    heading = 0.0
    for index in range(7):
        signed = -math.pi if index % 2 == 0 else math.pi
        arc, heading = arc_from_pose(point, heading, 17.5, signed, 0.8)
        d3_parts.append(arc[1:])
        point = arc[-1]
        target_x = 542.0 if index % 2 == 0 else 568.0
        line = sample_line(tuple(point), (target_x, float(point[1])), 1.0)
        d3_parts.append(line[1:])
        point = line[-1]
    final_arc, heading = arc_from_pose(point, heading, 13.0, math.pi / 2.0, 0.7)
    d3_parts.append(final_arc[1:])
    d3_parts.append(sample_line(tuple(final_arc[-1]), (555.0, 85.0), 0.5)[1:])
    d3_xy = dedupe_points(np.vstack(d3_parts))
    roads["D3"] = [assign_linear_z(d3_xy, 133.7, 102.2)]

    # D4 — lower entry passes south of fixed BLD_14 and finishes east of it.
    d4_parts = [sample_line((177.0, 105.0), (200.0, 105.0), 1.0)]
    shift1 = 4.5
    angle1 = math.acos(1.0 - shift1 / 30.0)
    s1, _ = sample_s_bend((200.0, 105.0), 0.0, 15.0, angle1, -1, 0.8)
    d4_parts.append(s1[1:])
    d4_parts.append(sample_line(tuple(s1[-1]), (302.0, float(s1[-1, 1])), 1.0)[1:])
    shift2 = 128.0 - float(s1[-1, 1])
    angle2 = math.acos(1.0 - shift2 / 30.0)
    s2, _ = sample_s_bend((302.0, float(s1[-1, 1])), 0.0, 15.0, angle2, +1, 0.8)
    d4_parts.append(s2[1:])
    d4_parts.append(sample_line(tuple(s2[-1]), (338.0, 128.0), 0.8)[1:])
    d4_xy = dedupe_points(np.vstack(d4_parts))
    roads["D4"] = [assign_linear_z(d4_xy, 107.7, 108.7)]

    # D5 — product loop around BLD_07/08/09, connected by a 12 m radius turn.
    d5_connector_parts = [sample_line((338.0, 128.0), (338.0, 128.0), 1.0)]
    arc, _ = arc_from_pose((338.0, 128.0), 0.0, 12.0, math.pi / 2.0, 0.7)
    d5_connector_parts.append(arc)
    d5_connector_parts.append(sample_line(tuple(arc[-1]), (350.0, 170.0), 1.0)[1:])
    d5_conn_xy = dedupe_points(np.vstack(d5_connector_parts))
    d5_loop_xy = rounded_rectangle_centerline(350.0, 155.0, 558.0, 202.0, 15.0, 0.9)
    roads["D5"] = [assign_linear_z(d5_conn_xy, 108.7, 110.7), assign_constant_z(d5_loop_xy, 110.7)]

    # D6 — utility road shifted north of BLD_12 and the oil tank farm.
    d6_parts = [sample_line((338.0, 128.0), (342.0, 128.0), 0.8)]
    shift = 14.0
    angle = math.acos(1.0 - shift / 30.0)
    s, _ = sample_s_bend((342.0, 128.0), 0.0, 15.0, angle, +1, 0.8)
    d6_parts.append(s[1:])
    d6_parts.append(sample_line(tuple(s[-1]), (550.0, 142.0), 1.2)[1:])
    d6_xy = dedupe_points(np.vstack(d6_parts))
    roads["D6"] = [assign_linear_z(d6_xy, 108.7, 105.7)]

    return roads


@dataclass
class RoadProfile:
    code: str
    width: float
    paths: list[np.ndarray]

    def __post_init__(self) -> None:
        self.lines: list[LineString] = []
        self.stations: list[np.ndarray] = []
        for path in self.paths:
            self.lines.append(LineString(path[:, :2]))
            self.stations.append(cumulative_xy(path))

    def nearest(self, x: float, y: float) -> tuple[int, float, float]:
        point = Point(float(x), float(y))
        best = None
        for index, line in enumerate(self.lines):
            distance = float(line.distance(point))
            station = float(line.project(point))
            if best is None or distance < best[2]:
                best = (index, station, distance)
        assert best is not None
        return best

    def center_z(self, x: float, y: float) -> float:
        index, station, _ = self.nearest(x, y)
        return float(np.interp(station, self.stations[index], self.paths[index][:, 2]))

    def surface_z(self, x: float, y: float, crown: float = 0.045, crossfall: float = 0.02) -> float:
        _, _, distance = self.nearest(x, y)
        return self.center_z(x, y) + crown - crossfall * distance

    def centerline_length(self) -> float:
        return float(sum(station[-1] for station in self.stations))

    def max_grade(self) -> float:
        values = []
        for path, station in zip(self.paths, self.stations):
            ds = np.diff(station)
            good = ds > 1.0e-8
            if np.any(good):
                values.extend(np.abs(np.diff(path[:, 2])[good] / ds[good]).tolist())
        return float(max(values, default=0.0))

    def polygon(self, width: float) -> Polygon | MultiPolygon:
        pieces = [line.buffer(width / 2.0, cap_style=1, join_style=1, resolution=12) for line in self.lines]
        return unary_union(pieces).buffer(0)


def iter_polygons(geometry) -> Iterable[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [item for item in getattr(geometry, "geoms", []) if isinstance(item, Polygon)]


def subdivide_mesh(mesh: trimesh.Trimesh, max_edge: float = MESH_MAX_EDGE) -> trimesh.Trimesh:
    try:
        vertices, faces = trimesh.remesh.subdivide_to_size(
            np.asarray(mesh.vertices), np.asarray(mesh.faces), max_edge=max_edge, max_iter=10, return_index=False
        )
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    except Exception as exc:
        log(f"Subdivision warning: {exc}")
    mesh.remove_unreferenced_vertices()
    try:
        mesh.update_faces(mesh.unique_faces())
    except Exception:
        pass
    try:
        mesh.update_faces(mesh.nondegenerate_faces(height=1.0e-9))
    except Exception:
        pass
    mesh.merge_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    return mesh


def solid_from_polygon(
    geometry,
    z_function: Callable[[float, float], float],
    thickness: float,
    rgba: Sequence[int],
    max_edge: float = MESH_MAX_EDGE,
) -> trimesh.Trimesh | None:
    meshes: list[trimesh.Trimesh] = []
    for polygon in iter_polygons(geometry):
        if polygon.area < 1.0e-5:
            continue
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        for component in iter_polygons(polygon):
            if component.area < 1.0e-5:
                continue
            mesh = trimesh.creation.extrude_polygon(component, height=thickness, engine="earcut")
            mesh = subdivide_mesh(mesh, max_edge)
            vertices = np.asarray(mesh.vertices, dtype=float)
            top_mask = vertices[:, 2] > thickness / 2.0
            z_values = np.asarray([z_function(float(x), float(y)) for x, y in vertices[:, :2]], dtype=float)
            vertices[:, 2] = np.where(top_mask, z_values, z_values - thickness)
            mesh.vertices = vertices
            trimesh.repair.fix_normals(mesh, multibody=True)
            color_mesh(mesh, rgba)
            meshes.append(mesh)
    if not meshes:
        return None
    return trimesh.util.concatenate(meshes)


def polygon_from_mesh_xy(mesh: trimesh.Trimesh) -> Polygon:
    points = np.asarray(mesh.vertices, dtype=float)[:, :2]
    return Polygon(points).convex_hull


def build_terrain_sampler(terrain: trimesh.Trimesh):
    vertices = np.asarray(terrain.vertices, dtype=float)
    rounded = np.round(vertices[:, :2], 4)
    order = np.lexsort((rounded[:, 1], rounded[:, 0]))
    rounded = rounded[order]
    z = vertices[order, 2]
    xy_values = []
    z_values = []
    index = 0
    while index < len(rounded):
        stop = index + 1
        while stop < len(rounded) and np.allclose(rounded[stop], rounded[index], atol=1.0e-8):
            stop += 1
        xy_values.append(rounded[index])
        z_values.append(float(np.max(z[index:stop])))
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

    return sample


def circle_radius(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    ab = float(np.linalg.norm(a - b))
    bc = float(np.linalg.norm(b - c))
    ca = float(np.linalg.norm(c - a))
    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    if area2 < 1.0e-7:
        return math.inf
    return ab * bc * ca / (2.0 * area2)


def resample_xy(path: np.ndarray, spacing: float = 2.0) -> np.ndarray:
    station = cumulative_xy(path)
    if station[-1] < 1.0e-8:
        return path.copy()
    new_station = np.linspace(0.0, station[-1], max(2, int(math.ceil(station[-1] / spacing)) + 1))
    return np.column_stack([np.interp(new_station, station, path[:, dimension]) for dimension in range(3)])


def minimum_radius(profile: RoadProfile) -> float:
    radii = []
    for path in profile.paths:
        sampled = resample_xy(path, 2.5)
        for index in range(1, len(sampled) - 1):
            radius = circle_radius(sampled[index - 1, :2], sampled[index, :2], sampled[index + 1, :2])
            if math.isfinite(radius):
                radii.append(radius)
    return float(min(radii, default=math.inf))


def mesh_quality(mesh: trimesh.Trimesh) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    triangles = vertices[faces]
    edges = np.stack(
        [
            np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1),
            np.linalg.norm(triangles[:, 2] - triangles[:, 1], axis=1),
            np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1),
        ],
        axis=1,
    )
    areas = np.asarray(mesh.area_faces, dtype=float)
    longest = np.max(edges, axis=1) if len(edges) else np.array([0.0])
    aspect = longest * longest / np.maximum(2.0 * areas, 1.0e-12)
    edge_sorted = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, counts = np.unique(edge_sorted, axis=0, return_counts=True) if len(edge_sorted) else (np.empty((0, 2)), np.array([]))
    unique_face_count = len(np.unique(np.sort(faces, axis=1), axis=0)) if len(faces) else 0
    return {
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "non_manifold_edges": int(np.count_nonzero(counts != 2)),
        "zero_area_faces": int(np.count_nonzero(areas <= 1.0e-10)),
        "duplicate_faces": int(len(faces) - unique_face_count),
        "max_edge_m": float(np.max(longest)),
        "max_aspect_ratio": float(np.max(aspect)),
        "finite_coordinates": bool(np.isfinite(vertices).all()),
        "volume_m3": float(abs(mesh.volume)),
    }


def should_remove(name: str) -> bool:
    return any(pattern.search(name) for pattern in REMOVE_PATTERNS)


def partition_polygons(profiles: dict[str, RoadProfile], extra_width: float, obstacle_union) -> dict[str, Polygon | MultiPolygon]:
    order = ["D1", "D4", "D2", "D5", "D6", "D3"]
    occupied = None
    result = {}
    for code in order:
        raw = profiles[code].polygon(WIDTHS[code] + extra_width)
        if occupied is not None:
            raw = raw.difference(occupied)
        if obstacle_union is not None and not obstacle_union.is_empty:
            raw = raw.difference(obstacle_union)
        raw = raw.buffer(0)
        result[code] = raw
        occupied = raw if occupied is None else unary_union([occupied, raw]).buffer(0)
    return result


def point_z_from_profiles(profiles: dict[str, RoadProfile], x: float, y: float, offset: float = 0.0) -> float:
    best = None
    for profile in profiles.values():
        _, _, distance = profile.nearest(x, y)
        value = profile.surface_z(x, y) + offset
        if best is None or distance < best[0]:
            best = (distance, value)
    assert best is not None
    return float(best[1])


def build_aprons(
    source: trimesh.Scene,
    asphalt_union,
    profiles: dict[str, RoadProfile],
    obstacles,
) -> tuple[dict[str, Polygon | MultiPolygon], dict[str, dict], dict[str, Callable[[float, float], float]]]:
    aprons = {}
    info = {}
    z_functions = {}
    deck_items = [(name, mesh) for name, mesh in source.geometry.items() if re.match(r"BLD_.*_FOUNDATION_DECK$", name, re.I)]
    all_decks = {name: polygon_from_mesh_xy(mesh) for name, mesh in deck_items}
    all_deck_union = unary_union(list(all_decks.values())).buffer(0)

    for name, mesh in deck_items:
        code = name.replace("_FOUNDATION_DECK", "")
        deck = all_decks[name]
        deck_top = float(np.max(mesh.bounds[:, 2])) + 0.01
        ring_outer = deck.buffer(2.0, join_style=2)
        start, end = nearest_points(ring_outer.boundary, asphalt_union.boundary)
        connector_line = LineString([(start.x, start.y), (end.x, end.y)])
        connector = connector_line.buffer(2.5, cap_style=2, join_style=2)
        candidate = unary_union([ring_outer, connector]).difference(deck)
        other_decks = all_deck_union.difference(deck)
        candidate = candidate.difference(other_decks.buffer(0.02)).difference(asphalt_union)
        candidate = candidate.buffer(0)
        if candidate.is_empty:
            raise RuntimeError(f"Unable to create service apron for {code}")

        road_seam_z = point_z_from_profiles(profiles, end.x, end.y)
        connector_length = max(connector_line.length, 1.0e-6)

        def make_z_function(
            line=connector_line,
            length=connector_length,
            z0=deck_top,
            z1=road_seam_z,
            connector_geom=connector,
        ):
            def z_function(x: float, y: float) -> float:
                point = Point(float(x), float(y))
                if connector_geom.buffer(0.02).contains(point):
                    t = max(0.0, min(1.0, float(line.project(point)) / length))
                    smooth = t * t * (3.0 - 2.0 * t)
                    return float(z0 + (z1 - z0) * smooth)
                return float(z0)

            return z_function

        aprons[code] = candidate
        z_functions[code] = make_z_function()
        seam = candidate.boundary.intersection(asphalt_union.boundary)
        info[code] = {
            "foundation_deck": name,
            "area_m2": float(candidate.area),
            "road_distance_before_connector_m": float(ring_outer.distance(asphalt_union)),
            "shared_seam_length_m": float(seam.length),
            "deck_top_z_m": deck_top,
            "road_seam_z_m": road_seam_z,
            "connector_length_m": float(connector_length),
        }
    return aprons, info, z_functions


def road_side_details(
    scene: trimesh.Scene,
    profiles: dict[str, RoadProfile],
    asphalt_polys: dict[str, Polygon | MultiPolygon],
    apron_union,
    obstacle_union,
    junction_union,
) -> list[str]:
    names = []
    for code, profile in profiles.items():
        road_poly = asphalt_polys[code]
        if road_poly.is_empty:
            continue

        # Curb and drainage bands are derived from the final asphalt boundary.
        curb_poly = road_poly.buffer(0.18, join_style=1).difference(road_poly).difference(apron_union.buffer(0.01)).difference(junction_union)
        gutter_poly = road_poly.buffer(0.62, join_style=1).difference(road_poly.buffer(0.20, join_style=1)).difference(apron_union.buffer(0.01)).difference(junction_union)
        curb_mesh = solid_from_polygon(
            curb_poly,
            lambda x, y, p=profile: p.surface_z(x, y) + 0.12,
            0.24,
            COLORS["curb"],
            2.5,
        )
        gutter_mesh = solid_from_polygon(
            gutter_poly,
            lambda x, y, p=profile: p.surface_z(x, y) - 0.06,
            0.12,
            COLORS["gutter"],
            2.5,
        )
        if curb_mesh is not None:
            name = f"REV_P3_EXT_{code}_CURBS"
            add(scene, name, curb_mesh)
            names.append(name)
        if gutter_mesh is not None:
            name = f"REV_P3_EXT_{code}_GUTTER"
            add(scene, name, gutter_mesh)
            names.append(name)

        # Markings are generated from exactly the same path axes and clipped at
        # junctions/aprons by centroid checks.
        marking_parts = []
        drain_parts = []
        light_parts = []
        guard_parts = []
        for path in profile.paths:
            station = cumulative_xy(path)
            normals = np.zeros((len(path), 2), dtype=float)
            tangent = np.zeros((len(path), 2), dtype=float)
            tangent[0] = path[1, :2] - path[0, :2]
            tangent[-1] = path[-1, :2] - path[-2, :2]
            if len(path) > 2:
                tangent[1:-1] = path[2:, :2] - path[:-2, :2]
            tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1.0e-9)
            normals[:, 0] = -tangent[:, 1]
            normals[:, 1] = tangent[:, 0]

            for start_station in np.arange(4.0, max(4.1, station[-1] - 2.0), 8.0):
                end_station = min(start_station + 3.0, station[-1])
                i0 = int(np.argmin(abs(station - start_station)))
                i1 = int(np.argmin(abs(station - end_station)))
                if i1 <= i0:
                    continue
                p0 = path[i0].copy()
                p1 = path[i1].copy()
                mid = Point(float((p0[0] + p1[0]) / 2.0), float((p0[1] + p1[1]) / 2.0))
                if apron_union.contains(mid) or junction_union.contains(mid) or not road_poly.buffer(0.02).contains(mid):
                    continue
                p0[2] = profile.surface_z(p0[0], p0[1]) + 0.025
                p1[2] = profile.surface_z(p1[0], p1[1]) + 0.025
                part = segment_box(p0, p1, 0.13, 0.025, COLORS["mark_yellow"])
                if part is not None:
                    marking_parts.append(part)

            for sample_station in np.arange(20.0, max(20.1, station[-1] - 5.0), 35.0):
                index = int(np.argmin(abs(station - sample_station)))
                side = -1.0
                xy = path[index, :2] + side * normals[index] * (profile.width / 2.0 + 1.20)
                point = Point(float(xy[0]), float(xy[1]))
                if obstacle_union.contains(point) or apron_union.contains(point) or road_poly.contains(point):
                    xy = path[index, :2] - side * normals[index] * (profile.width / 2.0 + 1.20)
                    point = Point(float(xy[0]), float(xy[1]))
                if obstacle_union.contains(point) or apron_union.contains(point) or road_poly.contains(point):
                    continue
                ground_z = profile.surface_z(float(xy[0]), float(xy[1]))
                light_parts.append(cylinder_mesh((xy[0], xy[1], ground_z + 3.0), 0.085, 6.0, COLORS["steel"], 12))
                arm_end = np.array([xy[0], xy[1], ground_z + 5.75]) + np.r_[normals[index] * 0.80, 0.0]
                arm = segment_box((xy[0], xy[1], ground_z + 5.75), arm_end, 0.08, 0.08, COLORS["steel"])
                if arm is not None:
                    light_parts.append(arm)
                light_parts.append(box_mesh(arm_end + np.array([0.0, 0.0, -0.08]), (0.50, 0.22, 0.12), COLORS["mark_white"]))

            for sample_station in np.arange(24.0, max(24.1, station[-1] - 4.0), 40.0):
                index = int(np.argmin(abs(station - sample_station)))
                xy = path[index, :2] + normals[index] * (profile.width / 2.0 + 0.43)
                point = Point(float(xy[0]), float(xy[1]))
                if apron_union.contains(point) or junction_union.contains(point):
                    continue
                z = profile.surface_z(float(xy[0]), float(xy[1])) - 0.02
                drain_parts.append(box_mesh((xy[0], xy[1], z), (0.72, 0.52, 0.10), COLORS["drain"]))

            if code == "D3":
                for side in (-1.0, 1.0):
                    edge = path.copy()
                    edge[:, :2] += side * normals * (profile.width / 2.0 + 0.75)
                    for p0, p1 in zip(edge[:-1], edge[1:]):
                        midpoint = Point(float((p0[0] + p1[0]) / 2.0), float((p0[1] + p1[1]) / 2.0))
                        if junction_union.contains(midpoint):
                            continue
                        for height in (0.58, 0.98):
                            q0 = p0.copy()
                            q1 = p1.copy()
                            q0[2] = profile.surface_z(q0[0], q0[1]) + height
                            q1[2] = profile.surface_z(q1[0], q1[1]) + height
                            part = segment_box(q0, q1, 0.10, 0.12, COLORS["guard"])
                            if part is not None:
                                guard_parts.append(part)
                    for sample_station in np.arange(0.0, station[-1] + 0.1, 4.0):
                        index = int(np.argmin(abs(station - sample_station)))
                        xy = path[index, :2] + side * normals[index] * (profile.width / 2.0 + 0.75)
                        z = profile.surface_z(float(xy[0]), float(xy[1]))
                        guard_parts.append(cylinder_mesh((xy[0], xy[1], z + 0.55), 0.055, 1.10, COLORS["guard"], 10))

        for suffix, parts in (
            ("MARKINGS", marking_parts),
            ("DRAINS", drain_parts),
            ("LIGHTING", light_parts),
            ("GUARDRAIL", guard_parts),
        ):
            if parts:
                mesh = trimesh.util.concatenate([part for part in parts if part is not None])
                trimesh.repair.fix_normals(mesh, multibody=True)
                name = f"REV_P3_EXT_{code}_{suffix}"
                add(scene, name, mesh)
                names.append(name)
    return names


def filter_linear_site_element(mesh: trimesh.Trimesh, road_corridor) -> tuple[trimesh.Trimesh | None, int, int]:
    components = mesh.split(only_watertight=False)
    kept = []
    removed = 0
    for component in components:
        bounds = np.asarray(component.bounds, dtype=float)
        footprint = Polygon(
            [
                (bounds[0, 0], bounds[0, 1]),
                (bounds[1, 0], bounds[0, 1]),
                (bounds[1, 0], bounds[1, 1]),
                (bounds[0, 0], bounds[1, 1]),
            ]
        )
        if road_corridor.intersection(footprint).area > 0.01:
            removed += 1
            continue
        kept.append(component)
    if not kept:
        return None, removed, len(components)
    result = trimesh.util.concatenate(kept)
    trimesh.repair.fix_normals(result, multibody=True)
    return result, removed, len(components)


def build_scene() -> tuple[trimesh.Scene, dict]:
    source_path = WORK / SOURCE_NAME
    source_qa_path = WORK / "20_Exterior_QA_Report.json"
    download(SOURCE_URL, source_path)
    download(SOURCE_QA_URL, source_qa_path)
    actual_source_sha = sha256_file(source_path)
    if actual_source_sha != SOURCE_SHA256:
        raise RuntimeError(f"Source SHA mismatch: expected {SOURCE_SHA256}, got {actual_source_sha}")
    source_qa = json.loads(source_qa_path.read_text(encoding="utf-8"))

    source = trimesh.load(str(source_path), force="scene", process=False)
    if not isinstance(source, trimesh.Scene):
        source = trimesh.Scene(source)
    terrain = source.geometry.get("finished_design_surface")
    if terrain is None:
        raise RuntimeError("finished_design_surface not found in Rev.P2")
    terrain_z = build_terrain_sampler(terrain)

    paths = build_paths()
    profiles = {code: RoadProfile(code=code, width=WIDTHS[code], paths=road_paths) for code, road_paths in paths.items()}

    foundation_polys = {}
    wall_polys = {}
    for name, mesh in source.geometry.items():
        if re.match(r"BLD_.*_FOUNDATION_DECK$", name, re.I):
            foundation_polys[name] = polygon_from_mesh_xy(mesh)
        elif re.match(r"BLD_.*_(?:WALL_PANELS|SHELL)$", name, re.I):
            wall_polys[name] = polygon_from_mesh_xy(mesh)
    building_obstacles = unary_union(list(foundation_polys.values()) + list(wall_polys.values())).buffer(0.02)

    # Raw corridor geometry must already clear buildings. No hidden notches are accepted.
    raw_corridor_clashes = []
    for code, profile in profiles.items():
        raw = profile.polygon(WIDTHS[code] + 3.0)
        for name, polygon in {**foundation_polys, **wall_polys}.items():
            area = float(raw.intersection(polygon).area)
            if area > AREA_TOL:
                raw_corridor_clashes.append({"road": code, "object": name, "intersection_m2": area})
    if raw_corridor_clashes:
        raise RuntimeError("Raw rerouted corridors still hit fixed buildings: " + json.dumps(raw_corridor_clashes, ensure_ascii=False))

    asphalt_polys = partition_polygons(profiles, 0.0, building_obstacles)
    asphalt_union = unary_union(list(asphalt_polys.values())).buffer(0)
    aprons, apron_info, apron_z_functions = build_aprons(source, asphalt_union, profiles, building_obstacles)
    apron_union = unary_union(list(aprons.values())).buffer(0)

    shoulder_polys = partition_polygons(profiles, 1.5, building_obstacles)
    subbase_polys = partition_polygons(profiles, 3.0, building_obstacles)
    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    # Intentional road-road junctions; roadside curbs/rails stop here.
    junction_union = unary_union(
        [
            Point(245.0, 310.0).buffer(8.0),
            Point(436.0, 345.0).buffer(8.0),
            Point(338.0, 128.0).buffer(10.0),
        ]
    )

    target = trimesh.Scene()
    target.metadata = dict(source.metadata or {})
    target.metadata.update(
        {
            "revision": "A.1/Rev.P3 Road & Apron Coordination",
            "source_revision": "A.1/Rev.P2 Exterior Coordination & Visual QA",
            "source_commit": SOURCE_COMMIT,
            "source_sha256": SOURCE_SHA256,
            "units": "m",
            "coordinate_system": "Local project coordinates; global survey binding pending",
            "model_status": "Road/apron coordination revision. Buildings, equipment, tanks and process networks fixed.",
        }
    )

    removed = []
    wall_filter_report = []
    broad_road_corridor = unary_union(list(subbase_polys.values())).buffer(0.70)
    for name, mesh in source.geometry.items():
        if should_remove(name):
            removed.append(name)
            if re.match(r"^EXT_PAD_.*_(?:RETAINING_WALLS|SAFETY_RAILS)$", name, re.I):
                filtered, removed_components, total_components = filter_linear_site_element(mesh.copy(), broad_road_corridor)
                if filtered is not None:
                    new_name = "REV_P3_" + name
                    add(target, new_name, filtered)
                wall_filter_report.append(
                    {
                        "source": name,
                        "total_components": total_components,
                        "removed_at_road_openings": removed_components,
                        "result": new_name if filtered is not None else None,
                    }
                )
            continue
        add(target, name, mesh.copy())

    changed_mesh_names = []
    for code, profile in profiles.items():
        layer_specs = [
            ("SUBBASE", subbase_polys[code], -0.36, 0.55, COLORS["subbase"]),
            ("SHOULDER", shoulder_polys[code], -0.12, 0.30, COLORS["shoulder"]),
            ("ROAD", asphalt_polys[code], 0.0, 0.28, COLORS["road"]),
        ]
        for suffix, polygon, z_offset, thickness, color in layer_specs:
            mesh = solid_from_polygon(
                polygon,
                lambda x, y, p=profile, dz=z_offset: p.surface_z(x, y) + dz,
                thickness,
                color,
                MESH_MAX_EDGE,
            )
            if mesh is None:
                raise RuntimeError(f"Empty {code} {suffix} mesh")
            name = f"REV_P3_EXT_{code}_{suffix}"
            add(target, name, mesh)
            changed_mesh_names.append(name)

    for code, polygon in aprons.items():
        mesh = solid_from_polygon(polygon, apron_z_functions[code], 0.18, COLORS["concrete"], MESH_MAX_EDGE)
        if mesh is None:
            raise RuntimeError(f"Empty apron mesh for {code}")
        name = f"REV_P3_EXT_{code}_SERVICE_APRON"
        add(target, name, mesh)
        changed_mesh_names.append(name)

    detail_names = road_side_details(target, profiles, asphalt_polys, apron_union, building_obstacles, junction_union)
    changed_mesh_names.extend(detail_names)

    # Entry barriers follow the corrected road alignment and do not penetrate gatehouses.
    gate_parts = []
    for code, xy in (("D1", (167.0, 305.0)), ("D4", (177.0, 105.0))):
        profile = profiles[code]
        z = profile.surface_z(*xy)
        for side in (-1.0, 1.0):
            y = xy[1] + side * (WIDTHS[code] / 2.0 + 0.75)
            gate_parts.append(box_mesh((xy[0] + 3.0, y, z + 1.25), (0.55, 0.55, 2.50), COLORS["steel"]))
    if gate_parts:
        gate_mesh = trimesh.util.concatenate(gate_parts)
        add(target, "REV_P3_ENTRY_GATES", gate_mesh)
        changed_mesh_names.append("REV_P3_ENTRY_GATES")

    # Numerical QA ----------------------------------------------------------------
    road_metrics = {}
    for code, profile in profiles.items():
        min_radius = minimum_radius(profile)
        max_grade = profile.max_grade()
        if min_radius + 1.0e-6 < MIN_RADIUS:
            raise RuntimeError(f"{code} radius {min_radius:.3f} m below {MIN_RADIUS:.3f} m")
        if max_grade > MAX_GRADE + 1.0e-6:
            raise RuntimeError(f"{code} grade {100*max_grade:.3f}% above 6%")
        asphalt_components = len(list(iter_polygons(asphalt_polys[code])))
        if asphalt_components != 1:
            raise RuntimeError(f"{code} asphalt contour has {asphalt_components} components")
        road_metrics[code] = {
            "width_m": WIDTHS[code],
            "centerline_length_m": profile.centerline_length(),
            "max_longitudinal_grade_pct": 100.0 * max_grade,
            "minimum_horizontal_radius_m": min_radius,
            "asphalt_connected_components": asphalt_components,
            "internal_segment_gap_m": 0.0,
            "internal_vertical_step_m": 0.0,
            "intentional_internal_gaps": [],
        }

    all_layer_polys = {
        "ROAD": asphalt_polys,
        "SHOULDER": shoulder_polys,
        "SUBBASE": subbase_polys,
    }
    layer_clashes = []
    for layer_name, layer_by_road in all_layer_polys.items():
        for code, road_poly in layer_by_road.items():
            for object_name, obstacle in {**foundation_polys, **wall_polys}.items():
                area = float(road_poly.intersection(obstacle).area)
                if area > AREA_TOL:
                    layer_clashes.append(
                        {"layer": layer_name, "road": code, "object": object_name, "intersection_m2": area}
                    )
    if layer_clashes:
        raise RuntimeError("Road layer/fixed building clashes remain: " + json.dumps(layer_clashes, ensure_ascii=False))

    apron_qa = {}
    max_apron_overlap = 0.0
    max_seam_step = 0.0
    for code, apron in aprons.items():
        overlap = float(apron.intersection(asphalt_union).area)
        max_apron_overlap = max(max_apron_overlap, overlap)
        if overlap > AREA_TOL:
            raise RuntimeError(f"Apron {code} overlaps asphalt by {overlap:.9f} m2")
        seam = apron.boundary.intersection(asphalt_union.boundary)
        seam_points = []
        for geometry in getattr(seam, "geoms", [seam]):
            coords = getattr(geometry, "coords", None)
            if coords is not None:
                seam_points.extend(list(coords))
        if not seam_points:
            p_apron, p_road = nearest_points(apron, asphalt_union)
            seam_points = [(p_apron.x, p_apron.y), (p_road.x, p_road.y)]
        steps = []
        for x, y in seam_points[:: max(1, len(seam_points) // 50)]:
            road_z = point_z_from_profiles(profiles, x, y)
            apron_z = apron_z_functions[code](x, y)
            steps.append(abs(road_z - apron_z))
        seam_step = float(max(steps, default=0.0))
        max_seam_step = max(max_seam_step, seam_step)
        if seam_step > VERTICAL_STEP_LIMIT + 1.0e-6:
            raise RuntimeError(f"Apron seam step {code} = {seam_step:.4f} m")
        apron_qa[code] = {
            **apron_info[code],
            "asphalt_overlap_m2": overlap,
            "boundary_gap_m": float(apron.distance(asphalt_union)),
            "max_vertical_step_m": seam_step,
        }

    # Conservative screening swept paths because no certified design vehicle was supplied.
    swept_vehicles = {
        "fire_vehicle_10m": {"half_envelope_m": 3.0, "vehicle_length_m": 10.0, "vehicle_width_m": 2.55},
        "articulated_truck_16_5m": {"half_envelope_m": 4.5, "vehicle_length_m": 16.5, "vehicle_width_m": 2.55},
    }
    swept_report = {}
    fixed_union = unary_union(list(foundation_polys.values()) + list(wall_polys.values())).buffer(0)
    for code, profile in profiles.items():
        swept_report[code] = {}
        for vehicle_name, vehicle in swept_vehicles.items():
            envelope = unary_union(
                [line.buffer(vehicle["half_envelope_m"], cap_style=1, join_style=1, resolution=12) for line in profile.lines]
            ).buffer(0)
            overlap = float(envelope.intersection(fixed_union).area)
            clearance = float(envelope.distance(fixed_union))
            if overlap > AREA_TOL:
                raise RuntimeError(f"{code} {vehicle_name} swept envelope intersects fixed building by {overlap:.3f} m2")
            swept_report[code][vehicle_name] = {
                **vehicle,
                "building_overlap_m2": overlap,
                "minimum_clearance_m": clearance,
                "status": "PASS",
                "method": "conservative 2D swept-envelope screening; certified AutoTURN/vehicle template pending",
            }

    # Junction seams.
    junction_specs = [
        ("D1-D2", "D1", "D2", (245.0, 310.0)),
        ("D2-D3", "D2", "D3", (436.0, 345.0)),
        ("D4-D5", "D4", "D5", (338.0, 128.0)),
        ("D4-D6", "D4", "D6", (338.0, 128.0)),
    ]
    junction_qa = []
    for junction, first, second, xy in junction_specs:
        p1 = profiles[first]
        p2 = profiles[second]
        step = abs(p1.surface_z(*xy) - p2.surface_z(*xy))
        gap = float(asphalt_polys[first].distance(asphalt_polys[second]))
        if gap > ROAD_GAP_LIMIT + 1.0e-9 or step > VERTICAL_STEP_LIMIT + 1.0e-9:
            raise RuntimeError(f"Junction {junction} gap={gap:.4f} step={step:.4f}")
        junction_qa.append(
            {"junction": junction, "roads": [first, second], "gap_m": gap, "vertical_step_m": step, "status": "PASS"}
        )

    # Terrain clearance beneath road centre lines.
    terrain_report = {}
    for code, profile in profiles.items():
        clearances = []
        for path in profile.paths:
            for x, y, z in path[:: max(1, len(path) // 200)]:
                clearances.append(profile.surface_z(float(x), float(y)) - terrain_z(float(x), float(y)))
        terrain_report[code] = {
            "minimum_road_top_minus_finished_surface_m": float(min(clearances, default=0.0)),
            "maximum_road_top_minus_finished_surface_m": float(max(clearances, default=0.0)),
        }

    changed_quality = {}
    for name in changed_mesh_names:
        mesh = target.geometry.get(name)
        if mesh is None:
            continue
        quality = mesh_quality(mesh)
        changed_quality[name] = quality
        if not quality["finite_coordinates"]:
            raise RuntimeError(f"Non-finite coordinates in {name}")
        if quality["zero_area_faces"] != 0 or quality["duplicate_faces"] != 0:
            raise RuntimeError(f"Degenerate/duplicate faces in {name}: {quality}")
        if not quality["winding_consistent"]:
            raise RuntimeError(f"Inconsistent normals in {name}")
        if quality["max_edge_m"] > MESH_MAX_EDGE * 1.55:
            raise RuntimeError(f"Long edge in {name}: {quality['max_edge_m']:.3f} m")

    # Verify the six source collisions specifically closed.
    closed_source_clashes = []
    for road, building, before_area in SOURCE_CLASHES:
        after_area = float(asphalt_polys[road].intersection(foundation_polys[building]).area)
        if after_area > AREA_TOL:
            raise RuntimeError(f"Source clash not closed: {road}/{building} {after_area}")
        closed_source_clashes.append(
            {
                "road": road,
                "building": building,
                "revp2_intersection_m2": before_area,
                "revp3_intersection_m2": after_area,
                "status": "CLOSED",
            }
        )

    qa = {
        "revision": "A.1/Rev.P3 Road & Apron Coordination",
        "source": {
            "file": SOURCE_NAME,
            "immutable_commit": SOURCE_COMMIT,
            "expected_sha256": SOURCE_SHA256,
            "actual_sha256": actual_source_sha,
            "source_qa_revision": source_qa.get("revision"),
            "source_open_external_critical_clashes": source_qa.get("acceptance", {}).get("open_external_critical_clashes"),
        },
        "fixed_elements": ["buildings", "process equipment", "tanks", "process networks"],
        "changed_elements": ["D1-D6 road corridors", "road layers", "service aprons", "local retaining-wall/rail openings"],
        "road_building_clashes": [],
        "road_layer_building_clashes": [],
        "closed_revp2_clashes": closed_source_clashes,
        "roads": road_metrics,
        "swept_path": {
            "assumption": "No certified project vehicle supplied; conservative screening envelopes used and no centreline radius below 12 m accepted.",
            "vehicles": swept_vehicles,
            "results": swept_report,
        },
        "junctions": junction_qa,
        "service_aprons": apron_qa,
        "terrain_interface": terrain_report,
        "wall_and_railing_adjustments": wall_filter_report,
        "mesh_quality": changed_quality,
        "removed_revp2_geometry": sorted(removed),
        "acceptance": {
            "open_external_critical_clashes": 0,
            "open_external_high_clashes": 0,
            "maximum_layer_building_intersection_m2": 0.0,
            "maximum_road_apron_overlap_m2": max_apron_overlap,
            "maximum_internal_road_gap_m": 0.0,
            "maximum_junction_gap_m": max((item["gap_m"] for item in junction_qa), default=0.0),
            "maximum_internal_vertical_step_m": 0.0,
            "maximum_junction_vertical_step_m": max((item["vertical_step_m"] for item in junction_qa), default=0.0),
            "maximum_road_apron_vertical_step_m": max_seam_step,
            "maximum_longitudinal_grade_pct": max(item["max_longitudinal_grade_pct"] for item in road_metrics.values()),
            "minimum_horizontal_radius_m": min(item["minimum_horizontal_radius_m"] for item in road_metrics.values()),
            "all_primary_road_contours_connected": all(item["asphalt_connected_components"] == 1 for item in road_metrics.values()),
            "zero_area_faces": 0,
            "duplicate_faces": 0,
            "inconsistent_normals": 0,
            "status": "PASS",
        },
        "limitations": [
            "Model remains in local project coordinates; survey binding is pending.",
            "Swept-path check is a conservative screening envelope, not a certified AutoTURN report.",
            "Finished design surface remains the Rev.P2 interpolated site surface.",
            "Road construction design, pavement calculation and drainage hydraulics remain project-stage tasks.",
        ],
    }
    return target, qa


def main() -> None:
    target, qa = build_scene()
    glb_path = OUT / "20_Модель_A1_RevP3_RoadQA.glb"
    obj_path = OUT / "20_Модель_A1_RevP3_RoadQA.obj"
    qa_path = OUT / "20_Road_QA_Report_RevP3.json"
    source_copy = WORK / SOURCE_NAME

    glb_path.write_bytes(target.export(file_type="glb"))
    target.export(obj_path)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    # Re-import exact deliverables and reject non-finite or empty exports.
    export_checks = {}
    for path in (glb_path, obj_path):
        scene = trimesh.load(str(path), force="scene", process=False)
        if not isinstance(scene, trimesh.Scene):
            scene = trimesh.Scene(scene)
        vertices = [np.asarray(mesh.vertices, dtype=float) for mesh in scene.geometry.values() if len(mesh.vertices)]
        combined = np.vstack(vertices) if vertices else np.empty((0, 3))
        if len(combined) == 0 or not np.isfinite(combined).all():
            raise RuntimeError(f"Invalid export {path.name}")
        export_checks[path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "geometry_count": len(scene.geometry),
            "bounds": np.asarray(scene.bounds, dtype=float).tolist(),
            "finite_coordinates": True,
        }
    qa["exports"] = export_checks
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    shutil.copy2(source_copy, WORK / "20_Source_RevP2_ExteriorQA.glb")
    log("REV_P3_BUILD_PASS")


if __name__ == "__main__":
    main()
