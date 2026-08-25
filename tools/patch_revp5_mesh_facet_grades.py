from pathlib import Path


path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

d2_old = '''    roads["D2"] = [assign_linear_z(d2_conn_xy, 133.2, 133.7), assign_constant_z(d2_loop_xy, 133.7)]
'''
d2_new = '''    # Reach the loop formation level before the connector and loop corridors
    # begin to compete for the nearest profile.  The former linear rise ran
    # into the loop footprint and created a real Z discontinuity along the
    # Voronoi switch between the two D2 paths.  A C1 smoothstep over the first
    # 25 m gives zero grade at both ends and a 3.0% peak grade, then holds the
    # loop level exactly through the overlap.
    d2_connector = assign_linear_z(d2_conn_xy, 133.2, 133.7)
    d2_station = cumulative_xy(d2_connector)
    d2_u = np.clip(d2_station / 25.0, 0.0, 1.0)
    d2_connector[:, 2] = 133.2 + 0.5 * (3.0 * d2_u * d2_u - 2.0 * d2_u * d2_u * d2_u)
    roads["D2"] = [d2_connector, assign_constant_z(d2_loop_xy, 133.7)]
'''
if d2_old not in text:
    raise RuntimeError("Rev.P5 D2 connector profile anchor not found")
text = text.replace(d2_old, d2_new, 1)

start = text.find("def _conforming_watertight_solid(\n")
end = text.find("\ndef solid_from_polygon", start)
if start < 0 or end < 0:
    raise RuntimeError("Rev.P5 final road-solid function not found")

