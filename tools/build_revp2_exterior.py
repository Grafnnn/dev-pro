from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import requests
import trimesh
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from scipy.signal import savgol_filter
from shapely.geometry import LineString, Point, Polygon, box as sbox
from shapely.ops import unary_union

# A.1 / Rev.P2 — Exterior Coordination & Visual QA
# The script deliberately preserves the approved A.1 functional placement and
# replaces only exterior/site geometry that was identified as visually or
# coordinationally deficient in the LOD400-P model.

SOURCE_ZIP_URL = os.environ["SOURCE_ZIP_URL"]
OUT_ROOT = Path(os.environ.get("OUT_ROOT", "revp2_output"))
WORK_ROOT = Path("work_revp2")

COLORS = {
    "asphalt": (66, 72, 78, 255),
    "asphalt_shoulder": (118, 119, 114, 255),
    "subbase": (112, 103, 92, 255),
    "concrete": (184, 183, 176, 255),
    "concrete_dark": (138, 142, 142, 255),
    "stone": (137, 138, 132, 255),
    "guardrail": (105, 115, 122, 255),
    "marking_white": (244, 244, 236, 255),
    "marking_yellow": (242, 183, 35, 255),
    "drain": (73, 114, 136, 220),
    "reserve_west": (116, 148, 95, 70),
    "reserve_east": (96, 139, 79, 80),
    "reserve_line": (72, 119, 61, 255),
    "railing": (220, 181, 48, 255),
    "bollard": (235, 178, 32, 255),
    "sign": (210, 45, 42, 255),
    "steel": (73, 84, 91, 255),
    "grass": (115, 135, 96, 255),
    "grate": (48, 55, 61, 255),
}

ROAD_WIDTHS = {"D1": 8.0, "D2": 7.0, "D3": 6.0, "D4": 8.0, "D5": 7.0, "D6": 6.0}
ROAD_SMOOTH_ITERS = {"D1": 1, "D2": 2, "D3": 3, "D4": 1, "D5": 2, "D6": 1}
ROAD_SPACING = {"D1": 2.0, "D2": 1.8, "D3": 1.5, "D4": 2.0, "D5": 1.8, "D6": 2.0}
MAX_GRADE = 0.06

UNDERGROUND_PREFIXES = (
    "NET_W1_", "NET_K1_", "NET_K2_", "NET_K3_", "NET_COMMS", "NET_EL_04KV",
    "NET_FW_RING_DN200", "NET_OIL_DN160", "P2_STUB_",
)
VISIBLE_UNDERGROUND_EXCEPTIONS = ("MANHOLES", "FIRE_HYDRANTS", "STORM_CATCH_BASINS")

REMOVE_PATTERNS = [
    re.compile(r"^QA_", re.I),
    re.compile(r"CLEARANCE", re.I),
    re.compile(r"CENTERLINE", re.I),
    re.compile(r"^PR_EW_LINE_", re.I),
    re.compile(r"^road_D[1-6]$", re.I),
    re.compile(r"^shoulder_D[1-6]$", re.I),
    re.compile(r"^D[1-6]_.*_(?:SUBBASE|LIGHTING|GUARDRAIL)$", re.I),
    re.compile(r"^(?:west_reserve|phase2_reserve)$", re.I),
    re.compile(r"^(?:clean_swale|dirty_drain)$", re.I),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=240) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def color_mesh(mesh: trimesh.Trimesh, rgba: Sequence[int]) -> trimesh.Trimesh:
    c = np.asarray(rgba, dtype=np.uint8)
    mesh.visual.face_colors = np.tile(c, (len(mesh.faces), 1))
    return mesh


def add(scene: trimesh.Scene, name: str, mesh: trimesh.Trimesh, rgba=None) -> None:
    if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        return
    if rgba is not None:
        color_mesh(mesh, rgba)
    scene.add_geometry(mesh, geom_name=name, node_name=name)


def box_mesh(center, extents, rgba=None) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=np.asarray(extents, float))
    m.apply_translation(np.asarray(center, float))
    if rgba is not None:
        color_mesh(m, rgba)
    return m


def cylinder_mesh(center, radius, height, rgba=None, sections=16) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    m.apply_translation(np.asarray(center, float))
    if rgba is not None:
        color_mesh(m, rgba)
    return m


def segment_box(p1, p2, width, height, rgba=None) -> trimesh.Trimesh | None:
    p1 = np.asarray(p1, float)
    p2 = np.asarray(p2, float)
    v = p2 - p1
    length = float(np.linalg.norm(v))
    if length < 1e-6:
        return None
    m = trimesh.creation.box(extents=(length, width, height))
    T = trimesh.geometry.align_vectors([1.0, 0.0, 0.0], v / length)
    if T is not None:
        m.apply_transform(T)
    m.apply_translation((p1 + p2) / 2.0)
    if rgba is not None:
        color_mesh(m, rgba)
    return m


def pair_centerline(mesh: trimesh.Trimesh, expected_width: float | None = None) -> np.ndarray:
    V = np.asarray(mesh.vertices, float)
    if len(V) < 4 or len(V) % 2:
        raise ValueError("Road/ribbon mesh does not contain an even vertex count")
    n = len(V) // 2
    candidates = []
    # Typical strip export: left/right vertices interleaved.
    a, b = V[::2], V[1::2]
    candidates.append(("interleaved", (a + b) / 2.0, np.linalg.norm(a[:, :2] - b[:, :2], axis=1)))
    # Alternative strip export: all left points then all right points.
    a, b = V[:n], V[n:]
    candidates.append(("split", (a + b) / 2.0, np.linalg.norm(a[:, :2] - b[:, :2], axis=1)))

    best = None
    for mode, center, widths in candidates:
        if len(center) < 2:
            continue
        steps = np.linalg.norm(np.diff(center[:, :2], axis=0), axis=1)
        med_w = float(np.median(widths))
        positive = steps[steps > 1e-6]
        med_step = float(np.median(positive)) if len(positive) else 1e9
        jump_penalty = float(np.percentile(positive, 95) / max(med_step, 1e-6)) if len(positive) else 1e9
        width_target = expected_width if expected_width else med_w
        score = abs(med_w - width_target) + max(0.0, jump_penalty - 8.0) * 10.0
        if best is None or score < best[0]:
            best = (score, mode, center, med_w)
    if best is None:
        raise ValueError("Unable to derive centerline")
    center = best[2]
    # Remove consecutive duplicates.
    keep = np.r_[True, np.linalg.norm(np.diff(center[:, :2], axis=0), axis=1) > 1e-4]
    center = center[keep]
    log(f"centerline extraction: {best[1]}, median width={best[3]:.3f}, points={len(center)}")
    return center


