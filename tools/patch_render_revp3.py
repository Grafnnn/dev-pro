from pathlib import Path

path = Path('tools/render_revp3_qa.py')
text = path.read_text(encoding='utf-8')
old = '''    shading.light = "STUDIO"
    shading.studio_light = "paint.sl"
    shading.color_type = "OBJECT"'''
new = '''    shading.light = "STUDIO"
    try:
        shading.studio_light = "paint.sl"
    except Exception:
        pass
    shading.color_type = "OBJECT"'''
if old not in text:
    raise RuntimeError('Studio-light patch target not found')
text = text.replace(old, new, 1)
old2 = '''        scene.display.shading.show_wireframes = bool(view.get("clay", False))'''
new2 = '''        try:
            scene.display.shading.show_wireframes = bool(view.get("clay", False))
        except Exception:
            pass'''
if old2 not in text:
    raise RuntimeError('Wireframe patch target not found')
text = text.replace(old2, new2, 1)
path.write_text(text, encoding='utf-8')
print('REV_P3_RENDER_PATCHED')