replacement = r'''REV_P5_ROAD_CHORD_TOLERANCE_M = 0.001
REV_P5_D5_BUILD_FACET_GRADE_LIMIT_PCT = 6.320
REV_P5_D5_EXPORT_FACET_GRADE_LIMIT_PCT = 100.0 * math.hypot(MAX_GRADE, 0.02)
REV_P5_TRIANGLE_MINIMUM_ANGLE_DEG = 28.0
REV_P5_TRIANGLE_MAXIMUM_AREA_FACTOR = 0.42


def _ring_without_duplicate_closure(ring) -> np.ndarray:
    coordinates = np.asarray(ring.coords, dtype=float)[:, :2]
    if len(coordinates) > 1 and np.linalg.norm(coordinates[0] - coordinates[-1]) <= 1.0e-10:
        coordinates = coordinates[:-1]
    retained = []
    for coordinate in coordinates:
        if not retained or np.linalg.norm(coordinate - retained[-1]) > 1.0e-9:
            retained.append(coordinate)
    result = np.asarray(retained, dtype=float)
    if len(result) < 3:
        raise RuntimeError("Road polygon ring collapsed during PSLG cleanup")
    return result


def _polygon_pslg(component: Polygon, surface_breaklines=None) -> dict:
    rings = [_ring_without_duplicate_closure(component.exterior)]
    rings.extend(_ring_without_duplicate_closure(ring) for ring in component.interiors)
    vertices = []
    segments = []
    holes = []
    vertex_index = {}

    def add_vertex(coordinate) -> int:
        point = np.asarray(coordinate, dtype=float)[:2]
        key = tuple(np.round(point, 8))
        if key not in vertex_index:
            vertex_index[key] = len(vertices)
            vertices.append(point.tolist())
        return int(vertex_index[key])

    for ring_index, coordinates in enumerate(rings):
        indices = [add_vertex(coordinate) for coordinate in coordinates]
        count = len(indices)
        segments.extend([[indices[index], indices[(index + 1) % count]] for index in range(count)])
        if ring_index > 0:
            point = Polygon(coordinates).representative_point()
            holes.append([float(point.x), float(point.y)])

    if surface_breaklines:
        clipped = []
        for line in surface_breaklines:
            intersection = line.intersection(component)
            if not intersection.is_empty:
                clipped.append(intersection)
        if clipped:
            network = unary_union(clipped)

            def iter_lines(geometry):
                if geometry.is_empty:
                    return []
                if geometry.geom_type == "LineString":
                    return [geometry]
                return [
                    item
                    for item in getattr(geometry, "geoms", [])
                    if item.geom_type == "LineString" and item.length > 1.0e-8
                ]

            for line in iter_lines(network):
                coordinates = np.asarray(line.coords, dtype=float)[:, :2]
                indices = [add_vertex(coordinate) for coordinate in coordinates]
                for first, second in zip(indices[:-1], indices[1:]):
                    if first != second:
                        segments.append([first, second])

    unique_segments = []
    seen_segments = set()
    for first, second in segments:
        key = tuple(sorted((int(first), int(second))))
        if first != second and key not in seen_segments:
            seen_segments.add(key)
            unique_segments.append([int(first), int(second)])
    result = {
        "vertices": np.asarray(vertices, dtype=float),
        "segments": np.asarray(unique_segments, dtype=int),
    }
    if holes:
        result["holes"] = np.asarray(holes, dtype=float)
    return result


def _surface_face_metrics(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    z_function: Callable[[float, float], float],
) -> dict:
    vertices = np.asarray(vertices_2d, dtype=float)
    triangles = np.asarray(faces, dtype=int)
    z_values = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices],
        dtype=float,
    )
    plan_triangles = vertices[triangles]
    top_triangles = np.column_stack([vertices, z_values])[triangles]
    normals = np.cross(
        top_triangles[:, 1] - top_triangles[:, 0],
        top_triangles[:, 2] - top_triangles[:, 0],
    )
    double_plan_area = np.abs(normals[:, 2])
    if np.any(double_plan_area <= 1.0e-10):
        raise RuntimeError("Quality triangulation contains a near-zero plan-area top face")
    grades = 100.0 * np.linalg.norm(normals[:, :2], axis=1) / double_plan_area

    centroids = np.mean(plan_triangles, axis=1)
    midpoint_01 = 0.5 * (plan_triangles[:, 0] + plan_triangles[:, 1])
    midpoint_12 = 0.5 * (plan_triangles[:, 1] + plan_triangles[:, 2])
    midpoint_20 = 0.5 * (plan_triangles[:, 2] + plan_triangles[:, 0])
    samples = np.stack([centroids, midpoint_01, midpoint_12, midpoint_20], axis=1)
    vertex_z = z_values[triangles]
    interpolated = np.stack(
        [
            np.mean(vertex_z, axis=1),
            0.5 * (vertex_z[:, 0] + vertex_z[:, 1]),
            0.5 * (vertex_z[:, 1] + vertex_z[:, 2]),
            0.5 * (vertex_z[:, 2] + vertex_z[:, 0]),
        ],
        axis=1,
    )
    actual = np.asarray(
        [
            [z_function(float(point[0]), float(point[1])) for point in row]
            for row in samples
        ],
        dtype=float,
    )
    sample_residual = np.abs(interpolated - actual)
    chord_residual = np.max(sample_residual, axis=1)
    worst_chord_points = samples[
        np.arange(len(samples)),
        np.argmax(sample_residual, axis=1),
    ]

    edge_01 = np.linalg.norm(plan_triangles[:, 1] - plan_triangles[:, 0], axis=1)
    edge_12 = np.linalg.norm(plan_triangles[:, 2] - plan_triangles[:, 1], axis=1)
    edge_20 = np.linalg.norm(plan_triangles[:, 0] - plan_triangles[:, 2], axis=1)
    maximum_edge = np.maximum(np.maximum(edge_01, edge_12), edge_20)
    aspect = maximum_edge * maximum_edge / double_plan_area
    return {
        "z_values": z_values,
        "plan_area_m2": 0.5 * double_plan_area,
        "grade_pct": grades,
        "chord_residual_m": chord_residual,
        "aspect_ratio": aspect,
        "centroids": centroids,
        "worst_chord_points": worst_chord_points,
    }


def _quality_profile_triangulation(
    component: Polygon,
    z_function: Callable[[float, float], float],
    max_edge: float,
    surface_breaklines,
    maximum_surface_grade_pct: float | None,
    maximum_chord_residual_m: float | None,
    maximum_iterations: int = 20,
) -> tuple[np.ndarray, np.ndarray, dict]:
    try:
        from triangle import triangulate as triangle_triangulate
    except ImportError as exc:
        raise RuntimeError(
            "Rev.P5 quality road triangulation requires the 'triangle' package"
        ) from exc

    if hasattr(component, "segmentize"):
        component = component.segmentize(float(max_edge))
    base = _polygon_pslg(component, surface_breaklines=surface_breaklines)
    base_vertices = np.asarray(base["vertices"], dtype=float)
    controls = np.empty((0, 2), dtype=float)
    history = []
    maximum_area = max(
        0.20,
        REV_P5_TRIANGLE_MAXIMUM_AREA_FACTOR * float(max_edge) * float(max_edge),
    )
    triangle_args = (
        f"pq{REV_P5_TRIANGLE_MINIMUM_ANGLE_DEG:.0f}a{maximum_area:.8f}"
    )

    for iteration in range(maximum_iterations):
        arguments = {
            "vertices": np.vstack([base_vertices, controls]),
            "segments": np.asarray(base["segments"], dtype=int).copy(),
        }
        if "holes" in base:
            arguments["holes"] = np.asarray(base["holes"], dtype=float).copy()
        result = triangle_triangulate(arguments, triangle_args)
        if "vertices" not in result or "triangles" not in result:
            raise RuntimeError("Triangle PSLG returned no usable road triangulation")
        vertices_2d = np.asarray(result["vertices"], dtype=float)[:, :2]
        faces_2d = np.asarray(result["triangles"], dtype=int)
        metrics = _surface_face_metrics(vertices_2d, faces_2d, z_function)

        bad_chord = np.zeros(len(faces_2d), dtype=bool)
        if maximum_chord_residual_m is not None:
            bad_chord = (
                metrics["chord_residual_m"]
                > float(maximum_chord_residual_m) + 1.0e-9
            )
        bad_grade = np.zeros(len(faces_2d), dtype=bool)
        if maximum_surface_grade_pct is not None:
            bad_grade = (
                metrics["grade_pct"]
                > float(maximum_surface_grade_pct) + 1.0e-7
            )
        bad = bad_chord | bad_grade
        history.append(
            {
                "iteration": int(iteration),
                "control_point_count": int(len(controls)),
                "vertex_count": int(len(vertices_2d)),
                "face_count": int(len(faces_2d)),
                "failing_face_count": int(np.count_nonzero(bad)),
                "failing_face_area_m2": float(np.sum(metrics["plan_area_m2"][bad])),
                "maximum_facet_grade_pct": float(np.max(metrics["grade_pct"])),
                "maximum_chord_residual_m": float(np.max(metrics["chord_residual_m"])),
            }
        )
        if not np.any(bad):
            report = {
                "engine": "Triangle PSLG quality mesh with whole-polygon adaptive control points",
                "triangle_args": triangle_args,
                "maximum_target_edge_m": float(max_edge),
                "maximum_triangle_area_m2": float(maximum_area),
                "minimum_angle_target_deg": REV_P5_TRIANGLE_MINIMUM_ANGLE_DEG,
                "maximum_chord_residual_limit_m": maximum_chord_residual_m,
                "maximum_surface_grade_build_limit_pct": maximum_surface_grade_pct,
                "top_face_count": int(len(faces_2d)),
                "maximum_facet_grade_pct": float(np.max(metrics["grade_pct"])),
                "maximum_chord_residual_m": float(np.max(metrics["chord_residual_m"])),
                "minimum_plan_face_area_m2": float(np.min(metrics["plan_area_m2"])),
                "maximum_plan_aspect_ratio": float(np.max(metrics["aspect_ratio"])),
                "adaptive_control_point_count": int(len(controls)),
                "adaptive_iteration_count": int(iteration + 1),
                "history": history,
                "status": "PASS",
            }
            return vertices_2d, faces_2d, report

        # Use interior centroids as controls.  Edge-midpoint controls can lie
        # exactly on a constrained crown or boundary segment; passing such a
        # point to Triangle without explicitly splitting the segment produces
        # an invalid PSLG.  The centroid always remains inside its source face.
        new_controls = metrics["centroids"][bad]
        existing = {
            tuple(np.round(point, 7))
            for point in np.vstack([base_vertices, controls])
        }
        additions = []
        for point in new_controls:
            key = tuple(np.round(point, 7))
            if key not in existing:
                existing.add(key)
                additions.append(point)
        if not additions:
            raise RuntimeError(
                "Adaptive road triangulation stalled before meeting the strict chord/grade gate"
            )
        controls = np.vstack([controls, np.asarray(additions, dtype=float)])
        if len(controls) > 50_000:
            raise RuntimeError("Adaptive road triangulation exceeded the controlled point budget")

    raise RuntimeError(
        "Adaptive road triangulation did not meet the strict chord/grade gate: "
        + json.dumps(history[-1], ensure_ascii=False)
    )


def _conforming_watertight_solid(
    component: Polygon,
    z_function: Callable[[float, float], float],
    thickness: float,
    max_edge: float,
    surface_breaklines=None,
    maximum_surface_grade_pct: float | None = None,
    maximum_chord_residual_m: float | None = None,
) -> trimesh.Trimesh:
    """Build one watertight solid from a quality, profile-controlled PSLG mesh."""
    if not component.is_valid:
        component = component.buffer(0)
    if component.is_empty or component.area <= 1.0e-8:
        raise RuntimeError("Cannot build a solid from an empty polygon")

    exterior = np.round(np.asarray(component.exterior.coords, dtype=float), 7)
    holes = []
    for ring in component.interiors:
        hole = Polygon(ring)
        if hole.area >= 0.005:
            holes.append(np.round(np.asarray(ring.coords, dtype=float), 7))
    component = Polygon(exterior, holes).buffer(0)
    if component.is_empty or not isinstance(component, Polygon):
        raise RuntimeError("Precision cleanup did not produce one road polygon")

    vertices_2d, top_faces, surface_report = _quality_profile_triangulation(
        component=component,
        z_function=z_function,
        max_edge=float(max_edge),
        surface_breaklines=surface_breaklines,
        maximum_surface_grade_pct=maximum_surface_grade_pct,
        maximum_chord_residual_m=maximum_chord_residual_m,
    )
    signed = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in top_faces],
        dtype=float,
    )
    if np.any(np.abs(signed) <= 1.0e-10):
        raise RuntimeError("Quality road triangulation contains a zero-area face")
    flip = signed < 0.0
    if np.any(flip):
        top_faces = top_faces.copy()
        temporary = top_faces[flip, 1].copy()
        top_faces[flip, 1] = top_faces[flip, 2]
        top_faces[flip, 2] = temporary

    boundary_edges = _oriented_boundary_edges(top_faces)
    if len(boundary_edges) < 3:
        raise RuntimeError("Quality road triangulation contains no polygon boundary")
    top_z = np.asarray(
        [z_function(float(x), float(y)) for x, y in vertices_2d],
        dtype=float,
    )
    top_vertices = np.column_stack([vertices_2d, top_z])
    bottom_vertices = np.column_stack([vertices_2d, top_z - float(thickness)])
    count = len(vertices_2d)
    vertices = np.vstack([top_vertices, bottom_vertices])
    bottom_faces = top_faces[:, ::-1] + count
    side_faces = np.empty((len(boundary_edges) * 2, 3), dtype=int)
    for index, (a, b) in enumerate(boundary_edges):
        a = int(a)
        b = int(b)
        side_faces[2 * index] = [a, a + count, b + count]
        side_faces[2 * index + 1] = [a, b + count, b]
    faces = np.vstack([top_faces, bottom_faces, side_faces])

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    edge_rows = np.sort(np.asarray(mesh.edges, dtype=int), axis=1)
    _, edge_counts = np.unique(edge_rows, axis=0, return_counts=True)
    open_or_nonmanifold = int(np.count_nonzero(edge_counts != 2))
    if open_or_nonmanifold != 0 or not mesh.is_watertight:
        raise RuntimeError(
            "Quality boundary-derived road solid is not watertight: "
            f"open/non-manifold edges={open_or_nonmanifold}"
        )
    if not mesh.is_winding_consistent:
        raise RuntimeError("Quality boundary-derived road solid has inconsistent winding")
    mesh.metadata["revp5_surface_mesh_qa"] = surface_report
    return mesh
'''