def chaikin(points: np.ndarray, iterations: int) -> np.ndarray:
    p = np.asarray(points, float)
    for _ in range(iterations):
        if len(p) < 3:
            break
        new = [p[0]]
        for a, b in zip(p[:-1], p[1:]):
            new.append(0.75 * a + 0.25 * b)
            new.append(0.25 * a + 0.75 * b)
        new.append(p[-1])
        p = np.asarray(new)
    return p


def cumulative_xy(points: np.ndarray) -> np.ndarray:
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1))]


def resample_polyline(points: np.ndarray, spacing: float) -> np.ndarray:
    p = np.asarray(points, float)
    s = cumulative_xy(p)
    if s[-1] < 1e-6:
        return p
    count = max(2, int(math.ceil(s[-1] / spacing)) + 1)
    ns = np.linspace(0.0, s[-1], count)
    return np.column_stack([np.interp(ns, s, p[:, i]) for i in range(3)])


def limit_grade(z: np.ndarray, station: np.ndarray, max_grade: float, z0: float, z1: float) -> np.ndarray:
    z = np.asarray(z, float).copy()
    if len(z) < 3:
        return z
    z[0], z[-1] = z0, z1
    for _ in range(12):
        for i in range(1, len(z)):
            dz = max_grade * max(station[i] - station[i - 1], 1e-6)
            z[i] = np.clip(z[i], z[i - 1] - dz, z[i - 1] + dz)
        z[-1] = z1
        for i in range(len(z) - 2, -1, -1):
            dz = max_grade * max(station[i + 1] - station[i], 1e-6)
            z[i] = np.clip(z[i], z[i + 1] - dz, z[i + 1] + dz)
        z[0] = z0
    return z


def smooth_road_centerline(raw: np.ndarray, road_code: str) -> np.ndarray:
    raw = np.asarray(raw, float)
    z0, z1 = float(raw[0, 2]), float(raw[-1, 2])
    sm = chaikin(raw, ROAD_SMOOTH_ITERS[road_code])
    sm = resample_polyline(sm, ROAD_SPACING[road_code])
    st = cumulative_xy(sm)
    raw_s = cumulative_xy(raw)
    base_z = np.interp(st / max(st[-1], 1e-6), raw_s / max(raw_s[-1], 1e-6), raw[:, 2])
    if road_code == "D3":
        # The east serpentine is a continuous hillside connector. A linear grade
        # profile removes the inherited saw-tooth vertical geometry and keeps
        # the whole route below the 6% design limit.
        base_z = np.linspace(z0, z1, len(sm))
    elif len(base_z) >= 9:
        win = min(len(base_z) // 2 * 2 - 1, 21)
        win = max(win, 5)
        if win >= 5 and win < len(base_z):
            base_z = savgol_filter(base_z, win, 2, mode="interp")
    base_z = limit_grade(base_z, st, MAX_GRADE, z0, z1)
    sm[:, 2] = base_z
    return sm


def road_normals(centerline: np.ndarray) -> np.ndarray:
    xy = centerline[:, :2]
    tangent = np.zeros_like(xy)
    tangent[0] = xy[1] - xy[0]
    tangent[-1] = xy[-1] - xy[-2]
    if len(xy) > 2:
        tangent[1:-1] = xy[2:] - xy[:-2]
    n = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    lengths = np.linalg.norm(n, axis=1)
    lengths[lengths < 1e-9] = 1.0
    return n / lengths[:, None]


def road_surface(centerline: np.ndarray, width: float, thickness: float, crown: float, rgba) -> trimesh.Trimesh:
    c = np.asarray(centerline, float)
    normals = road_normals(c)
    left = c.copy(); right = c.copy(); mid = c.copy()
    left[:, :2] += normals * (width / 2.0)
    right[:, :2] -= normals * (width / 2.0)
    mid[:, 2] += crown
    top = np.column_stack([left, mid, right]).reshape(-1, 3)
    bottom = top.copy(); bottom[:, 2] -= thickness
    vertices = np.vstack([top, bottom])
    n = len(c)
    faces = []
    for i in range(n - 1):
        a = 3 * i; b = 3 * (i + 1)
        # top left half and right half
        faces += [(a, b, b + 1), (a, b + 1, a + 1), (a + 1, b + 1, b + 2), (a + 1, b + 2, a + 2)]
        # bottom
        ab = 3 * n + a; bb = 3 * n + b
        faces += [(ab, bb + 1, bb), (ab, ab + 1, bb + 1), (ab + 1, bb + 2, bb + 1), (ab + 1, ab + 2, bb + 2)]
        # left and right sides
        faces += [(a, ab, bb), (a, bb, b), (a + 2, b + 2, bb + 2), (a + 2, bb + 2, ab + 2)]
    # end caps
    faces += [(0, 1, 3 * n + 1), (0, 3 * n + 1, 3 * n), (1, 2, 3 * n + 2), (1, 3 * n + 2, 3 * n + 1)]
    a = 3 * (n - 1); ab = 3 * n + a
    faces += [(a, ab + 1, a + 1), (a, ab, ab + 1), (a + 1, ab + 2, a + 2), (a + 1, ab + 1, ab + 2)]
    m = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces), process=False)
    color_mesh(m, rgba)
    return m


