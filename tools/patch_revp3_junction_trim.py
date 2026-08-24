from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

anchor = '''    shoulder_polys = partition_polygons(profiles, 1.5, building_obstacles)
    subbase_polys = partition_polygons(profiles, 3.0, building_obstacles)
    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    # Intentional road-road junctions; roadside curbs/rails stop here.'''

replacement = '''    shoulder_polys = partition_polygons(profiles, 1.5, building_obstacles)
    subbase_polys = partition_polygons(profiles, 3.0, building_obstacles)
    shoulder_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in shoulder_polys.items()}
    subbase_polys = {code: polygon.difference(apron_union).buffer(0) for code, polygon in subbase_polys.items()}

    # Boolean partitioning at a shared road junction can leave a tiny cap on
    # the far side of the higher-priority carriageway.  Such a cap is not a
    # meaningful road segment: keeping it would violate the connected-contour
    # criterion and create the very triangular/z-fighting artifacts Rev.P3 is
    # intended to remove.  Retain the primary connected component only when
    # every discarded component is small and located inside an explicit
    # junction control zone.  Any other disconnection remains a hard failure.
    junction_trim_report = []
    junction_control_zones = {
        "D1": unary_union([Point(245.0, 310.0).buffer(18.0)]),
        "D2": unary_union([Point(245.0, 310.0).buffer(18.0), Point(439.0, 345.0).buffer(18.0)]),
        "D3": unary_union([Point(439.0, 345.0).buffer(18.0)]),
        "D4": unary_union([Point(338.0, 128.0).buffer(22.0)]),
        "D5": unary_union([Point(338.0, 128.0).buffer(22.0)]),
        "D6": unary_union([Point(338.0, 128.0).buffer(22.0)]),
    }

    def retain_primary_junction_component(layer_name: str, code: str, geometry):
        components = sorted(list(iter_polygons(geometry)), key=lambda item: item.area, reverse=True)
        if len(components) <= 1:
            return geometry.buffer(0)
        primary = components[0]
        discarded = components[1:]
        zone = junction_control_zones[code]
        discarded_area = float(sum(item.area for item in discarded))
        largest_discarded_area = float(max(item.area for item in discarded))
        outside = [item for item in discarded if not zone.intersects(item)]
        if outside or discarded_area > 180.0 or largest_discarded_area > 120.0:
            raise RuntimeError(
                f"Unexpected disconnected {layer_name}/{code}: "
                f"components={len(components)}, discarded_area={discarded_area:.3f}, "
                f"outside_junction={len(outside)}"
            )
        junction_trim_report.append(
            {
                "layer": layer_name,
                "road": code,
                "components_before": len(components),
                "components_after": 1,
                "discarded_components": len(discarded),
                "discarded_area_m2": discarded_area,
                "largest_discarded_area_m2": largest_discarded_area,
                "reason": "intentional shared-junction boolean trim; primary road contour retained",
                "status": "PASS",
            }
        )
        return primary.buffer(0)

    asphalt_polys = {
        code: retain_primary_junction_component("ROAD", code, polygon)
        for code, polygon in asphalt_polys.items()
    }
    shoulder_polys = {
        code: retain_primary_junction_component("SHOULDER", code, polygon)
        for code, polygon in shoulder_polys.items()
    }
    subbase_polys = {
        code: retain_primary_junction_component("SUBBASE", code, polygon)
        for code, polygon in subbase_polys.items()
    }
    asphalt_union = unary_union(list(asphalt_polys.values())).buffer(0)

    # Intentional road-road junctions; roadside curbs/rails stop here.'''

if anchor not in text:
    raise RuntimeError("Rev.P3 junction-trim insertion anchor not found")
text = text.replace(anchor, replacement, 1)

qa_anchor = '''        "wall_and_railing_adjustments": wall_filter_report,
        "mesh_quality": changed_quality,'''
qa_replacement = '''        "wall_and_railing_adjustments": wall_filter_report,
        "intentional_junction_trims": junction_trim_report,
        "mesh_quality": changed_quality,'''
if qa_anchor not in text:
    raise RuntimeError("Rev.P3 junction-trim QA anchor not found")
text = text.replace(qa_anchor, qa_replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_JUNCTION_TRIM_PATCHED")