text = text[:start] + replacement + text[end:]

solid_start = text.find("def solid_from_polygon(\n")
solid_end = text.find("\ndef polygon_from_mesh_xy", solid_start)
if solid_start < 0 or solid_end < 0:
    raise RuntimeError("Rev.P5 solid_from_polygon block not found")

solid_replacement = r'''def solid_from_polygon(
    geometry,
    z_function: Callable[[float, float], float],
    thickness: float,
    rgba: Sequence[int],
    max_edge: float = MESH_MAX_EDGE,
    surface_breaklines=None,
    maximum_surface_grade_pct: float | None = None,
    maximum_chord_residual_m: float | None = None,
) -> trimesh.Trimesh | None:
    meshes: list[trimesh.Trimesh] = []
    reports = []
    for polygon in iter_polygons(geometry):
        if polygon.area < 1.0e-5:
            continue
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        for component in iter_polygons(polygon):
            if component.area < 1.0e-5:
                continue
            mesh = _conforming_watertight_solid(
                component=component,
                z_function=z_function,
                thickness=thickness,
                max_edge=max_edge,
                surface_breaklines=surface_breaklines,
                maximum_surface_grade_pct=maximum_surface_grade_pct,
                maximum_chord_residual_m=maximum_chord_residual_m,
            )
            reports.append(dict(mesh.metadata["revp5_surface_mesh_qa"]))
            color_mesh(mesh, rgba)
            meshes.append(mesh)
    if not meshes:
        return None
    result = trimesh.util.concatenate(meshes)
    result.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(result, multibody=True)
    result.metadata["revp5_surface_mesh_qa"] = {
        "component_count": len(reports),
        "top_face_count": int(sum(item["top_face_count"] for item in reports)),
        "maximum_facet_grade_pct": float(max(item["maximum_facet_grade_pct"] for item in reports)),
        "maximum_chord_residual_m": float(max(item["maximum_chord_residual_m"] for item in reports)),
        "minimum_plan_face_area_m2": float(min(item["minimum_plan_face_area_m2"] for item in reports)),
        "maximum_plan_aspect_ratio": float(max(item["maximum_plan_aspect_ratio"] for item in reports)),
        "adaptive_control_point_count": int(sum(item["adaptive_control_point_count"] for item in reports)),
        "adaptive_iteration_count": int(max(item["adaptive_iteration_count"] for item in reports)),
        "maximum_chord_residual_limit_m": maximum_chord_residual_m,
        "maximum_surface_grade_build_limit_pct": maximum_surface_grade_pct,
        "components": reports,
        "status": "PASS",
    }
    return result
'''
text = text[:solid_start] + solid_replacement + text[solid_end:]

