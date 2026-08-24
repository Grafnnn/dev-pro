from pathlib import Path

path = Path('tools/package_revp3.py')
text = path.read_text(encoding='utf-8')
old = '''CORE_NAMES = [
    "20_Модель_A1_RevP3_RoadQA.glb",
    "20_Модель_A1_RevP3_RoadQA.obj",
    "20_Road_QA_Report_RevP3.json",
]'''
new = '''CORE_NAMES = [
    "20_Модель_A1_RevP3_RoadQA.glb",
    "20_Модель_A1_RevP3_RoadQA.obj",
    "20_Road_QA_Report_RevP3.json",
    "20_Blender_Mesh_QA_RevP3.json",
]'''
if old not in text:
    raise RuntimeError('CORE_NAMES patch target not found')
text = text.replace(old, new, 1)
old2 = '''        qa_path,
        visual_path,'''
new2 = '''        qa_path,
        ROOT / "20_Blender_Mesh_QA_RevP3.json",
        visual_path,'''
if old2 not in text:
    raise RuntimeError('checksum target patch not found')
text = text.replace(old2, new2, 1)
path.write_text(text, encoding='utf-8')
print('REV_P3_PACKAGE_PATCHED')
