from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

old = '''    def polygon(self, width: float) -> Polygon | MultiPolygon:
        pieces = [line.buffer(width / 2.0, cap_style=1, join_style=1, resolution=12) for line in self.lines]
        return unary_union(pieces).buffer(0)'''

new = '''    def polygon(self, width: float) -> Polygon | MultiPolygon:
        pieces = [line.buffer(width / 2.0, cap_style=1, join_style=1, resolution=12) for line in self.lines]
        geometry = unary_union(pieces).buffer(0)
        # A connector meeting a closed loop creates a legitimate branched road,
        # but exact tangent offset curves can meet at a single repeated polygon
        # vertex. Extrusion of that pinch exports one vertical edge shared by
        # four faces. A 2 mm close/open regularisation removes only the singular
        # point, preserving nominal road width and all building clearances while
        # yielding one simple manifold boundary suitable for solid extrusion.
        if not geometry.is_empty:
            epsilon = 0.002
            geometry = geometry.buffer(epsilon, resolution=4, join_style=1)
            geometry = geometry.buffer(-epsilon, resolution=4, join_style=1).buffer(0)
        return geometry'''

if old not in text:
    raise RuntimeError("Rev.P3 road polygon regularisation anchor not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("REV_P3_POLYGON_REGULARIZED")