road_block_old = '''    changed_mesh_names = []
    for code, profile in profiles.items():
        layer_specs = [
            ("SUBBASE", subbase_polys[code], -0.36, 0.55, COLORS["subbase"]),
            ("SHOULDER", shoulder_polys[code], -0.12, 0.30, COLORS["shoulder"]),
            ("ROAD", asphalt_polys[code], 0.0, 0.28, COLORS["road"]),
        ]
        for suffix, polygon, z_offset, thickness, color in layer_specs:
            mesh = solid_from_polygon(
                polygon,
                lambda x, y, p=profile, dz=z_offset, layer=suffix: p.surface_z_for_layer(x, y, layer=layer) + dz,
                thickness,
                color,
                MESH_MAX_EDGE,
            )
            if mesh is None:
                raise RuntimeError(f"Empty {code} {suffix} mesh")
            name = f"REV_P3_EXT_{code}_{suffix}"
            add(target, name, mesh)
            changed_mesh_names.append(name)
'''
road_block_new = '''    changed_mesh_names = []
    road_surface_mesh_qa = {}
    for code, profile in profiles.items():
        layer_specs = [
            ("SUBBASE", subbase_polys[code], -0.36, 0.55, COLORS["subbase"]),
            ("SHOULDER", shoulder_polys[code], -0.12, 0.30, COLORS["shoulder"]),
            ("ROAD", asphalt_polys[code], 0.0, 0.28, COLORS["road"]),
        ]
        for suffix, polygon, z_offset, thickness, color in layer_specs:
            log(f"REV_P5_SURFACE_BUILD_START {code} {suffix}")
            try:
                mesh = solid_from_polygon(
                    polygon,
                    lambda x, y, p=profile, dz=z_offset, layer=suffix: p.surface_z_for_layer(x, y, layer=layer) + dz,
                    thickness,
                    color,
                    MESH_MAX_EDGE,
                    surface_breaklines=profile.lines,
                    maximum_surface_grade_pct=(
                        REV_P5_D5_BUILD_FACET_GRADE_LIMIT_PCT if code == "D5" else None
                    ),
                    maximum_chord_residual_m=REV_P5_ROAD_CHORD_TOLERANCE_M,
                )
            except Exception as exc:
                raise RuntimeError(f"{code} {suffix} quality surface mesh failed: {exc}") from exc
            if mesh is None:
                raise RuntimeError(f"Empty {code} {suffix} mesh")
            name = f"REV_P3_EXT_{code}_{suffix}"
            road_surface_mesh_qa[name] = dict(mesh.metadata["revp5_surface_mesh_qa"])
            add(target, name, mesh)
            changed_mesh_names.append(name)
'''
if road_block_old not in text:
    raise RuntimeError("Rev.P5 road-layer build block not found")
