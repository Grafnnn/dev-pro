from __future__ import annotations

import hashlib
import json
import os
import statistics
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
PNG = ROOT / "qa_png"
COMPARE = ROOT / "qa_compare"
COMPARE.mkdir(parents=True, exist_ok=True)

CORE = [
    "26_Модель_A1_RevP5_Integrated_preFEED.glb",
    "26_Модель_A1_RevP5_Integrated_preFEED.obj",
    "26_Integrated_QA_Report_RevP5.json",
    "26_Masterplan_Change_Register_RevP5.json",
    "26_Masterplan_Change_Register_RevP5.csv",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def metrics(path: Path) -> dict:
    with Image.open(path).convert("RGB") as image:
        stat = ImageStat.Stat(image)
        variance = float(statistics.mean(stat.var))
        extrema = image.getextrema()
        ranges = [high - low for low, high in extrema]
        return {
            "width_px": image.width,
            "height_px": image.height,
            "variance": variance,
            "channel_ranges": ranges,
            "nonblank": bool(variance > 12.0 and max(ranges) > 25),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }


def build_comparisons() -> list[dict]:
    before = {path.name.replace("_BEFORE_RevP2.png", ""): path for path in PNG.glob("*_BEFORE_RevP2.png")}
    after = {path.name.replace("_AFTER_RevP5.png", ""): path for path in PNG.glob("*_AFTER_RevP5.png")}
    keys = sorted(set(before) & set(after))
    if len(keys) != 7:
        raise RuntimeError(f"Expected 7 identical-camera pairs, got {len(keys)}")
    label = get_font(28)
    title = get_font(20)
    report = []
    for key in keys:
        left_metrics = metrics(before[key])
        right_metrics = metrics(after[key])
        if not left_metrics["nonblank"] or not right_metrics["nonblank"]:
            raise RuntimeError(f"Blank visual QA image for {key}")
        with Image.open(before[key]).convert("RGB") as left, Image.open(after[key]).convert("RGB") as right:
            left = left.resize((1100, 672), Image.Resampling.LANCZOS)
            right = right.resize((1100, 672), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (2200, 748), (240, 243, 245))
            canvas.paste(left, (0, 60))
            canvas.paste(right, (1100, 60))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, 1100, 60), fill=(50, 57, 63))
            draw.rectangle((1100, 0, 2200, 60), fill=(15, 79, 98))
            draw.text((25, 12), "ДО — A.1 / Rev.P2", font=label, fill="white")
            draw.text((1125, 12), "ПОСЛЕ — A.1 / Rev.P5 Integrated", font=label, fill="white")
            draw.text((850, 718), key.replace("26_QA_", ""), font=title, fill=(35, 42, 47))
            output = COMPARE / f"{key}_COMPARE.png"
            canvas.save(output, optimize=True)
        report.append({
            "camera": key.replace("26_QA_", ""),
            "before": {"file": before[key].name, **left_metrics},
            "after": {"file": after[key].name, **right_metrics},
            "comparison": {"file": output.name, "size_bytes": output.stat().st_size, "sha256": sha256_file(output)},
        })
    return report


