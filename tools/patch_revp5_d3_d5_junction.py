from pathlib import Path


path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"Rev.P5 D3-D5 patch target not found: {label}")
    text = text.replace(old, new, 1)


# D5 starts in the shared D4 node but terminates at the side of continuous D3.
# A round cap at the terminal crosses to the far side of D3 and leaves a small
# disconnected crescent after partitioning. The flat terminal below produces a
# true butt joint; only the D4 entrance retains its round cap.
replace_once(
    '''    def polygon(self, width: float) -> Polygon | MultiPolygon:
        pieces = [line.buffer(width / 2.0, cap_style=1, join_style=1, resolution=12) for line in self.lines]
        return unary_union(pieces).buffer(0)''',
    '''    def polygon(self, width: float) -> Polygon | MultiPolygon:
        radius = float(width) / 2.0
        pieces = []
        for path_index, line in enumerate(self.lines):
            if self.code == "D5" and path_index == len(self.lines) - 1:
                body = line.buffer(radius, cap_style=2, join_style=1, resolution=12)
                start_cap = Point(line.coords[0]).buffer(radius, resolution=12)
                piece = unary_union([body, start_cap]).buffer(0)
            else:
                piece = line.buffer(radius, cap_style=1, join_style=1, resolution=12)
            pieces.append(piece)
        return unary_union(pieces).buffer(0)''',
    "D5 flat terminal cap",
)


# The prior check compared only both centreline elevations at the nominal
# node.  The actual butt seams occur 2.4...4.6 m before that node and showed
# up to 150 mm mismatch across ROAD/SHOULDER/SUBBASE.  D3 remains the
# controlling continuous road.  D5 is tied to the D3 design surface on a
# layer-specific terminal plateau and returns to its independent profile
# through a short 6 m cubic smoothstep.  Separate plateau lengths are required
# because the three butt seams occur at different stations.  A single long
# blend removed the steps but introduced a local drainage sag; it is therefore
# explicitly prohibited by the QA below.
replace_once(
    '''    def surface_z(self, x: float, y: float, crown: float = 0.045, crossfall: float = 0.02) -> float:
        _, _, distance = self.nearest(x, y)
        return self.center_z(x, y) + crown - crossfall * distance''',
    '''    def surface_z_for_layer(
        self,
        x: float,
        y: float,
        layer: str = "ROAD",
        crown: float = 0.045,
        crossfall: float = 0.02,
    ) -> float:
        path_index, station, distance = self.nearest(x, y)
        base = self.center_z(x, y) + crown - crossfall * distance
        match_profile = getattr(self, "revp5_vertical_match_profile", None)
        if self.code != "D5" or match_profile is None or path_index != len(self.lines) - 1:
            return float(base)
        settings = getattr(self, "revp5_vertical_match_by_layer", {})
        if layer not in settings:
            raise RuntimeError(f"Unsupported D3-D5 vertical-match layer: {layer}")
        full_match_m = float(settings[layer]["full_match_m"])
        transition_m = float(settings[layer]["transition_m"])
        remaining = max(0.0, float(self.lines[path_index].length - station))
        outer = full_match_m + transition_m
        if remaining >= outer:
            return float(base)
        target = float(
            match_profile.surface_z_for_layer(
                float(x), float(y), layer=layer, crown=crown, crossfall=crossfall
            )
        )
        if remaining <= full_match_m:
            return target
        t = (remaining - full_match_m) / transition_m
        weight = 1.0 - 3.0 * t * t + 2.0 * t * t * t
        return float(base + weight * (target - base))

    def surface_z(self, x: float, y: float, crown: float = 0.045, crossfall: float = 0.02) -> float:
        return self.surface_z_for_layer(
            x, y, layer="ROAD", crown=crown, crossfall=crossfall
        )''',
    "D5 C1 vertical surface blend",
)


