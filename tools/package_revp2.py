from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path('revp2_output')
RENDERS = ROOT / 'renders'


def montage():
    images = []
    for p in sorted(RENDERS.glob('*.png')):
        im = Image.open(p).convert('RGB')
        images.append((p.name, im))
    if not images:
        return
    thumb_w, thumb_h = 960, 540
    cols = 2
    rows = (len(images) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * thumb_w, rows * (thumb_h + 44)), 'white')
    draw = ImageDraw.Draw(canvas)
    for i, (name, im) in enumerate(images):
        im.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = (i % cols) * thumb_w + (thumb_w - im.width) // 2
        y0 = (i // cols) * (thumb_h + 44)
        y = y0 + (thumb_h - im.height) // 2
        canvas.paste(im, (x, y))
        draw.rectangle((i % cols * thumb_w, y0 + thumb_h, (i % cols + 1) * thumb_w, y0 + thumb_h + 44), fill=(242, 245, 247))
        draw.text((i % cols * thumb_w + 16, y0 + thumb_h + 12), name, fill=(25, 39, 52))
    canvas.save(ROOT / '20_Монтаж_контрольных_ракурсов_RevP2.jpg', quality=94, subsampling=0)


def write_summary():
    qa = json.loads((ROOT / '20_Exterior_QA_Report.json').read_text(encoding='utf-8'))
    lines = [
        '# A.1 / Rev.P2 — итог повторного внешнего аудита',
        '',
        f"- Исходных геометрических объектов: {qa['source_geometry_count']}",
        f"- Объектов в координационной модели: {qa['coordination_geometry_count']}",
        f"- Объектов в очищенной наружной модели: {qa['exterior_geometry_count']}",
        f"- Удалено служебных/ошибочных объектов: {qa['removed_geometry_count']}",
        f"- Добавлено новых наружных групп: {qa['new_geometry_count']}",
        f"- Удалено конфликтующих компонентов деревьев: {qa['filtered_tree_components']}",
        f"- Удалено секций ограждения в местах ворот: {qa['filtered_fence_components_at_gates']}",
        f"- Критические наружные коллизии: {qa['acceptance']['open_external_critical_clashes']}",
        f"- Высокозначимые наружные коллизии: {qa['acceptance']['open_external_high_clashes']}",
        f"- Служебная геометрия в финальной модели: {qa['acceptance']['helper_geometry_count']}",
        f"- Максимальный уклон дорог: {qa['acceptance']['max_road_grade_pct']:.2f}% при лимите {qa['acceptance']['max_grade_limit_pct']:.2f}%",
        '',
        '## Дороги',
        '',
    ]
    for code, m in qa['roads'].items():
        lines.append(f"- {code}: длина {m['length_m']:.1f} м; максимальный уклон {m['max_grade_pct']:.2f}%; контрольный радиус {m['min_radius_p05_m']:.1f} м.")
    (ROOT / '20_Итог_повторного_аудита_RevP2.md').write_text('\n'.join(lines), encoding='utf-8')


def package():
    zip_path = ROOT / '20_Комплект_A1_RevP2_ExteriorQA.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(ROOT.rglob('*')):
            if p.is_file() and p != zip_path:
                zf.write(p, p.relative_to(ROOT))


def main():
    montage()
    write_summary()
    package()
    print('PACKAGE_DONE')


if __name__ == '__main__':
    main()
