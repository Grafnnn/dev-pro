from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''        def make_z_function(
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

            return z_function'''

new = '''        def make_z_function(
            deck_geom=deck,
            road_geom=asphalt_union,
            z0=deck_top,
            profiles_ref=profiles,
        ):
            # Blend every apron point between the immutable foundation-deck
            # elevation and the nearest road surface using boundary distances.
            # This guarantees an exact common-Z seam at road/apron boundaries,
            # even when the apron touches a road along more than the original
            # shortest connector line.  It removes the 1.585 m BLD_02 seam jump
            # found by the first Rev.P3 numerical QA pass.
            def z_function(x: float, y: float) -> float:
                point = Point(float(x), float(y))
                distance_to_deck = float(point.distance(deck_geom))
                distance_to_road = float(point.distance(road_geom))
                road_z = point_z_from_profiles(profiles_ref, x, y)
                if distance_to_road <= 1.0e-7:
                    return float(road_z)
                if distance_to_deck <= 1.0e-7:
                    return float(z0)
                ratio = distance_to_deck / max(distance_to_deck + distance_to_road, 1.0e-9)
                ratio = max(0.0, min(1.0, ratio))
                smooth = ratio * ratio * (3.0 - 2.0 * ratio)
                return float(z0 + (road_z - z0) * smooth)

            return z_function'''

if old not in text:
    raise RuntimeError("Rev.P3 apron blend patch target not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("REV_P3_APRON_BLEND_PATCHED")