profile_helper_anchor = '''def iter_polygons(geometry) -> Iterable[Polygon]:
'''
profile_helper = '''def coordinate_revp5_d3_d5_profiles(profiles: dict[str, RoadProfile]) -> None:
    required = {"D3", "D5"}
    if not required.issubset(profiles):
        raise RuntimeError("D3/D5 profiles are required for junction vertical coordination")
    d5 = profiles["D5"]
    d5.revp5_vertical_match_profile = profiles["D3"]
    d5.revp5_vertical_match_by_layer = {
        "ROAD": {"full_match_m": 3.35, "transition_m": 6.0},
        "SHOULDER": {"full_match_m": 4.10, "transition_m": 6.0},
        "SUBBASE": {"full_match_m": 4.85, "transition_m": 6.0},
    }
    if len(d5.paths) != 1 or len(d5.lines) != 1:
        raise RuntimeError("Controlled D5 vertical regrade requires one continuous path")

    # The old generic easing reached the terminal elevation too early. Any
    # local tie down to the D3 crossfall then created a drainage sag. Regrade
    # D5 with a non-negative C1 grade distribution: zero grade at D4, a mild
    # long approach, a 6 m transition and a terminal tangent parallel to D3.
    line = d5.lines[0]
    station_values = np.asarray(d5.stations[0], dtype=float)
    length = float(line.length)
    terminal_length = max(
        float(value["full_match_m"] + value["transition_m"])
        for value in d5.revp5_vertical_match_by_layer.values()
    )
    terminal_grade_transition = 6.0
    start_grade_transition = 10.0
    if length <= terminal_length + terminal_grade_transition + start_grade_transition + 1.0:
        raise RuntimeError("D5 path is too short for the controlled C1 vertical regrade")

    endpoint = line.interpolate(length)
    before_endpoint = line.interpolate(length - 1.0)
    endpoint_target = profiles["D3"].surface_z(endpoint.x, endpoint.y)
    before_target = profiles["D3"].surface_z(before_endpoint.x, before_endpoint.y)
    terminal_grade = float(endpoint_target - before_target)
    if not (0.0 < terminal_grade <= MAX_GRADE):
        raise RuntimeError(
            f"D3 target grade along the D5 terminal is invalid: {100.0 * terminal_grade:.6f}%"
        )

    z_start = float(d5.paths[0][0, 2])
    z_end = float(d5.paths[0][-1, 2])
    total_rise = z_end - z_start
    long_length = length - start_grade_transition - terminal_grade_transition - terminal_length
    long_grade_coefficient = (
        0.5 * start_grade_transition + long_length + 0.5 * terminal_grade_transition
    )
    terminal_rise = terminal_grade * (0.5 * terminal_grade_transition + terminal_length)
    long_grade = float((total_rise - terminal_rise) / long_grade_coefficient)
    if not (0.0 <= long_grade <= terminal_grade <= MAX_GRADE):
        raise RuntimeError(
            "D5 C1 regrade is not monotone: "
            f"long={100.0 * long_grade:.6f}%; terminal={100.0 * terminal_grade:.6f}%"
        )

    first_break = start_grade_transition
    second_break = first_break + long_length
    third_break = second_break + terminal_grade_transition
    rise_at_first = 0.5 * start_grade_transition * long_grade
    rise_at_second = rise_at_first + long_length * long_grade
    rise_at_third = rise_at_second + 0.5 * terminal_grade_transition * (long_grade + terminal_grade)
    elevations = np.empty_like(station_values)
    for index, station in enumerate(station_values):
        station = float(station)
        if station <= first_break:
            rise = 0.5 * long_grade * station * station / start_grade_transition
        elif station <= second_break:
            rise = rise_at_first + long_grade * (station - first_break)
        elif station <= third_break:
            u = station - second_break
            rise = (
                rise_at_second
                + long_grade * u
                + 0.5 * (terminal_grade - long_grade) * u * u / terminal_grade_transition
            )
        else:
            rise = rise_at_third + terminal_grade * (station - third_break)
        elevations[index] = z_start + rise
    elevations[-1] = z_end
    if np.any(np.diff(elevations) < -1.0e-9):
        raise RuntimeError("D5 C1 regrade generated a reverse-grade segment")
    d5.paths[0][:, 2] = elevations
    d5.revp5_vertical_regrade = {
        "method": "C1_NONNEGATIVE_GRADE_DISTRIBUTION_MATCHED_TO_D3_CROSSFALL",
        "start_grade_transition_m": start_grade_transition,
        "long_approach_length_m": long_length,
        "terminal_grade_transition_m": terminal_grade_transition,
        "terminal_tangent_length_m": terminal_length,
        "long_approach_grade_pct": 100.0 * long_grade,
        "terminal_grade_pct": 100.0 * terminal_grade,
        "start_elevation_m": z_start,
        "end_elevation_m": z_end,
    }


''' + profile_helper_anchor
replace_once(profile_helper_anchor, profile_helper, "D3-D5 vertical profile coordinator")