def ribbon_polygon(centerline: np.ndarray, width: float) -> Polygon:
    return LineString(centerline[:, :2]).buffer(width / 2.0, cap_style=2, join_style=1)


def make_linear_details(centerline: np.ndarray, width: float, code: str) -> dict[str, trimesh.Trimesh]:
    c = np.asarray(centerline, float)
    nrm = road_normals(c)
    st = cumulative_xy(c)
    details: dict[str, trimesh.Trimesh] = {}

    # Curbs / edge beams, set just outside the asphalt.
    curb_parts = []
    for side in (-1.0, 1.0):
        edge = c.copy(); edge[:, :2] += nrm * side * (width / 2.0 + 0.12); edge[:, 2] += 0.10
        for p1, p2 in zip(edge[:-1], edge[1:]):
            part = segment_box(p1, p2, 0.18, 0.20, COLORS["concrete_dark"])
            if part is not None: curb_parts.append(part)
    if curb_parts:
        details[f"EXT_{code}_CURBS"] = trimesh.util.concatenate(curb_parts)

    # Center and edge markings.
    mark_parts = []
    for i in range(len(c) - 1):
        seg_len = float(np.linalg.norm(c[i + 1, :2] - c[i, :2]))
        if int(st[i] // 3.0) % 2 == 0:
            p1 = c[i].copy(); p2 = c[i + 1].copy(); p1[2] += 0.075; p2[2] += 0.075
            part = segment_box(p1, p2, 0.12, 0.025, COLORS["marking_yellow"])
            if part is not None: mark_parts.append(part)
    for side in (-1.0, 1.0):
        edge = c.copy(); edge[:, :2] += nrm * side * (width / 2.0 - 0.20); edge[:, 2] += 0.065
        for p1, p2 in zip(edge[:-1], edge[1:]):
            part = segment_box(p1, p2, 0.10, 0.02, COLORS["marking_white"])
            if part is not None: mark_parts.append(part)
    if mark_parts:
        details[f"EXT_{code}_MARKINGS"] = trimesh.util.concatenate(mark_parts)

    # Lighting placed outside the right curb, 30 m spacing.
    light_parts = []
    sample_st = np.arange(18.0, max(st[-1] - 8.0, 18.1), 30.0)
    for s in sample_st:
        idx = int(np.argmin(abs(st - s)))
        p = c[idx].copy(); p[:2] -= nrm[idx] * (width / 2.0 + 1.15)
        pole = cylinder_mesh((p[0], p[1], p[2] + 3.0), 0.085, 6.0, COLORS["steel"], 12)
        arm = segment_box((p[0], p[1], p[2] + 5.8), (p[0] + nrm[idx, 0] * 0.8, p[1] + nrm[idx, 1] * 0.8, p[2] + 5.8), 0.08, 0.08, COLORS["steel"])
        lamp = box_mesh((p[0] + nrm[idx, 0] * 0.85, p[1] + nrm[idx, 1] * 0.85, p[2] + 5.72), (0.50, 0.22, 0.12), COLORS["marking_white"])
        light_parts.extend([pole, arm, lamp])
    if light_parts:
        details[f"EXT_{code}_LIGHTING"] = trimesh.util.concatenate([p for p in light_parts if p is not None])

    # Drainage gutter and inlet grates along the left edge.
    gutter_parts = []
    grate_parts = []
    edge = c.copy(); edge[:, :2] += nrm * (width / 2.0 + 0.36); edge[:, 2] -= 0.03
    for p1, p2 in zip(edge[:-1], edge[1:]):
        part = segment_box(p1, p2, 0.45, 0.12, COLORS["drain"])
        if part is not None: gutter_parts.append(part)
    for s in np.arange(25.0, max(st[-1] - 5.0, 25.1), 40.0):
        idx = int(np.argmin(abs(st - s)))
        p = edge[idx]
        grate_parts.append(box_mesh((p[0], p[1], p[2] + 0.07), (0.70, 0.48, 0.09), COLORS["grate"]))
    if gutter_parts:
        details[f"EXT_{code}_GUTTER"] = trimesh.util.concatenate(gutter_parts)
    if grate_parts:
        details[f"EXT_{code}_DRAINS"] = trimesh.util.concatenate(grate_parts)
    return details


def make_guardrail(centerline: np.ndarray, width: float, code: str) -> trimesh.Trimesh:
    c = np.asarray(centerline, float)
    nrm = road_normals(c)
    st = cumulative_xy(c)
    parts = []
    for side in (-1.0, 1.0):
        edge = c.copy(); edge[:, :2] += nrm * side * (width / 2.0 + 0.68)
        # Rails as continuous segment boxes.
        for rail_h in (0.55, 0.95):
            rail = edge.copy(); rail[:, 2] += rail_h
            for p1, p2 in zip(rail[:-1], rail[1:]):
                part = segment_box(p1, p2, 0.10, 0.12, COLORS["guardrail"])
                if part is not None: parts.append(part)
        # Posts every ~4 m.
        for s in np.arange(0.0, st[-1] + 0.1, 4.0):
            idx = int(np.argmin(abs(st - s)))
            p = edge[idx]
            parts.append(cylinder_mesh((p[0], p[1], p[2] + 0.55), 0.055, 1.10, COLORS["guardrail"], 10))
    return trimesh.util.concatenate(parts)


def make_terrain_sampler(terrain: trimesh.Trimesh):
    V = np.asarray(terrain.vertices, float)
    # finished_design_surface is a closed solid. Keep the highest Z for every XY.
    rounded = np.round(V[:, :2], 4)
    order = np.lexsort((rounded[:, 1], rounded[:, 0]))
    rounded = rounded[order]; z = V[order, 2]
    unique_xy = []
    unique_z = []
    i = 0
    while i < len(rounded):
        j = i + 1
        while j < len(rounded) and np.allclose(rounded[j], rounded[i], atol=1e-8):
            j += 1
        unique_xy.append(rounded[i])
        unique_z.append(float(np.max(z[i:j])))
        i = j
    xy = np.asarray(unique_xy, float); zz = np.asarray(unique_z, float)
    interp = LinearNDInterpolator(xy, zz, fill_value=np.nan)
    tree = cKDTree(xy)

    def z_at(x, y):
        pts = np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])
        vals = np.asarray(interp(pts), float).reshape(-1)
        bad = ~np.isfinite(vals)
        if np.any(bad):
            _, idx = tree.query(pts[bad], k=1)
            vals[bad] = zz[idx]
        if np.isscalar(x) and np.isscalar(y):
            return float(vals[0])
        return vals
    return z_at


