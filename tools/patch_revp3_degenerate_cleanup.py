from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

anchor = '''def _triangle_signed_area(vertices: np.ndarray, face: np.ndarray) -> float:
    a, b, c = vertices[face]
    return 0.5 * float(
        (b[0] - a[0]) * (c[1] - a[1])
        - (b[1] - a[1]) * (c[0] - a[0])
    )


'''
addition = anchor + '''def _clean_plan_triangulation(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    coordinate_decimals: int = 10,
    area_tolerance: float = 1.0e-11,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Merge coincident 2D nodes and remove only mathematically zero-area faces.

    Earcut can emit redundant triangles where Boolean road/apron boundaries contain
    repeated or collinear points.  Those faces carry no area but prevent the solid
    from passing the strict Rev.P3 zero-area and watertight checks.  The operation
    below is deterministic and preserves every non-zero-area triangle.
    """
    vertices = np.asarray(vertices_2d, dtype=float)
    triangles = np.asarray(faces, dtype=int)
    if len(vertices) < 3 or len(triangles) < 1:
        raise RuntimeError("Plan triangulation is empty before cleanup")

    rounded = np.round(vertices[:, :2], coordinate_decimals)
    unique_vertices, inverse = np.unique(rounded, axis=0, return_inverse=True)
    remapped = inverse[triangles]
    repeated_index = (
        (remapped[:, 0] == remapped[:, 1])
        | (remapped[:, 1] == remapped[:, 2])
        | (remapped[:, 2] == remapped[:, 0])
    )
    signed = np.asarray(
        [_triangle_signed_area(unique_vertices, face) for face in remapped],
        dtype=float,
    )
    keep = (~repeated_index) & (np.abs(signed) > area_tolerance)
    cleaned_faces = remapped[keep]
    if len(cleaned_faces) < 1:
        raise RuntimeError("All plan triangles were degenerate after cleanup")

    # Remove vertices no longer referenced by a retained face and make indices
    # compact before conforming refinement and boundary-edge extraction.
    used = np.unique(cleaned_faces.reshape(-1))
    compact_map = np.full(len(unique_vertices), -1, dtype=int)
    compact_map[used] = np.arange(len(used), dtype=int)
    compact_vertices = unique_vertices[used]
    compact_faces = compact_map[cleaned_faces]

    report = {
        "input_vertices": int(len(vertices)),
        "unique_vertices": int(len(unique_vertices)),
        "output_vertices": int(len(compact_vertices)),
        "input_faces": int(len(triangles)),
        "removed_repeated_index_faces": int(np.count_nonzero(repeated_index)),
        "removed_zero_area_faces": int(np.count_nonzero((~repeated_index) & (np.abs(signed) <= area_tolerance))),
        "output_faces": int(len(compact_faces)),
    }
    return compact_vertices, compact_faces, report


'''
if anchor not in text:
    raise RuntimeError("Rev.P3 triangle helper anchor not found")
text = text.replace(anchor, addition, 1)

anchor = '''    if len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Earcut returned no usable triangulation")

    vertices_2d, faces_2d = _refine_triangulation_conforming(
        vertices_2d,
        faces_2d,
        max_edge=float(max_edge),
    )
    # Normalize top orientation before deriving directed boundary edges.
    signed = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
'''
replacement = '''    if len(vertices_2d) < 3 or len(faces_2d) < 1:
        raise RuntimeError("Earcut returned no usable triangulation")

    vertices_2d, faces_2d, pre_refine_cleanup = _clean_plan_triangulation(
        vertices_2d,
        faces_2d,
    )
    vertices_2d, faces_2d = _refine_triangulation_conforming(
        vertices_2d,
        faces_2d,
        max_edge=float(max_edge),
    )
    vertices_2d, faces_2d, post_refine_cleanup = _clean_plan_triangulation(
        vertices_2d,
        faces_2d,
    )
    # Normalize top orientation before deriving directed boundary edges.
    signed = np.asarray(
        [_triangle_signed_area(vertices_2d, face) for face in faces_2d],
        dtype=float,
    )
'''
if anchor not in text:
    raise RuntimeError("Rev.P3 solid cleanup call anchor not found")
text = text.replace(anchor, replacement, 1)

anchor = '''    if np.any(np.abs(signed) <= 1.0e-12):
        raise RuntimeError("Refined top triangulation contains zero-area faces")

    boundary_edges = _oriented_boundary_edges(faces_2d)
'''
replacement = '''    if np.any(np.abs(signed) <= 1.0e-12):
        raise RuntimeError("Plan cleanup failed to remove zero-area faces")

    boundary_edges = _oriented_boundary_edges(faces_2d)
'''
if anchor not in text:
    raise RuntimeError("Rev.P3 zero-area guard anchor not found")
text = text.replace(anchor, replacement, 1)

path.write_text(text, encoding="utf-8")
print("REV_P3_DEGENERATE_TRIANGLES_CLEANED")