helper_anchor = '''def subdivide_mesh(mesh: trimesh.Trimesh, max_edge: float = MESH_MAX_EDGE) -> trimesh.Trimesh:
'''
helper = '''def revp5_d3_d5_junction_qa(
    profiles: dict[str, RoadProfile],
    layer_polys: dict[str, dict[str, Polygon | MultiPolygon]],
    sliver_audit: list[dict] | None = None,
) -> dict:
    node = Point(557.0394602011489, 150.0)
    d3_line = profiles["D3"].lines[0]
    d5_line = profiles["D5"].lines[-1]
    centerline_intersection = d3_line.intersection(d5_line)
    if centerline_intersection.geom_type != "Point" or centerline_intersection.distance(node) > 1.0e-4:
        raise RuntimeError(
            "D3-D5 must have one point centreline intersection at the controlled node: "
            + centerline_intersection.wkt
        )
    if centerline_intersection.length > 1.0e-6:
        raise RuntimeError("D3-D5 centreline overlap remains")
    if Point(d5_line.coords[-1]).distance(node) > 1.0e-4:
        raise RuntimeError("D5 does not terminate at the controlled D3 node")

    d3_station = float(d3_line.project(node))
    sample = min(1.0, 0.25 * d3_line.length)
    d3_before = d3_line.interpolate(max(0.0, d3_station - sample))
    d3_after = d3_line.interpolate(min(d3_line.length, d3_station + sample))
    d5_before = d5_line.interpolate(max(0.0, d5_line.length - sample))
    d5_end = d5_line.interpolate(d5_line.length)
    d3_heading = math.atan2(d3_after.y - d3_before.y, d3_after.x - d3_before.x)
    d5_heading = math.atan2(d5_end.y - d5_before.y, d5_end.x - d5_before.x)
    angle = abs(math.degrees(d5_heading - d3_heading)) % 180.0
    acute_angle = min(angle, 180.0 - angle)
    if acute_angle < 75.0:
        raise RuntimeError(f"D3-D5 approach angle {acute_angle:.3f} deg is not transverse")

    layer_extra = {"ROAD": 0.0, "SHOULDER": 1.5, "SUBBASE": 3.0}
    overlap_limits = {"ROAD": 25.0, "SHOULDER": 36.0, "SUBBASE": 50.0}
    layers = {}
    for layer, extra_width in layer_extra.items():
        d3_raw = profiles["D3"].polygon(WIDTHS["D3"] + extra_width)
        d5_raw = profiles["D5"].polygon(WIDTHS["D5"] + extra_width)
        raw_overlap = d3_raw.intersection(d5_raw)
        raw_overlap_area = float(raw_overlap.area)
        outside_node_area = float(raw_overlap.difference(node.buffer(8.0)).area)
        d3_final = layer_polys[layer]["D3"]
        d5_final = layer_polys[layer]["D5"]
        d3_components = len(list(iter_polygons(d3_final)))
        d5_components = len(list(iter_polygons(d5_final)))
        final_overlap = float(d3_final.intersection(d5_final).area)
        gap = float(d3_final.distance(d5_final))
        seam_length = float(d3_final.boundary.intersection(d5_final.boundary).length)
        seam = d3_final.boundary.intersection(d5_final.boundary)
        seam_parts = list(getattr(seam, "geoms", [seam]))
        seam_steps = []
        seam_remaining = []
        layer_offset = {"ROAD": 0.0, "SHOULDER": -0.12, "SUBBASE": -0.36}[layer]
        for part in seam_parts:
            if part.is_empty or float(getattr(part, "length", 0.0)) <= 0.0:
                continue
            count = max(3, int(math.ceil(float(part.length) / 0.10)) + 1)
            for station in np.linspace(0.0, float(part.length), count):
                point = part.interpolate(float(station))
                d3_z = profiles["D3"].surface_z_for_layer(point.x, point.y, layer=layer) + layer_offset
                d5_z = profiles["D5"].surface_z_for_layer(point.x, point.y, layer=layer) + layer_offset
                seam_steps.append(abs(float(d3_z - d5_z)))
                d5_station = float(d5_line.project(point))
                seam_remaining.append(max(0.0, float(d5_line.length - d5_station)))
        maximum_seam_step = float(max(seam_steps, default=math.inf))
        maximum_seam_remaining = float(max(seam_remaining, default=math.inf))
        d3_local_loss = float(d3_raw.intersection(node.buffer(8.0)).difference(d3_final).area)
        effective_d5_width = WIDTHS["D5"] + extra_width
        if not (0.0 < raw_overlap_area <= overlap_limits[layer]):
            raise RuntimeError(f"D3-D5 {layer} raw overlap {raw_overlap_area:.6f} m2 is outside the controlled T-node limit")
        if outside_node_area > AREA_TOL:
            raise RuntimeError(f"D3-D5 {layer} raw overlap escapes the 8 m junction node by {outside_node_area:.9f} m2")
        if d3_components != 1 or d5_components != 1:
            raise RuntimeError(f"D3-D5 {layer} disconnected: D3={d3_components}, D5={d5_components}")
        if d3_local_loss > AREA_TOL:
            raise RuntimeError(f"D3-D5 {layer} partition removed {d3_local_loss:.9f} m2 from continuous D3")
        if final_overlap > AREA_TOL or gap > ROAD_GAP_LIMIT:
            raise RuntimeError(f"D3-D5 {layer} final overlap={final_overlap:.9f} gap={gap:.6f}")
        if not (0.90 * effective_d5_width <= seam_length <= 1.15 * effective_d5_width):
            raise RuntimeError(f"D3-D5 {layer} butt seam {seam_length:.6f} m is not a full-width connection")
        match_settings = getattr(profiles["D5"], "revp5_vertical_match_by_layer", {})
        full_match_m = float(match_settings.get(layer, {}).get("full_match_m", 0.0))
        if maximum_seam_remaining > full_match_m - 0.25:
            raise RuntimeError(
                f"D3-D5 {layer} seam escapes the vertical-match plateau: "
                f"remaining={maximum_seam_remaining:.6f} m; plateau={full_match_m:.6f} m"
            )
        if maximum_seam_step > 0.005001:
            raise RuntimeError(
                f"D3-D5 {layer} full-seam vertical step {maximum_seam_step:.6f} m exceeds 5 mm"
            )
        layers[layer] = {
            "effective_d3_width_m": float(WIDTHS["D3"] + extra_width),
            "effective_d5_width_m": float(effective_d5_width),
            "raw_overlap_m2": raw_overlap_area,
            "raw_overlap_outside_8m_node_m2": outside_node_area,
            "final_overlap_m2": final_overlap,
            "gap_m": gap,
            "common_boundary_seam_m": seam_length,
            "maximum_full_seam_vertical_step_m": maximum_seam_step,
            "maximum_seam_remaining_to_d5_node_m": maximum_seam_remaining,
            "d3_connected_components": d3_components,
            "d5_connected_components": d5_components,
            "d3_local_partition_loss_m2": d3_local_loss,
            "status": "PASS",
        }

    protected_slivers = [
        item for item in (sliver_audit or [])
        if item.get("road") in {"D3", "D5"}
    ]
    if protected_slivers:
        raise RuntimeError("D3/D5 geometry was hidden by sliver cleanup: " + json.dumps(protected_slivers, ensure_ascii=False))
    d5_stations = np.linspace(
        0.0,
        float(d5_line.length),
        max(3, int(math.ceil(d5_line.length / 0.05)) + 1),
    )
    d5_grade_by_layer = {}
    d5_min_signed_grade_by_layer = {}
    d5_interior_sag_count_by_layer = {}
    for layer in layer_extra:
        elevations = []
        for station in d5_stations:
            point = d5_line.interpolate(float(station))
            elevations.append(
                profiles["D5"].surface_z_for_layer(point.x, point.y, layer=layer)
            )
        signed_grades = np.diff(np.asarray(elevations, dtype=float)) / np.diff(d5_stations)
        d5_grade_by_layer[layer] = float(100.0 * max(np.abs(signed_grades), default=math.inf))
        d5_min_signed_grade_by_layer[layer] = float(100.0 * min(signed_grades, default=-math.inf))
        sag_count = int(np.count_nonzero(signed_grades < -1.0e-7))
        d5_interior_sag_count_by_layer[layer] = sag_count
        if d5_grade_by_layer[layer] > 6.000001:
            raise RuntimeError(
                f"D5 blended {layer} centreline grade "
                f"{d5_grade_by_layer[layer]:.6f}% exceeds 6%"
            )
        if sag_count != 0:
            raise RuntimeError(
                f"D5 blended {layer} profile contains {sag_count} reverse-grade samples"
            )
    d5_blended_max_grade = float(max(d5_grade_by_layer.values()))

    # The layer-specific blends must remain a nested pavement package.  Sample
    # the whole terminal tie over the full subbase width and prove that the
    # intentionally overlapping road/shoulder/subbase solids retain positive,
    # bounded vertical engagement with no inverted top order.  Also check the
    # resultant (longitudinal + 2% crossfall) surface gradient for every layer.
    match_settings = profiles["D5"].revp5_vertical_match_by_layer
    maximum_tie_length = max(
        float(value["full_match_m"] + value["transition_m"])
        for value in match_settings.values()
    )
    tie_remaining = np.linspace(0.0, maximum_tie_length, 214)
    maximum_half_width = (WIDTHS["D5"] + max(layer_extra.values())) / 2.0
    lateral_offsets = np.linspace(-maximum_half_width, maximum_half_width, 101)
    road_shoulder_overlaps = []
    shoulder_subbase_overlaps = []
    road_over_shoulder_top = []
    shoulder_over_subbase_top = []
    surface_divergences = []
    resultant_grades_by_layer = {layer: [] for layer in layer_extra}
    gradient_step_m = 0.02
    for remaining in tie_remaining:
        station = max(0.0, float(d5_line.length - remaining))
        centre = d5_line.interpolate(station)
        before = d5_line.interpolate(max(0.0, station - 0.05))
        after = d5_line.interpolate(min(float(d5_line.length), station + 0.05))
        tangent = np.asarray([after.x - before.x, after.y - before.y], dtype=float)
        tangent /= max(float(np.linalg.norm(tangent)), 1.0e-12)
        normal = np.asarray([-tangent[1], tangent[0]], dtype=float)
        for lateral in lateral_offsets:
            x = float(centre.x + lateral * normal[0])
            y = float(centre.y + lateral * normal[1])
            road_surface = profiles["D5"].surface_z_for_layer(x, y, layer="ROAD")
            shoulder_surface = profiles["D5"].surface_z_for_layer(x, y, layer="SHOULDER")
            subbase_surface = profiles["D5"].surface_z_for_layer(x, y, layer="SUBBASE")
            if abs(float(lateral)) <= WIDTHS["D5"] / 2.0 + 1.0e-9:
                road_bottom = road_surface - 0.28
                shoulder_top = shoulder_surface - 0.12
                road_shoulder_overlaps.append(shoulder_top - road_bottom)
                road_over_shoulder_top.append(road_surface - shoulder_top)
                surface_divergences.append(abs(road_surface - shoulder_surface))
            if abs(float(lateral)) <= (WIDTHS["D5"] + 1.5) / 2.0 + 1.0e-9:
                shoulder_top = shoulder_surface - 0.12
                shoulder_bottom = shoulder_surface - 0.12 - 0.30
                subbase_top = subbase_surface - 0.36
                shoulder_subbase_overlaps.append(subbase_top - shoulder_bottom)
                shoulder_over_subbase_top.append(shoulder_top - subbase_top)
                surface_divergences.append(abs(shoulder_surface - subbase_surface))
            for layer, extra_width in layer_extra.items():
                if abs(float(lateral)) > (WIDTHS["D5"] + extra_width) / 2.0 + 1.0e-9:
                    continue
                dz_dx = (
                    profiles["D5"].surface_z_for_layer(x + gradient_step_m, y, layer=layer)
                    - profiles["D5"].surface_z_for_layer(x - gradient_step_m, y, layer=layer)
                ) / (2.0 * gradient_step_m)
                dz_dy = (
                    profiles["D5"].surface_z_for_layer(x, y + gradient_step_m, layer=layer)
                    - profiles["D5"].surface_z_for_layer(x, y - gradient_step_m, layer=layer)
                ) / (2.0 * gradient_step_m)
                resultant_grades_by_layer[layer].append(100.0 * math.hypot(dz_dx, dz_dy))
    minimum_road_shoulder_overlap = float(min(road_shoulder_overlaps, default=-math.inf))
    maximum_road_shoulder_overlap = float(max(road_shoulder_overlaps, default=math.inf))
    minimum_shoulder_subbase_overlap = float(min(shoulder_subbase_overlaps, default=-math.inf))
    maximum_shoulder_subbase_overlap = float(max(shoulder_subbase_overlaps, default=math.inf))
    minimum_road_over_shoulder_top = float(min(road_over_shoulder_top, default=-math.inf))
    minimum_shoulder_over_subbase_top = float(min(shoulder_over_subbase_top, default=-math.inf))
    maximum_surface_divergence = float(max(surface_divergences, default=math.inf))
    maximum_resultant_grade_by_layer = {
        layer: float(max(values, default=math.inf))
        for layer, values in resultant_grades_by_layer.items()
    }
    maximum_resultant_grade = float(max(maximum_resultant_grade_by_layer.values()))
    resultant_grade_limit = float(100.0 * math.hypot(MAX_GRADE, 0.02))
    if minimum_road_shoulder_overlap <= 0.005:
        raise RuntimeError(
            "D3-D5 ROAD/SHOULDER layer nesting gap: "
            f"minimum overlap={minimum_road_shoulder_overlap:.6f} m"
        )
    if minimum_shoulder_subbase_overlap <= 0.005:
        raise RuntimeError(
            "D3-D5 SHOULDER/SUBBASE layer nesting gap: "
            f"minimum overlap={minimum_shoulder_subbase_overlap:.6f} m"
        )
    if maximum_road_shoulder_overlap > 0.25:
        raise RuntimeError(
            "D3-D5 ROAD/SHOULDER layer engagement is excessive: "
            f"maximum overlap={maximum_road_shoulder_overlap:.6f} m"
        )
    if maximum_shoulder_subbase_overlap > 0.12:
        raise RuntimeError(
            "D3-D5 SHOULDER/SUBBASE layer engagement is excessive: "
            f"maximum overlap={maximum_shoulder_subbase_overlap:.6f} m"
        )
    if minimum_road_over_shoulder_top <= 0.0 or minimum_shoulder_over_subbase_top <= 0.0:
        raise RuntimeError(
            "D3-D5 pavement layer top order is inverted: "
            f"road/shoulder={minimum_road_over_shoulder_top:.6f} m; "
            f"shoulder/subbase={minimum_shoulder_over_subbase_top:.6f} m"
        )
    if maximum_resultant_grade > resultant_grade_limit + 1.0e-6:
        raise RuntimeError(
            "D3-D5 D5 resultant surface grade exceeds the 6% longitudinal + 2% crossfall envelope: "
            f"maximum={maximum_resultant_grade:.6f}%; limit={resultant_grade_limit:.6f}%"
        )
    vertical_step = abs(profiles["D3"].surface_z(node.x, node.y) - profiles["D5"].surface_z(node.x, node.y))
    if vertical_step > VERTICAL_STEP_LIMIT:
        raise RuntimeError(f"D3-D5 vertical step {vertical_step:.6f} m exceeds tolerance")
    return {
        "node_xy": [node.x, node.y],
        "centreline_intersection_type": centerline_intersection.geom_type,
        "centreline_overlap_length_m": float(centerline_intersection.length),
        "approach_angle_deg": float(acute_angle),
        "vertical_step_m": float(vertical_step),
        "maximum_full_seam_vertical_step_m": float(
            max(item["maximum_full_seam_vertical_step_m"] for item in layers.values())
        ),
        "d5_blended_maximum_centerline_grade_pct": d5_blended_max_grade,
        "d5_blended_maximum_centerline_grade_pct_by_layer": d5_grade_by_layer,
        "d5_blended_minimum_signed_centerline_grade_pct_by_layer": d5_min_signed_grade_by_layer,
        "d5_blended_reverse_grade_sample_count_by_layer": d5_interior_sag_count_by_layer,
        "d5_maximum_resultant_surface_grade_pct": maximum_resultant_grade,
        "d5_maximum_resultant_surface_grade_pct_by_layer": maximum_resultant_grade_by_layer,
        "d5_resultant_surface_grade_limit_pct": resultant_grade_limit,
        "layer_nesting": {
            "minimum_road_shoulder_vertical_overlap_m": minimum_road_shoulder_overlap,
            "maximum_road_shoulder_vertical_overlap_m": maximum_road_shoulder_overlap,
            "minimum_shoulder_subbase_vertical_overlap_m": minimum_shoulder_subbase_overlap,
            "maximum_shoulder_subbase_vertical_overlap_m": maximum_shoulder_subbase_overlap,
            "minimum_road_surface_above_shoulder_top_m": minimum_road_over_shoulder_top,
            "minimum_shoulder_top_above_subbase_top_m": minimum_shoulder_over_subbase_top,
            "maximum_interlayer_design_surface_divergence_m": maximum_surface_divergence,
            "sample_spacing_longitudinal_m": maximum_tie_length / max(len(tie_remaining) - 1, 1),
            "sample_spacing_lateral_m": 2.0 * maximum_half_width / max(len(lateral_offsets) - 1, 1),
            "sample_count": len(tie_remaining) * len(lateral_offsets),
            "road_shoulder_sample_count": len(road_shoulder_overlaps),
            "shoulder_subbase_sample_count": len(shoulder_subbase_overlaps),
            "resultant_surface_grade_sample_count_by_layer": {
                layer: len(values) for layer, values in resultant_grades_by_layer.items()
            },
            "status": "PASS",
        },
        "vertical_match": {
            "controlling_profile": "D3",
            "matched_profile": "D5",
            "by_layer": match_settings,
            "full_seam_limit_m": 0.005,
            "reverse_grade_sample_limit": 0,
            "d5_centreline_regrade": profiles["D5"].revp5_vertical_regrade,
        },
        "partition_priority": "D3_CONTINUOUS__D5_BUTT_JOINT",
        "protected_sliver_removals": protected_slivers,
        "layers": layers,
        "status": "PASS",
    }


''' + helper_anchor
replace_once(helper_anchor, helper, "junction QA helper")


