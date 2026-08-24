from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''        road_seam_z = point_z_from_profiles(profiles, end.x, end.y)
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
'''

new = '''        road_seam_z = point_z_from_profiles(profiles, end.x, end.y)
        connector_length = max(connector_line.length, 1.0e-6)

        # Grade the complete apron, not only the narrow connector polygon.
        # At every fixed deck boundary point the apron equals deck_top; at
        # every road-boundary point it equals the exact nearest road surface.
        # Distance-weighted smooth interpolation prevents vertical steps and
        # removes coplanar road/apron overlap without moving the building.
        def make_z_function(
            deck_geometry=deck,
            road_geometry=asphalt_union,
            z0=deck_top,
        ):
            deck_boundary = deck_geometry.boundary
            road_boundary = road_geometry.boundary

            def z_function(x: float, y: float) -> float:
                point = Point(float(x), float(y))
                deck_distance = float(point.distance(deck_boundary))
                road_distance = float(point.distance(road_boundary))
                road_z = point_z_from_profiles(profiles, float(x), float(y))
                if deck_distance <= 1.0e-6:
                    return float(z0)
                if road_distance <= 1.0e-6:
                    return float(road_z)
                denominator = deck_distance + road_distance
                if denominator <= 1.0e-9:
                    return float(road_z)
                t = max(0.0, min(1.0, deck_distance / denominator))
                smooth = t * t * (3.0 - 2.0 * t)
                return float(z0 + (road_z - z0) * smooth)

            return z_function
'''

if old not in text:
    raise RuntimeError("Rev.P3 service-apron grading block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("REV_P3_APRON_GRADING_PATCHED")
