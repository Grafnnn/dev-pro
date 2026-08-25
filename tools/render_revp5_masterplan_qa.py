from __future__ import annotations

import importlib
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
BEFORE = Path("work_revp3") / "20_Модель_A1_RevP2_ExteriorQA.glb"
AFTER = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
PNG = ROOT / "qa_png"
PNG.mkdir(parents=True, exist_ok=True)

RENDER_WIDTH = 1800
RENDER_HEIGHT = 1100
MIN_MODEL_BYTES = 1_000_000
MIN_RENDER_BYTES = 10_000

REQUIRED_AFTER_OBJECTS = {
    "REV_P5_MP_ASSEMBLY_PAD_60x40",
    "REV_P5_MP_HEAVY_HAUL_ROUTE",
    "REV_P5_MP_CRANE_PAD_01",
    "REV_P5_MP_CRANE_PAD_02",
    "REV_P5_MP_D3_EMERGENCY_BAY",
    "REV_P5_MP_TIRE_QUARANTINE",
    "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE",
    "REV_P5_MP_DRY_HYBRID_COOLER_RESERVE_40x25",
    "REV_P5_MP_CLEAN_SNOW_CONTAINMENT",
    "REV_P5_MP_DIRTY_SNOW_CONTAINMENT",
    "REV_P5_MP_PHASE2_CAPPED_STUBS",
    "REV_P5_MP_RAW_LOOP_ONE_WAY_MARKINGS",
    "REV_P5_MP_PRODUCT_LOOP_ONE_WAY_MARKINGS",
    "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3",
    "REV_P5_MP_LABORATORY_RESERVE",
    "REV_P5_MP_WASTEWATER_TREATMENT_RESERVE",
    "REV_P5_MP_DG_UPS_RESERVE",
    "REV_P5_MP_HVAC_HEAT_SOURCE_RESERVE",
    "REV_P5_SAFETY_PRELIM_PYROLYSIS_ZONE",
}

FEATURE_COLORS = {
    "ASSEMBLY": (0.72, 0.47, 0.18, 1),
    "HEAVY_HAUL": (0.95, 0.28, 0.05, 1),
    "CRANE_PAD": (0.98, 0.67, 0.05, 1),
    "EMERGENCY_BAY": (0.95, 0.05, 0.04, 1),
    "QUARANTINE": (0.70, 0.03, 0.03, 1),
    "PEDESTRIAN": (0.02, 0.72, 0.92, 1),
    "COOLER": (0.02, 0.55, 0.68, 1),
    "CLEAN_SNOW": (0.65, 0.88, 1.0, 1),
    "DIRTY_SNOW": (0.34, 0.46, 0.56, 1),
    "PHASE2_CAPPED": (0.92, 0.38, 0.12, 1),
    "ONE_WAY": (1.0, 0.85, 0.10, 1),
    "BLD05_SERVICE_RAMP": (0.72, 0.73, 0.75, 1),
    "LABORATORY": (0.31, 0.39, 0.76, 1),
    "WASTEWATER": (0.05, 0.50, 0.33, 1),
    "DG_UPS": (0.22, 0.22, 0.27, 1),
    "HVAC": (0.55, 0.25, 0.65, 1),
    "SAFETY_PRELIM": (0.95, 0.18, 0.03, 1),
}


@dataclass(frozen=True)
class CameraView:
    view_id: str
    location: tuple[float, float, float]
    target: tuple[float, float, float]
    lens: float = 58.0
    ortho_scale: float | None = None
    clay: bool = False
    required_after: tuple[str, ...] = ()
    fully_framed_after: tuple[str, ...] = ()
    hidden_tokens: tuple[str, ...] = ()