def contact_sheet(files: list[Path]) -> Path:
    thumb_w, thumb_h = 880, 300
    columns = 2
    rows = (len(files) + 1) // 2
    header = 90
    canvas = Image.new("RGB", (columns * thumb_w, header + rows * thumb_h), (234, 238, 241))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.width, header), fill=(15, 79, 98))
    draw.text((35, 22), "A.1 / Rev.P5 Integrated pre-FEED — визуальный QA мастер-плана", font=get_font(29), fill="white")
    for index, path in enumerate(files):
        with Image.open(path).convert("RGB") as image:
            image.thumbnail((thumb_w - 10, thumb_h - 10), Image.Resampling.LANCZOS)
            x0 = (index % columns) * thumb_w
            y0 = header + (index // columns) * thumb_h
            canvas.paste(image, (x0 + (thumb_w - image.width) // 2, y0 + (thumb_h - image.height) // 2))
    output = ROOT / "26_RevP5_Visual_QA_ContactSheet.jpg"
    canvas.save(output, quality=93, subsampling=0)
    return output


def main() -> None:
    for name in CORE:
        path = ROOT / name
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    qa = json.loads((ROOT / "26_Integrated_QA_Report_RevP5.json").read_text(encoding="utf-8"))
    if qa.get("status") != "PASS_CONTROLLED_PRE_FEED":
        raise RuntimeError("Integrated QA is not PASS_CONTROLLED_PRE_FEED")

    pairs = build_comparisons()
    sheet = contact_sheet(sorted(COMPARE.glob("*.png")))
    visual = {
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "identical_camera_pair_count": len(pairs),
        "all_images_nonblank": all(item["before"]["nonblank"] and item["after"]["nonblank"] for item in pairs),
        "pairs": pairs,
        "contact_sheet": {"file": sheet.name, "size_bytes": sheet.stat().st_size, "sha256": sha256_file(sheet)},
    }
    visual_path = ROOT / "26_Visual_QA_Report_RevP5.json"
    visual_path.write_text(json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = ROOT / "26_README_RevP5.md"
    acceptance = qa["acceptance"]
    readme.write_text(
        "# A.1 / Rev.P5 Integrated pre-FEED Masterplan\n\n"
        "Статус: контролируемая координационная модель pre-FEED; не для строительства.\n\n"
        "## Включено в фактическую 3D-модель\n\n"
        "- исправленная геометрия дорог D1–D6 и road–apron;\n"
        "- монтажная площадка 60×40 м и тяжеловесный маршрут;\n"
        "- две крановые позиции;\n"
        "- аварийный карман D3;\n"
        "- карантинная площадка шин;\n"
        "- защищённый пешеходный маршрут;\n"
        "- резерв dry/hybrid cooler 40×25 м;\n"
        "- раздельные зоны чистого и загрязнённого снега;\n"
        "- физические заглушенные подключения II очереди;\n"
        "- одностороннее движение на сырьевой и продуктовой петлях;\n"
        "- правильный длинный сервисный ramp BLD_05 к D3;\n"
        "- пространственные резервы лаборатории, ЛОС, ДГУ/UPS и HVAC/теплоснабжения;\n"
        "- предварительная safety/Ex coordination zone.\n\n"
        "## Числовой QA\n\n"
        f"- road_building_clashes: `{acceptance['road_building_clashes']}`\n"
        f"- open_external_critical_clashes: `{acceptance['open_external_critical_clashes']}`\n"
        f"- terrain_above_road_points: `{acceptance['terrain_above_road_points']}`\n"
        f"- non_adjacent_road_triangle_self_intersections: `{acceptance['non_adjacent_road_triangle_self_intersections']}`\n"
        f"- duplicated_top_faces: `{acceptance['duplicated_top_faces']}`\n"
        f"- non_manifold_edges: `{acceptance['non_manifold_edges']}`\n"
        f"- BLD_05 service ramp grade: `{acceptance['bld05_ramp_grade_pct']:.3f}%`\n\n"
        "Открытые vendor/survey/process/safety hold points перечислены в QA JSON и не скрыты моделью.\n",
        encoding="utf-8",
    )

    manifest = {
        "revision": "A.1/Rev.P5 Integrated pre-FEED Masterplan",
        "status": "CONTROLLED_PRE_FEED_NOT_FOR_CONSTRUCTION",
        "source_immutable_commit_revp2": "2af60d5b22917bf28f24685e42d9d83f519524f9",
        "source_revp2_sha256": "cb26e1ac38f7919c522d4d289d952ed3a5e543e5cec3759ed4a3ea96e8f278fd",
        "build_code_commit": os.environ.get("GITHUB_SHA", "local"),
        "build_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "files": {},
    }
    for path in [ROOT / name for name in CORE] + [visual_path, sheet, readme]:
        manifest["files"][path.name] = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
    manifest_path = ROOT / "26_RevP5_Version_Manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    targets = [
        *[ROOT / name for name in CORE], visual_path, sheet, readme, manifest_path,
        *sorted(PNG.glob("*.png")), *sorted(COMPARE.glob("*.png")),
    ]
    sums = ROOT / "26_SHA256SUMS_RevP5.txt"
    sums.write_text("\n".join(f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in targets) + "\n", encoding="utf-8")

    archive = ROOT / "26_Комплект_A1_RevP5_Integrated_preFEED.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and path != archive and path.name != "26_Release_SHA256_RevP5.txt":
                package.write(path, path.relative_to(ROOT))
    with zipfile.ZipFile(archive) as package:
        bad = package.testzip()
        if bad is not None:
            raise RuntimeError(f"Corrupt ZIP member: {bad}")

    release = ROOT / "26_Release_SHA256_RevP5.txt"
    release.write_text(
        f"{sha256_file(archive)}  {archive.name}\n"
        f"{sha256_file(ROOT / CORE[0])}  {CORE[0]}\n"
        f"{sha256_file(ROOT / CORE[1])}  {CORE[1]}\n"
        f"{sha256_file(ROOT / CORE[2])}  {CORE[2]}\n"
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    print("REV_P5_INTEGRATED_PACKAGE_PASS")


if __name__ == "__main__":
    main()