text = text.replace(road_block_old, road_block_new, 1)

qa_anchor = '''        "road_mesh_resolution": {
            "maximum_target_edge_m": MESH_MAX_EDGE,
            "basis": "controlled conforming triangulation; user acceptance specifies removal of erroneous long spikes, not a 3 m tessellation limit",
        },
'''
qa_replacement = qa_anchor + '''        "road_surface_mesh_qa": road_surface_mesh_qa,
'''
if qa_anchor not in text:
    raise RuntimeError("Rev.P5 road QA report anchor not found")
text = text.replace(qa_anchor, qa_replacement, 1)

acceptance_anchor = '''            "d3_d5_protected_sliver_removals": len(d3_d5_junction_geometry["protected_sliver_removals"]),
'''
acceptance_replacement = acceptance_anchor + '''            "road_layer_maximum_chord_residual_m": max(
                item["maximum_chord_residual_m"] for item in road_surface_mesh_qa.values()
            ),
            "road_layer_maximum_chord_residual_limit_m": REV_P5_ROAD_CHORD_TOLERANCE_M,
            "d5_layer_maximum_facet_grade_pct": max(
                item["maximum_facet_grade_pct"]
                for name, item in road_surface_mesh_qa.items()
                if "_D5_" in name
            ),
            "d5_layer_export_facet_grade_limit_pct": REV_P5_D5_EXPORT_FACET_GRADE_LIMIT_PCT,
            "road_layer_quality_triangulation_status": "PASS",
'''
if acceptance_anchor not in text:
    raise RuntimeError("Rev.P5 road acceptance anchor not found")
text = text.replace(acceptance_anchor, acceptance_replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P5_QUALITY_FACET_GRADE_PATCHED")