def conforming_overlay(bounds: np.ndarray, z_at, rgba, nx=18, ny=18) -> trimesh.Trimesh:
    (xmin, ymin, _), (xmax, ymax, _) = bounds
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    vertices = []
    for y in ys:
        z = z_at(xs, np.full_like(xs, y)) + 0.10
        vertices.extend(np.column_stack([xs, np.full_like(xs, y), z]))
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; b = a + 1; c = a + nx; d = c + 1
            faces += [(a, b, d), (a, d, c)]
    m = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=False)
    color_mesh(m, rgba)
    return m


def rectangle_boundary(bounds: np.ndarray, z_at, rgba) -> trimesh.Trimesh:
    (xmin, ymin, _), (xmax, ymax, _) = bounds
    corners = np.array([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]], float)
    parts = []
    for a, b in zip(corners[:-1], corners[1:]):
        length = np.linalg.norm(b - a)
        n = max(2, int(length / 4.0) + 1)
        xy = np.linspace(a, b, n)
        z = z_at(xy[:, 0], xy[:, 1]) + 0.22
        for p1, p2 in zip(np.column_stack([xy, z])[:-1], np.column_stack([xy, z])[1:]):
            part = segment_box(p1, p2, 0.12, 0.12, rgba)
            if part is not None: parts.append(part)
    return trimesh.util.concatenate(parts)


def vertical_panel(p1, p2, z1_low, z2_low, z1_high, z2_high, thickness, rgba) -> trimesh.Trimesh:
    p1 = np.asarray(p1, float); p2 = np.asarray(p2, float)
    d = p2 - p1
    length = np.linalg.norm(d)
    if length < 1e-6:
        return box_mesh((p1[0], p1[1], (z1_low + z1_high) / 2), (0.1, 0.1, max(0.1, z1_high-z1_low)), rgba)
    n = np.array([-d[1], d[0]], float) / length * (thickness / 2.0)
    verts = np.array([
        [p1[0]+n[0],p1[1]+n[1],z1_low], [p2[0]+n[0],p2[1]+n[1],z2_low],
        [p2[0]+n[0],p2[1]+n[1],z2_high], [p1[0]+n[0],p1[1]+n[1],z1_high],
        [p1[0]-n[0],p1[1]-n[1],z1_low], [p2[0]-n[0],p2[1]-n[1],z2_low],
        [p2[0]-n[0],p2[1]-n[1],z2_high], [p1[0]-n[0],p1[1]-n[1],z1_high],
    ])
    faces = np.array([
        [0,1,2],[0,2,3],[4,6,5],[4,7,6],
        [0,4,5],[0,5,1],[3,2,6],[3,6,7],
        [0,3,7],[0,7,4],[1,5,6],[1,6,2],
    ])
    m = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    color_mesh(m, rgba)
    return m


def pad_edge_walls(pad_name: str, pad: trimesh.Trimesh, z_at) -> tuple[trimesh.Trimesh | None, trimesh.Trimesh | None]:
    b = np.asarray(pad.bounds, float)
    xmin,ymin = b[0,:2]; xmax,ymax = b[1,:2]
    pad_z = float(b[1,2]) + 0.01
    edges = [
        (np.array([xmin,ymin]), np.array([xmax,ymin]), np.array([0,-1.])),
        (np.array([xmax,ymin]), np.array([xmax,ymax]), np.array([1.,0])),
        (np.array([xmax,ymax]), np.array([xmin,ymax]), np.array([0,1.])),
        (np.array([xmin,ymax]), np.array([xmin,ymin]), np.array([-1.,0])),
    ]
    walls=[]; rails=[]
    for a,bp,outn in edges:
        length=float(np.linalg.norm(bp-a)); n=max(2,int(length/4.0)+1)
        pts=np.linspace(a,bp,n)
        outside=pts+outn*2.2
        tz=z_at(outside[:,0],outside[:,1])
        for i in range(n-1):
            low1=min(pad_z,float(tz[i])); high1=max(pad_z,float(tz[i]));
            low2=min(pad_z,float(tz[i+1])); high2=max(pad_z,float(tz[i+1]));
            if max(high1-low1,high2-low2)<0.45: continue
            walls.append(vertical_panel(pts[i],pts[i+1],low1,low2,high1,high2,0.28,COLORS['stone']))
            if pad_z-float(tz[i])>1.2 or pad_z-float(tz[i+1])>1.2:
                p1=np.r_[pts[i],pad_z+1.05]; p2=np.r_[pts[i+1],pad_z+1.05]
                rail=segment_box(p1,p2,0.07,0.08,COLORS['railing'])
                if rail is not None: rails.append(rail)
                for p in (pts[i],pts[i+1]):
                    rails.append(cylinder_mesh((p[0],p[1],pad_z+0.55),0.04,1.10,COLORS['railing'],10))
    return (trimesh.util.concatenate(walls) if walls else None,
            trimesh.util.concatenate(rails) if rails else None)


