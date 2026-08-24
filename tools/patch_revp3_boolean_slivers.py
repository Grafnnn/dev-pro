from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise RuntimeError(f"Patch target not found: {label}")
    text = text.replace(old, new, 1)


# Auditable list: only disconnected components below both an absolute and a
# relative threshold may be discarded. Any second engineering-scale component
# remains in the geometry and is rejected by the subsequent one-component QA.
replace_once(
    "AREA_TOL = 1.0e-6\n",
    "AREA_TOL = 1.0e-6\nBOOLEAN_SLIVER_AUDIT: list[dict] = []\n",
    "boolean sliver audit declaration",
)

old_partition = '''def partition_polygons(profiles: dict[str, RoadProfile], extra_width: float, obstacle_union) -> dict[str, Polygon | MultiPolygon]:
    order = ["D1", "D4", "D2", "D3", "D5", "D6"]
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
'''

new_partition = '''def _clean_boolean_micro_slivers(
    geometry,
    road_code: str,
    extra_width: float,
    absolute_limit_m2: float = 5.0,
    relative_limit: float = 0.002,
):
    polygons = sorted(iter_polygons(geometry), key=lambda polygon: polygon.area, reverse=True)
    if len(polygons) <= 1:
        return geometry
    total_area = float(sum(polygon.area for polygon in polygons))
    primary = polygons[0]
    secondary = polygons[1:]
    secondary_area = float(sum(polygon.area for polygon in secondary))
    largest_secondary = float(max((polygon.area for polygon in secondary), default=0.0))
    if (
        largest_secondary < absolute_limit_m2
        and secondary_area / max(total_area, 1.0e-12) < relative_limit
    ):
        layer = {0.0: "ROAD", 1.5: "SHOULDER", 3.0: "SUBBASE"}.get(float(extra_width), f"EXTRA_{extra_width:g}")
        BOOLEAN_SLIVER_AUDIT.append(
            {
                "road": road_code,
                "layer": layer,
                "discarded_component_count": len(secondary),
                "discarded_area_m2": secondary_area,
                "largest_discarded_component_m2": largest_secondary,
                "retained_primary_area_m2": float(primary.area),
                "discarded_area_fraction": secondary_area / max(total_area, 1.0e-12),
                "reason": "boolean micro-sliver at an intentional road junction",
            }
        )
        return primary.buffer(0)
    return geometry


def partition_polygons(profiles: dict[str, RoadProfile], extra_width: float, obstacle_union) -> dict[str, Polygon | MultiPolygon]:
    order = ["D1", "D4", "D2", "D3", "D5", "D6"]
    occupied = None
    result = {}
    for code in order:
        raw = profiles[code].polygon(WIDTHS[code] + extra_width)
        if occupied is not None:
            raw = raw.difference(occupied)
        if obstacle_union is not None and not obstacle_union.is_empty:
            raw = raw.difference(obstacle_union)
        raw = raw.buffer(0)
        raw = _clean_boolean_micro_slivers(raw, code, extra_width)
        result[code] = raw
        occupied = raw if occupied is None else unary_union([occupied, raw]).buffer(0)
    return result
'''
replace_once(old_partition, new_partition, "partition micro-sliver cleaner")

replace_once(
    '''        "road_building_clashes": [],
        "road_layer_building_clashes": [],''',
    '''        "road_building_clashes": [],
        "road_layer_building_clashes": [],
        "boolean_micro_slivers_removed": BOOLEAN_SLIVER_AUDIT,''',
    "boolean sliver QA report",
)

replace_once(
    '''            "open_external_high_clashes": 0,
            "maximum_layer_building_intersection_m2": 0.0,''',
    '''            "open_external_high_clashes": 0,
            "boolean_micro_sliver_count": int(sum(item["discarded_component_count"] for item in BOOLEAN_SLIVER_AUDIT)),
            "boolean_micro_sliver_area_m2": float(sum(item["discarded_area_m2"] for item in BOOLEAN_SLIVER_AUDIT)),
            "maximum_layer_building_intersection_m2": 0.0,''',
    "boolean sliver acceptance summary",
)

path.write_text(text, encoding="utf-8")
print("REV_P3_BOOLEAN_SLIVER_PATCHED")
