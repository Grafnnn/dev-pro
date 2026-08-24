from __future__ import annotations

import os
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
BEFORE = Path("work_revp3") / "20_Модель_A1_RevP2_ExteriorQA.glb"
AFTER = ROOT / "26_Модель_A1_RevP5_Integrated_preFEED.glb"
PNG = ROOT / "qa_png"
PNG.mkdir(parents=True, exist_ok=True)

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


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup(path: Path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path.resolve()))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1800
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("REV_P5_QA_WORLD")
    scene.world.color = (0.87, 0.89, 0.91)
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    shading.curvature_ridge_factor = 1.4
    shading.curvature_valley_factor = 1.2
    shading.show_outline = True
    shading.show_specular_highlight = False
    shading.background_type = "WORLD"

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.clip_start = 0.5
    camera.data.clip_end = 5000
    scene.camera = camera
    return scene, camera


def style_objects(clay: bool = False):
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        name = obj.name.upper()
        hide = any(token in name for token in (
            "EXISTING_CONIFERS", "QA_CLEARANCE", "VEHICLES_FOR_SCALE",
            "NET_COMMS", "NET_EL_04KV", "SITE_CCTV", "CENTERLINE",
        ))
        obj.hide_render = hide
        obj.hide_viewport = hide
        if hide:
            continue
        obj.show_wire = clay
        obj.show_all_edges = clay
        if clay:
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


def render(scene, camera, output: Path, location, target, lens=58, ortho_scale=None, clay=False):
    style_objects(clay)
    camera.location = location
    if ortho_scale is None:
        camera.data.type = "PERSP"
        camera.data.lens = lens
    else:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = ortho_scale
    look_at(camera, target)
    scene.render.filepath = str(output.resolve())
    bpy.ops.render.render(write_still=True)


def render_model(path: Path, suffix: str):
    scene, camera = setup(path)
    views = [
        ("01_Aerial_Masterplan", (35, -165, 390), (330, 220, 116), 58, None, False),
        ("02_Orthographic_Top", (304, 220, 900), (304, 220, 110), 55, 700, False),
        ("03_West_Logistics", (-55, 110, 245), (130, 255, 124), 62, None, False),
        ("04_Pyrolysis_Ramp_Cranes", (250, 70, 235), (450, 220, 116), 62, None, False),
        ("05_D3_Phase2_Emergency", (745, 360, 280), (545, 265, 122), 64, None, False),
        ("06_Lower_Utilities_Snow", (650, -100, 240), (400, 85, 105), 60, None, False),
        ("07_Wireframe_Integrated", (710, -110, 330), (350, 215, 115), 60, None, True),
    ]
    for view_id, location, target, lens, ortho, clay in views:
        render(scene, camera, PNG / f"26_QA_{view_id}_{suffix}.png", location, target, lens, ortho, clay)


def main():
    if not BEFORE.exists():
        raise FileNotFoundError(BEFORE)
    if not AFTER.exists():
        raise FileNotFoundError(AFTER)
    render_model(BEFORE, "BEFORE_RevP2")
    render_model(AFTER, "AFTER_RevP5")
    print("REV_P5_VISUAL_QA_RENDERED")


if __name__ == "__main__":
    main()