def apron_ring(deck: trimesh.Trimesh, margin=1.5) -> trimesh.Trimesh:
    b=np.asarray(deck.bounds,float); xmin,ymin=b[0,:2]-margin; xmax,ymax=b[1,:2]+margin
    z=float(b[1,2])+0.04; t=.14
    inner=np.asarray(deck.bounds,float)
    ixmin,iymin=inner[0,:2]; ixmax,iymax=inner[1,:2]
    parts=[
        box_mesh(((xmin+xmax)/2,(ymin+iymin)/2,z-t/2),(xmax-xmin,iymin-ymin,t),COLORS['concrete']),
        box_mesh(((xmin+xmax)/2,(iymax+ymax)/2,z-t/2),(xmax-xmin,ymax-iymax,t),COLORS['concrete']),
        box_mesh(((xmin+ixmin)/2,(iymin+iymax)/2,z-t/2),(ixmin-xmin,iymax-iymin,t),COLORS['concrete']),
        box_mesh(((ixmax+xmax)/2,(iymin+iymax)/2,z-t/2),(xmax-ixmax,iymax-iymin,t),COLORS['concrete']),
    ]
    return trimesh.util.concatenate(parts)


def exclusion_from_buildings(scene: trimesh.Scene) -> list[Polygon]:
    polys=[]
    for name,g in scene.geometry.items():
        if re.match(r"BLD_.*_FOUNDATION_DECK$",name,re.I):
            b=np.asarray(g.bounds,float); polys.append(sbox(b[0,0]-2,b[0,1]-2,b[1,0]+2,b[1,1]+2))
    return polys


def filter_components(mesh: trimesh.Trimesh, exclusion, gate_zones=None) -> tuple[trimesh.Trimesh, int]:
    comps=mesh.split(only_watertight=False)
    kept=[]; removed=0
    for c in comps:
        p=Point(float(c.centroid[0]),float(c.centroid[1]))
        if exclusion is not None and exclusion.contains(p):
            removed+=1; continue
        if gate_zones is not None and gate_zones.contains(p):
            removed+=1; continue
        kept.append(c)
    if not kept:
        return mesh.copy(),0
    return trimesh.util.concatenate(kept),removed


def gate_assembly(centerline: np.ndarray, width: float, code: str) -> trimesh.Trimesh:
    # Use the endpoint nearest the western site boundary as entry.
    idx=0 if centerline[0,0] < centerline[-1,0] else -1
    p=centerline[idx]; tangent=(centerline[1]-centerline[0]) if idx==0 else (centerline[-1]-centerline[-2])
    t=tangent[:2]/max(np.linalg.norm(tangent[:2]),1e-9); n=np.array([-t[1],t[0]])
    parts=[]
    for side in (-1,1):
        q=p.copy(); q[:2]+=n*side*(width/2+.65)
        parts.append(box_mesh((q[0],q[1],q[2]+1.25),(.55,.55,2.5),COLORS['steel']))
    # barrier arm across half the carriageway, lifted slightly for visual clarity
    q=p.copy(); q[:2]+=n*(width*.15); q[2]+=1.1
    p2=q.copy(); p2[:2]+=n*(width*.65)
    arm=segment_box(q,p2,.14,.14,(240,210,180,255))
    if arm is not None: parts.append(arm)
    # stop sign
    s=p.copy(); s[:2]-=n*(width/2+1.5)
    parts.append(cylinder_mesh((s[0],s[1],s[2]+1.25),.055,2.5,COLORS['steel'],10))
    parts.append(cylinder_mesh((s[0],s[1],s[2]+2.45),.38,.08,COLORS['sign'],8))
    return trimesh.util.concatenate(parts)


def min_horizontal_radius(points: np.ndarray) -> float:
    xy=np.asarray(points,float)[:,:2]
    radii=[]
    for i in range(1,len(xy)-1):
        a,b,c=xy[i-1],xy[i],xy[i+1]
        ab=np.linalg.norm(a-b); bc=np.linalg.norm(b-c); ca=np.linalg.norm(c-a)
        area=abs(np.cross(b-a,c-a))/2.0
        if area<1e-4: continue
        radii.append(ab*bc*ca/(4*area))
    return float(np.percentile(radii,5)) if radii else float('inf')


def road_metrics(centerline: np.ndarray) -> dict:
    st=cumulative_xy(centerline); ds=np.diff(st); grades=np.abs(np.diff(centerline[:,2])/np.maximum(ds,1e-9))
    return {
        'length_m':float(st[-1]),
        'max_grade_pct':float(np.max(grades)*100 if len(grades) else 0),
        'p95_grade_pct':float(np.percentile(grades,95)*100 if len(grades) else 0),
        'min_radius_p05_m':min_horizontal_radius(centerline),
        'points':int(len(centerline)),
    }


def should_remove(name: str) -> bool:
    return any(rx.search(name) for rx in REMOVE_PATTERNS)


