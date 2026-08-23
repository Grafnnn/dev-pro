from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(os.environ.get('OUT_ROOT', 'revp2_output'))
GLB = ROOT / '20_Модель_A1_RevP2_ExteriorQA.glb'
RENDER_DIR = ROOT / 'renders'
RENDER_DIR.mkdir(parents=True, exist_ok=True)


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(GLB.resolve()))
    scene = bpy.context.scene
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = 'RGBA'
    try:
        if bpy.app.version >= (4, 0, 0):
            scene.view_settings.look = 'AgX - Medium High Contrast'
        else:
            scene.view_settings.look = 'Medium High Contrast'
    except Exception:
        pass
    scene.world.color = (0.82, 0.88, 0.94)

    bpy.ops.object.light_add(type='SUN', location=(350, 100, 500))
    sun = bpy.context.object
    sun.name = 'QA_SUN'
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(28), math.radians(-20), math.radians(125))
    try:
        sun.data.angle = math.radians(4.0)
    except Exception:
        pass
    bpy.ops.object.light_add(type='AREA', location=(180, 140, 320))
    area = bpy.context.object
    area.data.energy = 1800
    area.data.shape = 'DISK'
    area.data.size = 220
    look_at(area, (350, 220, 115))

    bpy.ops.object.camera_add()
    cam = bpy.context.object
    cam.data.lens = 52
    cam.data.sensor_width = 36
    scene.camera = cam
    return scene, cam


def render_view(scene, cam, filename, location, target, lens=52, ortho=False, ortho_scale=700):
    cam.location = location
    cam.data.lens = lens
    if ortho:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = ortho_scale
    else:
        cam.data.type = 'PERSP'
    look_at(cam, target)
    scene.render.filepath = str((RENDER_DIR / filename).resolve())
    bpy.ops.render.render(write_still=True)


def main():
    scene, cam = setup_scene()
    target = (360, 220, 116)
    views = [
        ('20_RevP2_01_птичий_полет_ЮЗ.png', (40, -130, 355), target, 54, False, 0),
        ('20_RevP2_02_птичий_полет_СВ.png', (720, 610, 370), target, 55, False, 0),
        ('20_RevP2_03_восточный_серпантин.png', (690, 260, 245), (505, 225, 117), 58, False, 0),
        ('20_RevP2_04_нижняя_терраса.png', (610, -80, 200), (420, 120, 106), 58, False, 0),
        ('20_RevP2_05_верхний_въезд.png', (90, 410, 185), (300, 325, 134), 52, False, 0),
        ('20_RevP2_06_план_сверху.png', (304, 220, 820), (304, 220, 110), 50, True, 690),
    ]
    for args in views:
        render_view(scene, cam, *args)
    print('RENDER_DONE')


if __name__ == '__main__':
    main()