replace_once(
    '''    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    terrain_cut_corridor =''',
    '''    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    d3_d5_junction_geometry = revp5_d3_d5_junction_qa(
        profiles,
        {"ROAD": asphalt_polys, "SHOULDER": shoulder_polys, "SUBBASE": subbase_polys},
        globals().get("BOOLEAN_SLIVER_AUDIT", []),
    )

    terrain_cut_corridor =''',
    "junction QA call",
)

replace_once(
    '''        "junctions": junction_qa,
        "service_aprons": apron_qa,''',
    '''        "junctions": junction_qa,
        "d3_d5_junction_geometry": d3_d5_junction_geometry,
        "service_aprons": apron_qa,''',
    "junction QA report",
)

replace_once(
    '''    profiles = {code: RoadProfile(code=code, width=WIDTHS[code], paths=road_paths) for code, road_paths in paths.items()}

    foundation_polys = {}''',
    '''    profiles = {code: RoadProfile(code=code, width=WIDTHS[code], paths=road_paths) for code, road_paths in paths.items()}
    coordinate_revp5_d3_d5_profiles(profiles)

    foundation_polys = {}''',
    "activate D3-D5 vertical coordination",
)

replace_once(
    '''                lambda x, y, p=profile, dz=z_offset: p.surface_z(x, y) + dz,''',
    '''                lambda x, y, p=profile, dz=z_offset, layer=suffix: p.surface_z_for_layer(x, y, layer=layer) + dz,''',
    "use layer-specific D3-D5 vertical ties for pavement solids",
)