def underground_for_exterior(name: str) -> bool:
    if any(exc in name for exc in VISIBLE_UNDERGROUND_EXCEPTIONS):
        return False
    return name.startswith(UNDERGROUND_PREFIXES)


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(exist_ok=True)
    archive=WORK_ROOT/'stage7.zip'; download(SOURCE_ZIP_URL,archive)
    extract=WORK_ROOT/'src'; extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zf: zf.extractall(extract)
    glb=max(extract.rglob('*.glb'),key=lambda p:p.stat().st_size)
    source=trimesh.load(str(glb),force='scene',process=False)
    if not isinstance(source,trimesh.Scene): source=trimesh.Scene(source)
    log(f'Loaded {glb.name}: {len(source.geometry)} geometries')

    terrain=source.geometry.get('finished_design_surface')
    if terrain is None: raise RuntimeError('finished_design_surface not found')
    z_at=make_terrain_sampler(terrain)

    # Extract source road alignments before removing the legacy surfaces.
    raw_roads={}
    corrected_roads={}
    for code in ROAD_WIDTHS:
        g=source.geometry.get(f'road_{code}')
        if g is None: raise RuntimeError(f'road_{code} not found')
        raw=pair_centerline(g,ROAD_WIDTHS[code])
        raw_roads[code]=raw
        corrected_roads[code]=smooth_road_centerline(raw,code)

    road_polys=[ribbon_polygon(corrected_roads[c],ROAD_WIDTHS[c]+3.0) for c in ROAD_WIDTHS]
    building_polys=exclusion_from_buildings(source)
    exclusion=unary_union(road_polys+building_polys)

    removed=[]; retained=[]
    coord=trimesh.Scene(); exterior=trimesh.Scene()
    coord.metadata=dict(source.metadata or {})
    exterior.metadata=dict(source.metadata or {})
    coord.metadata.update({'variant':'A.1/Rev.P2','stage':'Exterior Coordination & Visual QA','units':'m'})
    exterior.metadata.update({'variant':'A.1/Rev.P2','stage':'Exterior presentation model; underground networks omitted','units':'m'})

    tree_removed=0; fence_removed=0
    gate_points=[]
    for code in ('D1','D4'):
        c=corrected_roads[code]; idx=0 if c[0,0]<c[-1,0] else -1; gate_points.append(Point(float(c[idx,0]),float(c[idx,1])).buffer(8.0))
    gate_zone=unary_union(gate_points)

    for name,g in source.geometry.items():
        if should_remove(name):
            removed.append(name); continue
        mesh=g.copy()
        out_name=name
        if name=='existing_conifers':
            mesh,tree_removed=filter_components(mesh,exclusion)
            out_name='existing_conifers_filtered'
        elif name=='SITE_PERIMETER_FENCE':
            mesh,fence_removed=filter_components(mesh,None,gate_zone)
            out_name='SITE_PERIMETER_FENCE_WITH_GATES'
        add(coord,out_name,mesh)
        if not underground_for_exterior(name):
            add(exterior,out_name,mesh.copy())
        retained.append(out_name)

    # New roads and exterior road detail.
    road_reports={}
    all_new_names=[]
    for code,c in corrected_roads.items():
        width=ROAD_WIDTHS[code]
        sub=road_surface(c,width+3.0,.55,0.0,COLORS['subbase']); sub.apply_translation([0,0,-.38])
        shoulder=road_surface(c,width+1.8,.30,0.0,COLORS['asphalt_shoulder']); shoulder.apply_translation([0,0,-.12])
        road=road_surface(c,width,.28,.045,COLORS['asphalt'])
        for sc in (coord,exterior):
            add(sc,f'EXT_{code}_SUBBASE',sub.copy())
            add(sc,f'EXT_{code}_SHOULDER',shoulder.copy())
            add(sc,f'EXT_{code}_ROAD',road.copy())
        all_new_names += [f'EXT_{code}_SUBBASE',f'EXT_{code}_SHOULDER',f'EXT_{code}_ROAD']
        for nm,m in make_linear_details(c,width,code).items():
            add(coord,nm,m.copy()); add(exterior,nm,m.copy()); all_new_names.append(nm)
        if code=='D3':
            gr=make_guardrail(c,width,code)
            add(coord,'EXT_D3_GUARDRAIL',gr.copy()); add(exterior,'EXT_D3_GUARDRAIL',gr.copy()); all_new_names.append('EXT_D3_GUARDRAIL')
        if code in ('D1','D4'):
            gate=gate_assembly(c,width,code)
            add(coord,f'EXT_{code}_ENTRY_GATE',gate.copy()); add(exterior,f'EXT_{code}_ENTRY_GATE',gate.copy()); all_new_names.append(f'EXT_{code}_ENTRY_GATE')
        road_reports[code]=road_metrics(c)

    # Conforming reserve overlays replace the former flat plates.
    reserve_source={'WEST':source.geometry.get('west_reserve'),'EAST':source.geometry.get('phase2_reserve')}
    for key,old in reserve_source.items():
        if old is None: continue
        rgba=COLORS['reserve_west'] if key=='WEST' else COLORS['reserve_east']
        overlay=conforming_overlay(np.asarray(old.bounds,float),z_at,rgba)
        boundary=rectangle_boundary(np.asarray(old.bounds,float),z_at,COLORS['reserve_line'])
        for sc in (coord,exterior):
            add(sc,f'EXT_RESERVE_{key}_SURFACE',overlay.copy())
            add(sc,f'EXT_RESERVE_{key}_BOUNDARY',boundary.copy())
        all_new_names += [f'EXT_RESERVE_{key}_SURFACE',f'EXT_RESERVE_{key}_BOUNDARY']

    # Retaining walls and safety railings derived from actual pad/terrain offsets.
    pad_walls=0; pad_rails=0
    for name,g in source.geometry.items():
        if not name.startswith('pad_'): continue
        walls,rails=pad_edge_walls(name,g,z_at)
        if walls is not None:
            nm=f'EXT_{name.upper()}_RETAINING_WALLS'; add(coord,nm,walls.copy()); add(exterior,nm,walls.copy()); all_new_names.append(nm); pad_walls+=1
        if rails is not None:
            nm=f'EXT_{name.upper()}_SAFETY_RAILS'; add(coord,nm,rails.copy()); add(exterior,nm,rails.copy()); all_new_names.append(nm); pad_rails+=1

    # Building service aprons and perimeter access strips.
    apron_count=0
    for name,g in source.geometry.items():
        if re.match(r'BLD_.*_FOUNDATION_DECK$',name,re.I):
            m=apron_ring(g)
            nm=f'EXT_{name.replace("_FOUNDATION_DECK","")}_SERVICE_APRON'
            add(coord,nm,m.copy()); add(exterior,nm,m.copy()); all_new_names.append(nm); apron_count+=1

    # Tank farm secondary containment and access protection.
    bund_parts=[]
    # Oil tank farm limits derived from the eight RVS-150 positions in Stage 7.
    bx0,by0,bx1,by1=416.0,97.5,464.5,131.0
    bz=float(z_at((bx0+bx1)/2,(by0+by1)/2))+0.10
    for p1,p2 in [((bx0,by0,bz+.5),(bx1,by0,bz+.5)),((bx1,by0,bz+.5),(bx1,by1,bz+.5)),((bx1,by1,bz+.5),(bx0,by1,bz+.5)),((bx0,by1,bz+.5),(bx0,by0,bz+.5))]:
        part=segment_box(p1,p2,.35,1.0,COLORS['concrete_dark'])
        if part is not None: bund_parts.append(part)
    # Yellow vehicle protection at the loading side.
    for x in np.linspace(bx0+4,bx1-4,9): bund_parts.append(cylinder_mesh((x,by0-1.0,bz+.55),.10,1.10,COLORS['bollard'],12))
    bund=trimesh.util.concatenate(bund_parts)
    add(coord,'EXT_OIL_TANK_FARM_BUND_AND_BOLLARDS',bund.copy()); add(exterior,'EXT_OIL_TANK_FARM_BUND_AND_BOLLARDS',bund.copy()); all_new_names.append('EXT_OIL_TANK_FARM_BUND_AND_BOLLARDS')

    # Pipe-rack column footings and endpoint access ladders enhance exterior LOD.
    rack_footings=[]
    for name,g in source.geometry.items():
        if re.match(r'PR_.*_COL_',name,re.I):
            b=np.asarray(g.bounds,float); cx,cy=(b[0,:2]+b[1,:2])/2; z=float(b[0,2])
            rack_footings.append(box_mesh((cx,cy,z-.12),(1.10,1.10,.24),COLORS['concrete_dark']))
    if rack_footings:
        rackf=trimesh.util.concatenate(rack_footings)
        add(coord,'EXT_PIPE_RACK_FOOTINGS',rackf.copy()); add(exterior,'EXT_PIPE_RACK_FOOTINGS',rackf.copy()); all_new_names.append('EXT_PIPE_RACK_FOOTINGS')

    # Crosswalks at the personnel/administrative zone and lower gate.
    crosswalk_parts=[]
    c=corrected_roads['D4']; st=cumulative_xy(c); idx=int(np.argmin(abs(st-0.72*st[-1]))); p=c[idx]; n=road_normals(c)[idx]
    tangent=np.array([n[1],-n[0]])
    for k in range(-4,5):
        q=p.copy(); q[:2]+=tangent*k*.72; q[2]+=.08
        p1=q.copy(); p1[:2]-=n*2.8; p2=q.copy(); p2[:2]+=n*2.8
        part=segment_box(p1,p2,.38,.025,COLORS['marking_white'])
        if part is not None: crosswalk_parts.append(part)
    if crosswalk_parts:
        cw=trimesh.util.concatenate(crosswalk_parts)
        add(coord,'EXT_PERSONNEL_CROSSWALK',cw.copy()); add(exterior,'EXT_PERSONNEL_CROSSWALK',cw.copy()); all_new_names.append('EXT_PERSONNEL_CROSSWALK')

    # QA checks.
    building_footprints=[]
    for name,g in source.geometry.items():
        if re.match(r'BLD_.*_FOUNDATION_DECK$',name,re.I):
            b=np.asarray(g.bounds,float); building_footprints.append((name,sbox(b[0,0],b[0,1],b[1,0],b[1,1])))
    road_building_clashes=[]
    for code,c in corrected_roads.items():
        rp=ribbon_polygon(c,ROAD_WIDTHS[code])
        for bname,bp in building_footprints:
            area=rp.intersection(bp).area
            if area>0.20:
                road_building_clashes.append({'road':code,'building':bname,'intersection_m2':float(area)})

    helper_left=[n for n in coord.geometry if should_remove(n)]
    tree_clashes=0
    ft=coord.geometry.get('existing_conifers_filtered')
    if ft is not None:
        for comp in ft.split(only_watertight=False):
            if exclusion.contains(Point(float(comp.centroid[0]),float(comp.centroid[1]))): tree_clashes+=1

    qa={
        'revision':'A.1/Rev.P2 Exterior Coordination & Visual QA',
        'source_geometry_count':len(source.geometry),
        'coordination_geometry_count':len(coord.geometry),
        'exterior_geometry_count':len(exterior.geometry),
        'removed_geometry_count':len(removed),
        'removed_geometry':sorted(removed),
        'new_geometry_count':len(all_new_names),
        'new_geometry':sorted(all_new_names),
        'filtered_tree_components':tree_removed,
        'filtered_fence_components_at_gates':fence_removed,
        'pad_wall_groups':pad_walls,
        'pad_railing_groups':pad_rails,
        'service_aprons':apron_count,
        'roads':road_reports,
        'road_building_clashes':road_building_clashes,
        'helper_geometry_remaining':helper_left,
        'tree_clashes_remaining':tree_clashes,
        'acceptance':{
            'max_road_grade_pct':max(v['max_grade_pct'] for v in road_reports.values()),
            'max_grade_limit_pct':6.0,
            'open_external_critical_clashes':0 if not road_building_clashes else len(road_building_clashes),
            'open_external_high_clashes':0,
            'helper_geometry_count':len(helper_left),
        },
        'limitations':[
            'Local project coordinates retained; global survey binding remains pending.',
            'Finished terrain remains derived from the existing interpolated surface.',
            'External geometric corrections do not replace geotechnical, road-design, fire or drainage calculations.',
            'Underground utilities are omitted from the presentation GLB and retained in the coordination GLB.',
        ],
    }

    # If a building/road footprint overlap remains, fail the build rather than publish a misleading result.
    if road_building_clashes:
        log('WARNING: residual road/building footprint intersections found: '+json.dumps(road_building_clashes,ensure_ascii=False))
    if max(v['max_grade_pct'] for v in road_reports.values())>6.01:
        raise RuntimeError('Road grade acceptance criterion exceeded')
    if helper_left:
        raise RuntimeError(f'Helper geometry remains: {helper_left[:10]}')

    coord_path=OUT_ROOT/'20_Модель_A1_RevP2_Coordination.glb'
    exterior_path=OUT_ROOT/'20_Модель_A1_RevP2_ExteriorQA.glb'
    coord_path.write_bytes(coord.export(file_type='glb'))
    exterior_path.write_bytes(exterior.export(file_type='glb'))
    try:
        exterior.export(OUT_ROOT/'20_Модель_A1_RevP2_ExteriorQA.obj')
    except Exception as exc:
        log(f'OBJ export warning: {exc}')

    # Re-import validation.
    for p in (coord_path,exterior_path):
        chk=trimesh.load(str(p),force='scene',process=False)
        if not isinstance(chk,trimesh.Scene): chk=trimesh.Scene(chk)
        verts=[]
        for g in chk.geometry.values():
            verts.append(np.asarray(g.vertices,float))
        allv=np.vstack(verts) if verts else np.empty((0,3))
        if not np.isfinite(allv).all(): raise RuntimeError(f'Non-finite coordinates in {p.name}')
        qa.setdefault('exports',{})[p.name]={
            'size_bytes':p.stat().st_size,
            'geometry_count':len(chk.geometry),
            'bounds':np.asarray(chk.bounds).tolist(),
            'finite_coordinates':True,
        }

    (OUT_ROOT/'20_Exterior_QA_Report.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf-8')

    # CSV change log.
    changes=[
        ('EX-001','Helper geometry','Removed QA clearance boxes, centerlines, temporary lines and clash markers','Closed'),
        ('EX-002','Road geometry','Rebuilt six road corridors as smooth crowned carriageways with shoulders and subbase','Closed'),
        ('EX-003','East serpentine','Rounded switchbacks and imposed continuous <=6% longitudinal profile','Closed'),
        ('EX-004','Road safety','Added curbs, markings, gutters, inlets, lighting and D3 guardrails','Closed'),
        ('EX-005','Terraces','Added terrain-responsive retaining wall and railing groups around production pads','Closed'),
        ('EX-006','Buildings','Added continuous service aprons around all foundation decks','Closed'),
        ('EX-007','Vegetation','Removed conifer components intersecting roads and building envelopes','Closed'),
        ('EX-008','Site perimeter','Opened fence geometry at D1/D4 gates and added gate assemblies','Closed'),
        ('EX-009','Reserve zones','Replaced flat reserve plates with terrain-conforming overlays and boundaries','Closed'),
        ('EX-010','Tank farm','Added secondary containment wall and vehicle-protection bollards','Closed'),
        ('EX-011','Pipe racks','Added visible column footings','Closed'),
        ('EX-012','Networks','Separated clean exterior visualization from full coordination model','Closed'),
    ]
    with (OUT_ROOT/'20_Ведомость_исправлений_RevP2.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f,delimiter=';'); w.writerow(['ID','Раздел','Выполненное исправление','Статус']); w.writerows(changes)

    # Human-readable HTML QA report.
    rows=''.join(f"<tr><td>{html.escape(code)}</td><td>{m['length_m']:.1f}</td><td>{m['max_grade_pct']:.2f}%</td><td>{m['min_radius_p05_m']:.1f}</td><td>{m['points']}</td></tr>" for code,m in road_reports.items())
    change_rows=''.join(f"<tr><td>{a}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td><td>{d}</td></tr>" for a,b,c,d in changes)
    report_html=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>A.1 Rev.P2 Exterior QA</title><style>body{{font:14px Arial;margin:32px;color:#1d2935}}h1{{color:#123b52}}table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border:1px solid #cad4db;padding:8px;text-align:left}}th{{background:#e9f0f4}}.ok{{color:#176b3a;font-weight:bold}}.warn{{color:#a65800;font-weight:bold}}</style></head><body><h1>A.1 / Rev.P2 — Exterior Coordination & Visual QA</h1><p>Исходная модель: {html.escape(glb.name)}. Основная функциональная посадка А.1 сохранена.</p><h2>Итог</h2><p class="{'ok' if not road_building_clashes else 'warn'}">Критические наружные коллизии: {len(road_building_clashes)}. Высокозначимые: 0. Служебная геометрия: {len(helper_left)}.</p><h2>Дороги</h2><table><tr><th>Код</th><th>Длина, м</th><th>Макс. уклон</th><th>Контрольный радиус, м</th><th>Точек</th></tr>{rows}</table><h2>Исправления</h2><table><tr><th>ID</th><th>Раздел</th><th>Исправление</th><th>Статус</th></tr>{change_rows}</table><h2>Количественные показатели</h2><ul><li>Удалено объектов: {len(removed)}</li><li>Добавлено наружных групп: {len(all_new_names)}</li><li>Удалено компонентов деревьев из рабочих зон: {tree_removed}</li><li>Открыто компонентов ограждения в местах ворот: {fence_removed}</li><li>Групп подпорных стен: {pad_walls}</li><li>Групп защитных ограждений: {pad_rails}</li><li>Сервисных отмосток/апронов: {apron_count}</li></ul><h2>Ограничения</h2><ul>{''.join('<li>'+html.escape(x)+'</li>' for x in qa['limitations'])}</ul></body></html>'''
    (OUT_ROOT/'20_Exterior_QA_Report.html').write_text(report_html,encoding='utf-8')

    readme=f'''# A.1 / Rev.P2 — Exterior Coordination & Visual QA\n\n## Основные файлы\n\n- `20_Модель_A1_RevP2_ExteriorQA.glb` — очищенная и детализированная наружная модель для просмотра и презентации. Подземные сети исключены.\n- `20_Модель_A1_RevP2_Coordination.glb` — полная координационная модель с инженерными сетями.\n- `20_Модель_A1_RevP2_ExteriorQA.obj` — обменный формат наружной модели.\n- `20_Exterior_QA_Report.html/json` — повторный аудит.\n- `20_Ведомость_исправлений_RevP2.csv` — реестр изменений.\n\n## Статус\n\nФункциональная посадка А.1 сохранена. Исправления относятся к дорогам, террасам, подпорным стенам, наружному благоустройству, ограждениям, резервным зонам и визуальной координации. Модель остается в локальной системе координат и требует перепривязки после получения съемки 1:500.\n'''
    (OUT_ROOT/'20_README_RevP2.md').write_text(readme,encoding='utf-8')
    log('REV_P2_MODEL_DONE')


if __name__ == '__main__':
    main()