# One immutable list drives both imports. Camera matrices are compared after
# rendering, proving that every BEFORE/AFTER pair uses the same view.
CAMERA_VIEWS = (
    CameraView("01_Aerial_Masterplan", (30, -190, 405), (325, 220, 116), 52),
    CameraView("02_Orthographic_Top", (304, 220, 900), (304, 220, 110), 55, 740),
    CameraView(
        "03_West_Logistics_Assembly_Quarantine",
        (155, 287, 700),
        (155, 287, 110),
        55,
        320,
        required_after=(
            "REV_P5_MP_ASSEMBLY_PAD_60x40",
            "REV_P5_MP_TIRE_QUARANTINE",
            "REV_P5_MP_HEAVY_HAUL_ROUTE",
        ),
    ),
    CameraView(
        "04_Ramp_Cranes_Pedestrian",
        (250, 100, 360),
        (410, 225, 112),
        52,
        required_after=(
            "REV_P5_MP_BLD05_SERVICE_RAMP_TO_D3",
            "REV_P5_MP_CRANE_PAD_01",
            "REV_P5_MP_CRANE_PAD_02",
            "REV_P5_MP_PROTECTED_PEDESTRIAN_ROUTE",
        ),
    ),
    CameraView(
        "05_D3_D5_Emergency",
        (557, 220, 600),
        (557, 220, 108),
        55,
        300,
        required_after=(
            "REV_P5_EXT_D3_ROAD",
            "REV_P5_EXT_D5_ROAD",
            "REV_P5_MP_D3_EMERGENCY_BAY",
        ),
        fully_framed_after=("REV_P5_MP_D3_EMERGENCY_BAY",),
        hidden_tokens=("HEAVY_HAUL_ROUTE",),
    ),
    CameraView(
        "06_Relocated_Snow_Lower_Utilities",
        (325, -270, 600),
        (325, 60, 105),
        38,
        required_after=(
            "REV_P5_MP_CLEAN_SNOW_CONTAINMENT",
            "REV_P5_MP_DIRTY_SNOW_CONTAINMENT",
            "REV_P5_MP_DRY_HYBRID_COOLER_RESERVE_40x25",
            "REV_P5_MP_WASTEWATER_TREATMENT_RESERVE",
        ),
    ),
    CameraView(
        "07_Phase2_Capped_Interfaces",
        (635, 535, 250),
        (466, 412, 141),
        67,
        required_after=("REV_P5_MP_PHASE2_CAPPED_STUBS",),
    ),
)


def ensure_numpy_for_gltf() -> None:
    """Expose an ABI-compatible NumPy installation to Blender's glTF add-on."""
    try:
        importlib.import_module("numpy")
        return
    except ModuleNotFoundError:
        pass

    major, minor = sys.version_info[:2]
    version = f"python{major}.{minor}"
    candidates = [
        Path("/usr/lib/python3/dist-packages"),
        Path("/usr/local/lib") / version / "dist-packages",
        Path.home() / ".local" / "lib" / version / "site-packages",
    ]
    toolcache = Path("/opt/hostedtoolcache/Python")
    if toolcache.exists():
        candidates.extend(toolcache.glob(f"{major}.{minor}*/x64/lib/{version}/site-packages"))

    attempted = []
    for candidate in candidates:
        if not candidate.exists() or not (candidate / "numpy").exists():
            continue
        attempted.append(str(candidate))
        sys.path.insert(0, str(candidate))
        importlib.invalidate_caches()
        try:
            importlib.import_module("numpy")
            return
        except (ImportError, ModuleNotFoundError):
            sys.path.remove(str(candidate))

    raise RuntimeError(
        "Blender glTF import requires NumPy built for its embedded Python "
        f"{major}.{minor}; no compatible package was found. Checked: {attempted or candidates}"
    )


def look_at(obj, target) -> None:
    direction = Vector(target) - obj.location
    if direction.length <= 1.0e-9:
        raise RuntimeError(f"Camera location equals target: {target}")
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def project_to_blender(point: tuple[float, float, float]) -> tuple[float, float, float]:
    """Convert project XYZ (Z-up) to Blender coordinates used by glTF import."""
    x, y, z = point
    return (x, -z, y)


def set_optional(target, attribute: str, value) -> None:
    try:
        setattr(target, attribute, value)
    except (AttributeError, TypeError):
        pass