replace_once(
    '''            "maximum_junction_vertical_step_m": max((item["vertical_step_m"] for item in junction_qa), default=0.0),
            "maximum_road_apron_vertical_step_m": max_seam_step,''',
    '''            "maximum_junction_vertical_step_m": max((item["vertical_step_m"] for item in junction_qa), default=0.0),
            "d3_d5_junction_status": d3_d5_junction_geometry["status"],
            "d3_d5_road_raw_overlap_m2": d3_d5_junction_geometry["layers"]["ROAD"]["raw_overlap_m2"],
            "d3_d5_road_final_overlap_m2": d3_d5_junction_geometry["layers"]["ROAD"]["final_overlap_m2"],
            "d3_d5_maximum_full_seam_vertical_step_m": d3_d5_junction_geometry["maximum_full_seam_vertical_step_m"],
            "d3_d5_blended_maximum_centerline_grade_pct": d3_d5_junction_geometry["d5_blended_maximum_centerline_grade_pct"],
            "d3_d5_maximum_resultant_surface_grade_pct": d3_d5_junction_geometry["d5_maximum_resultant_surface_grade_pct"],
            "d3_d5_minimum_road_shoulder_vertical_overlap_m": d3_d5_junction_geometry["layer_nesting"]["minimum_road_shoulder_vertical_overlap_m"],
            "d3_d5_maximum_road_shoulder_vertical_overlap_m": d3_d5_junction_geometry["layer_nesting"]["maximum_road_shoulder_vertical_overlap_m"],
            "d3_d5_minimum_shoulder_subbase_vertical_overlap_m": d3_d5_junction_geometry["layer_nesting"]["minimum_shoulder_subbase_vertical_overlap_m"],
            "d3_d5_maximum_shoulder_subbase_vertical_overlap_m": d3_d5_junction_geometry["layer_nesting"]["maximum_shoulder_subbase_vertical_overlap_m"],
            "d3_d5_reverse_grade_sample_count": sum(d3_d5_junction_geometry["d5_blended_reverse_grade_sample_count_by_layer"].values()),
            "d3_d5_protected_sliver_removals": len(d3_d5_junction_geometry["protected_sliver_removals"]),
            "maximum_road_apron_vertical_step_m": max_seam_step,''',
    "junction acceptance summary",
)

path.write_text(text, encoding="utf-8")
print("REV_P5_D3_D5_ENGINEERED_BUTT_JUNCTION_PATCHED")
