from __future__ import annotations

import math
import os
import re
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(os.environ.get("OUT_ROOT", "revp3_output"))
SOURCE = Path("work_revp3") / "20_Модель_A1_RevP2_ExteriorQA.glb"
RESULT = ROOT / "20_Модель_A1_RevP3_RoadQA.glb"
RENDER_DIR = ROOT / "qa_png"
RENDER_DIR.mkdir(parents=True, exist_ok=True)

ROAD_COLORS = {
    "D1": (0.10, 0.45, 0.82, 1.0),
    "D2": (0.96, 0.55, 0.07, 1.0),
    "D3": (0.72, 0.12, 0.70, 1.0),
    "D4": (0.05, 0.55, 0.44, 1.0),
    "D5": (0.82, 0.08, 0.25, 1.0),
    "D6": (0.28, 0.32, 0.36, 1.0),
}
COLORS = {
    "building": (0.76, 0.77, 0.77, 1.0),
    "target_building": (0.90, 0.19, 0.10, 1.0),
    "foundation": (0.98, 0.78, 0.12, 1.0),
    "apron": (0.18, 0.74, 0.82, 1.0),
    "terrain": (0.54, 0.60, 0.48, 1.0),
    "wall": (0.50, 0.47, 0.43, 1.0),
    "detail": (0.20, 0.24, 0.27, 1.0),
    "muted": (0.80, 0.82, 0.83, 1.0),
}


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def name_upper(obj) -> str:
    return (obj.name or "").upper()


def road_code(name: str) -> str | None:
    match = re.search(r"(?:REV_P3_)?EXT_(D[1-6])_", name, re.I)
    return match.group(1).upper() if match else None


def import_model(path: Path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path.resolve()))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("QA_WORLD")
    scene.world.color = (0.84, 0.87, 0.90)
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.studio_light = "paint.sl"
    shading.color_type = "OBJECT"
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = "WORLD"
    shading.curvature_ridge_factor = 1.5
    shading.curvature_valley_factor = 1.2
    shading.show_specular_highlight = False
    shading.show_outline = True
    shading.background_type = "WORLD"

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.lens = 55
    camera.data.sensor_width = 36
    camera.data.clip_start = 0.5
    camera.data.clip_end = 5000
    scene.camera = camera
    return scene, camera


def base_visibility_and_colors(target_building: str | None = None, focus_road: str | None = None, clay: bool = False):
    target_building = (target_building or "").upper()
    for obj in bpy.context.scene.objects:
        if obj.type not in {"MESH", "CURVE"}:
            continue
        name = name_upper(obj)
        hide = (
            name.startswith("NET_")
            or name.startswith("PR_")
            or name.startswith("EQ_")
            or name.startswith("FND_E")
            or "EXISTING_CONIFERS" in name
            or "SITE_CCTV" in name
            or "VEHICLES_FOR_SCALE" in name
            or "QA_" in name
        )
        obj.hide_render = hide
        obj.hide_viewport = hide
        obj.show_wire = clay
        obj.show_all_edges = clay
        if hide:
            continue

        code = road_code(name)
        if clay:
            obj.color = (0.70, 0.72, 0.73, 1.0)
        elif code:
            color = ROAD_COLORS[code]
            if focus_road and code != focus_road:
                color = (0.60, 0.62, 0.64, 1.0)
            if "SERVICE_APRON" in name:
                color = COLORS["apron"]
            elif any(token in name for token in ("CURB", "GUTTER", "DRAIN", "MARKING", "LIGHT", "GUARD")):
                color = COLORS["detail"]
            obj.color = color
        elif "SERVICE_APRON" in name:
            obj.color = COLORS["apron"]
        elif "FOUNDATION_DECK" in name:
            obj.color = COLORS["foundation"]
        elif target_building and target_building in name:
            obj.color = COLORS["target_building"]
        elif name.startswith("BLD_"):
            obj.color = COLORS["building"]
        elif "FINISHED_DESIGN_SURFACE" in name:
            obj.color = COLORS["terrain"]
        elif "RETAINING" in name or "WALL" in name:
            obj.color = COLORS["wall"]
        else:
            obj.color = COLORS["muted"]


def render_camera(scene, camera, output: Path, location, target, lens=55, ortho_scale=None):
    camera.location = location
    if ortho_scale is not None:
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = ortho_scale
    else:
        camera.data.type = "PERSP"
        camera.data.lens = lens
    look_at(camera, target)
    scene.render.filepath = str(output.resolve())
    bpy.ops.render.render(write_still=True)


def render_model(path: Path, suffix: str):
    scene, camera = import_model(path)
    views = [
        {
            "id": "01_Aerial_Masterplan",
            "location": (30, -150, 370),
            "target": (370, 225, 118),
            "lens": 56,
        },
        {
            "id": "02_D3_Serpentine",
            "location": (735, 225, 285),
            "target": (580, 215, 116),
            "lens": 62,
            "focus_road": "D3",
        },
        {
            "id": "03_D2_BLD02",
            "location": (390, 455, 215),
            "target": (390, 343, 134),
            "lens": 62,
            "focus_road": "D2",
            "target_building": "BLD_02_",
        },
        {
            "id": "04_D2_BLD02A",
            "location": (245, 405, 195),
            "target": (317, 330, 134),
            "lens": 62,
            "focus_road": "D2",
            "target_building": "BLD_02A_",
        },
        {
            "id": "05_D5_BLD07",
            "location": (390, 245, 168),
            "target": (440, 175, 111),
            "lens": 65,
            "focus_road": "D5",
            "target_building": "BLD_07_",
        },
        {
            "id": "06_D5_BLD08",
            "location": (585, 245, 168),
            "target": (520, 180, 110),
            "lens": 65,
            "focus_road": "D5",
            "target_building": "BLD_08_",
        },
        {
            "id": "07_D5_BLD09",
            "location": (315, 245, 165),
            "target": (375, 175, 111),
            "lens": 65,
            "focus_road": "D5",
            "target_building": "BLD_09_",
        },
        {
            "id": "08_D6_BLD12",
            "location": (315, 25, 165),
            "target": (370, 100, 105),
            "lens": 65,
            "focus_road": "D6",
            "target_building": "BLD_12_",
        },
        {
            "id": "09_Orthographic_Top",
            "location": (304, 220, 900),
            "target": (304, 220, 110),
            "ortho_scale": 700,
        },
        {
            "id": "10_Wireframe_Road_Apron",
            "location": (660, -80, 285),
            "target": (420, 220, 116),
            "lens": 58,
            "clay": True,
        },
    ]

    for view in views:
        base_visibility_and_colors(
            target_building=view.get("target_building"),
            focus_road=view.get("focus_road"),
            clay=view.get("clay", False),
        )
        scene.display.shading.show_wireframes = bool(view.get("clay", False))
        output = RENDER_DIR / f"20_QA_{view['id']}_{suffix}.png"
        render_camera(
            scene,
            camera,
            output,
            view["location"],
            view["target"],
            lens=view.get("lens", 55),
            ortho_scale=view.get("ortho_scale"),
        )


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    if not RESULT.exists():
        raise FileNotFoundError(RESULT)
    render_model(SOURCE, "BEFORE_RevP2")
    render_model(RESULT, "AFTER_RevP3")
    print("REV_P3_VISUAL_QA_RENDERED")


if __name__ == "__main__":
    main()