def validate_model_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".glb":
        raise RuntimeError(f"Expected GLB input, got {path}")
    if path.stat().st_size < MIN_MODEL_BYTES:
        raise RuntimeError(f"GLB is unexpectedly small: {path} ({path.stat().st_size} bytes)")


def imported_scene_metrics(path: Path, require_revp5: bool) -> dict:
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(mesh_objects) < 100:
        raise RuntimeError(f"Incomplete GLB import for {path}: only {len(mesh_objects)} mesh objects")

    total_vertices = 0
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    empty = []
    non_finite = []
    names = set()
    for obj in mesh_objects:
        names.add(obj.name)
        vertices = obj.data.vertices
        polygons = obj.data.polygons
        total_vertices += len(vertices)
        if not vertices or not polygons:
            empty.append(obj.name)
            continue
        for vertex in vertices:
            if not all(math.isfinite(float(value)) for value in vertex.co):
                non_finite.append(obj.name)
                break
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                value = float(point[axis])
                minimum[axis] = min(minimum[axis], value)
                maximum[axis] = max(maximum[axis], value)

    if empty:
        raise RuntimeError(f"Imported empty mesh objects from {path}: {empty[:20]}")
    if non_finite:
        raise RuntimeError(f"Imported non-finite mesh coordinates from {path}: {non_finite[:20]}")
    if total_vertices < 10_000:
        raise RuntimeError(f"Incomplete GLB import for {path}: only {total_vertices} vertices")
    if not all(math.isfinite(value) for value in minimum + maximum):
        raise RuntimeError(f"Non-finite scene bounds after importing {path}: {minimum}, {maximum}")
    span_by_axis = [maximum[index] - minimum[index] for index in range(3)]
    span_sorted_desc = sorted(span_by_axis, reverse=True)
    if (
        span_sorted_desc[0] < 550.0
        or span_sorted_desc[1] < 400.0
        or span_sorted_desc[2] < 40.0
    ):
        raise RuntimeError(
            f"Unexpectedly truncated scene bounds after importing {path}: "
            f"bounds={minimum, maximum}, spans_by_axis={span_by_axis}, "
            f"spans_sorted_desc={span_sorted_desc}"
        )

    missing = sorted(REQUIRED_AFTER_OBJECTS - names) if require_revp5 else []
    if missing:
        raise RuntimeError(f"Integrated GLB is missing required Rev.P5 objects: {missing}")

    return {
        "file": path.name,
        "mesh_objects": len(mesh_objects),
        "vertices": total_vertices,
        "bounds": [minimum, maximum],
        "spans_by_axis": span_by_axis,
        "spans_sorted_desc": span_sorted_desc,
        "required_revp5_objects_present": not missing if require_revp5 else None,
    }


def setup(path: Path, require_revp5: bool):
    validate_model_file(path)
    ensure_numpy_for_gltf()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=str(path.resolve()))
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not finish importing {path}: {result}")
    import_metrics = imported_scene_metrics(path, require_revp5)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = RENDER_WIDTH
    scene.render.resolution_y = RENDER_HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("REV_P5_QA_WORLD")
    scene.world.color = (0.87, 0.89, 0.91)
    shading = scene.display.shading
    set_optional(shading, "light", "STUDIO")
    set_optional(shading, "color_type", "OBJECT")
    set_optional(shading, "show_shadows", True)
    set_optional(shading, "show_cavity", True)
    set_optional(shading, "cavity_type", "WORLD")
    set_optional(shading, "curvature_ridge_factor", 1.4)
    set_optional(shading, "curvature_valley_factor", 1.2)
    set_optional(shading, "show_outline", True)
    set_optional(shading, "show_specular_highlight", False)
    set_optional(shading, "background_type", "WORLD")

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "REV_P5_QA_CAMERA"
    camera.data.clip_start = 0.5
    camera.data.clip_end = 5000
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.sensor_width = 36.0
    scene.camera = camera
    return scene, camera, import_metrics


def style_objects(view: CameraView) -> None:
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.upper()
        hide = any(token in name for token in (
            "EXISTING_CONIFERS", "QA_CLEARANCE", "VEHICLES_FOR_SCALE",
            "NET_COMMS", "NET_EL_04KV", "SITE_CCTV", "CENTERLINE",
        )) or any(token in name for token in view.hidden_tokens)
        obj.hide_render = hide
        obj.hide_viewport = hide
        if hide:
            continue
        set_optional(obj, "show_wire", view.clay)
        set_optional(obj, "show_all_edges", view.clay)
        if view.clay:
            obj.color = (0.72, 0.73, 0.74, 1)
            continue
        matched = False
        for token, color in FEATURE_COLORS.items():
            if token in name:
                obj.color = color
                matched = True
                break
        if matched:
            continue
        if "REV_P5_EXT_D" in name and "_ROAD" in name:
            obj.color = (0.16, 0.18, 0.20, 1)
        elif "SERVICE_APRON" in name:
            obj.color = (0.58, 0.60, 0.61, 1)
        elif "FOUNDATION" in name:
            obj.color = (0.72, 0.70, 0.63, 1)
        elif name.startswith("BLD_"):
            obj.color = (0.73, 0.76, 0.78, 1)
        elif "FINISHED_DESIGN_SURFACE" in name:
            obj.color = (0.48, 0.56, 0.42, 1)
        elif "ROAD" in name:
            obj.color = (0.24, 0.26, 0.28, 1)
        elif "RESERVE" in name:
            obj.color = (0.44, 0.62, 0.38, 1)
        else:
            obj.color = (0.62, 0.65, 0.66, 1)


def camera_signature(camera) -> tuple:
    matrix = tuple(round(float(value), 9) for row in camera.matrix_world for value in row)
    projection = (
        camera.data.type,
        round(float(camera.data.lens), 9),
        round(float(camera.data.ortho_scale), 9),
        RENDER_WIDTH,
        RENDER_HEIGHT,
    )
    return matrix + projection


def assert_features_in_frame(scene, camera, view: CameraView) -> None:
    for name in view.required_after:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH" or obj.hide_render:
            raise RuntimeError(f"{view.view_id}: required visible object is unavailable: {name}")
        points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        # A winding road can cross the frame while every global bounding-box
        # corner and its object origin remain outside it. Sample the actual
        # mesh so the gate proves visible geometry, not only bbox placement.
        stride = max(1, len(obj.data.vertices) // 2000)
        points.extend(
            obj.matrix_world @ obj.data.vertices[index].co
            for index in range(0, len(obj.data.vertices), stride)
        )
        projected = [world_to_camera_view(scene, camera, point) for point in points]
        if not any(point.z > 0.0 and -0.02 <= point.x <= 1.02 and -0.02 <= point.y <= 1.02 for point in projected):
            coordinates = [(round(point.x, 3), round(point.y, 3), round(point.z, 3)) for point in projected]
            raise RuntimeError(f"{view.view_id}: {name} is outside the camera frame: {coordinates}")
        if name in view.fully_framed_after:
            corner_projection = [world_to_camera_view(scene, camera, point) for point in points[:8]]
            if not all(
                point.z > 0.0 and 0.02 <= point.x <= 0.98 and 0.02 <= point.y <= 0.98
                for point in corner_projection
            ):
                coordinates = [
                    (round(point.x, 3), round(point.y, 3), round(point.z, 3))
                    for point in corner_projection
                ]
                raise RuntimeError(
                    f"{view.view_id}: {name} is not fully framed with a review margin: {coordinates}"
                )


def verify_png(output: Path) -> dict:
    if not output.is_file() or output.stat().st_size < MIN_RENDER_BYTES:
        size = output.stat().st_size if output.exists() else 0
        raise RuntimeError(f"Render is missing or unexpectedly small: {output} ({size} bytes)")
    image = bpy.data.images.load(str(output.resolve()), check_existing=False)
    try:
        width, height = (int(image.size[0]), int(image.size[1]))
        if (width, height) != (RENDER_WIDTH, RENDER_HEIGHT):
            raise RuntimeError(f"Unexpected render dimensions for {output}: {(width, height)}")
        pixels = image.pixels
        luminance = []
        alpha = []
        for y_index in range(1, 12):
            y = min(height - 1, int(y_index * height / 12))
            for x_index in range(1, 20):
                x = min(width - 1, int(x_index * width / 20))
                offset = 4 * (y * width + x)
                red, green, blue, opacity = (float(pixels[offset + channel]) for channel in range(4))
                luminance.append(0.2126 * red + 0.7152 * green + 0.0722 * blue)
                alpha.append(opacity)
        dynamic_range = max(luminance) - min(luminance)
        if dynamic_range < 0.02:
            raise RuntimeError(f"Render appears blank or flat: {output}, sampled range={dynamic_range:.6f}")
        if max(alpha) < 0.99:
            raise RuntimeError(f"Render has no opaque sampled pixels: {output}")
        return {
            "file": output.name,
            "size_bytes": output.stat().st_size,
            "dimensions": [width, height],
            "sampled_luminance_range": dynamic_range,
        }
    finally:
        bpy.data.images.remove(image)


def render(scene, camera, output: Path, view: CameraView, require_frame_checks: bool) -> tuple[tuple, dict]:
    style_objects(view)
    camera.location = project_to_blender(view.location)
    if view.ortho_scale is None:
        camera.data.type = "PERSP"
        camera.data.lens = view.lens
    else:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = view.ortho_scale
    look_at(camera, project_to_blender(view.target))
    bpy.context.view_layer.update()
    if require_frame_checks:
        assert_features_in_frame(scene, camera, view)
    signature = camera_signature(camera)
    scene.render.filepath = str(output.resolve())
    result = bpy.ops.render.render(write_still=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not finish rendering {output}: {result}")
    return signature, verify_png(output)


def render_model(path: Path, suffix: str, require_revp5: bool) -> tuple[dict, dict, list[dict]]:
    scene, camera, import_metrics = setup(path, require_revp5)
    signatures = {}
    renders = []
    for view in CAMERA_VIEWS:
        output = PNG / f"26_QA_{view.view_id}_{suffix}.png"
        signature, render_metrics = render(scene, camera, output, view, require_revp5)
        signatures[view.view_id] = signature
        renders.append(render_metrics)
    return signatures, import_metrics, renders


def main() -> None:
    if len(CAMERA_VIEWS) != 7 or len({view.view_id for view in CAMERA_VIEWS}) != 7:
        raise RuntimeError("Visual QA must contain exactly seven uniquely named camera views")

    validate_model_file(BEFORE)
    validate_model_file(AFTER)
    for stale in PNG.glob("*.png"):
        stale.unlink()

    before_signatures, before_import, before_renders = render_model(BEFORE, "BEFORE_RevP2", False)
    after_signatures, after_import, after_renders = render_model(AFTER, "AFTER_RevP5", True)
    if before_signatures != after_signatures:
        mismatched = sorted(
            view_id for view_id in before_signatures
            if before_signatures[view_id] != after_signatures.get(view_id)
        )
        raise RuntimeError(f"BEFORE/AFTER camera transforms are not identical: {mismatched}")

    expected = {
        PNG / f"26_QA_{view.view_id}_{suffix}.png"
        for view in CAMERA_VIEWS
        for suffix in ("BEFORE_RevP2", "AFTER_RevP5")
    }
    actual = set(PNG.glob("*.png"))
    if actual != expected or len(actual) != 14:
        raise RuntimeError(
            f"Expected exactly 14 controlled PNGs, got {len(actual)}; "
            f"missing={sorted(str(path) for path in expected - actual)}, "
            f"unexpected={sorted(str(path) for path in actual - expected)}"
        )

    print({
        "camera_pairs": len(CAMERA_VIEWS),
        "before_import": before_import,
        "after_import": after_import,
        "before_renders": len(before_renders),
        "after_renders": len(after_renders),
    })
    print("REV_P5_VISUAL_QA_RENDERED_AND_VERIFIED")


if __name__ == "__main__":
    main()
