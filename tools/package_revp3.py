from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path(os.environ.get("OUT_ROOT", "revp3_output"))
PNG_DIR = ROOT / "qa_png"
COMPARE_DIR = ROOT / "qa_compare"
COMPARE_DIR.mkdir(parents=True, exist_ok=True)

CORE_NAMES = [
    "20_Модель_A1_RevP3_RoadQA.glb",
    "20_Модель_A1_RevP3_RoadQA.obj",
    "20_Road_QA_Report_RevP3.json",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def image_metrics(path: Path) -> dict:
    with Image.open(path).convert("RGB") as image:
        stat = ImageStat.Stat(image)
        extrema = image.getextrema()
        channel_ranges = [maximum - minimum for minimum, maximum in extrema]
        variance = statistics.mean(stat.var)
        return {
            "size_px": [image.width, image.height],
            "variance": float(variance),
            "channel_ranges": channel_ranges,
            "nonblank": bool(variance > 15.0 and max(channel_ranges) > 25),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }


def build_comparisons() -> list[dict]:
    before = sorted(PNG_DIR.glob("*_BEFORE_RevP2.png"))
    after = sorted(PNG_DIR.glob("*_AFTER_RevP3.png"))
    before_map = {p.name.replace("_BEFORE_RevP2.png", ""): p for p in before}
    after_map = {p.name.replace("_AFTER_RevP3.png", ""): p for p in after}
    keys = sorted(set(before_map) & set(after_map))
    if len(keys) != 10:
        raise RuntimeError(f"Expected 10 visual QA camera pairs, found {len(keys)}")

    label_font = font(30)
    title_font = font(22)
    pairs = []
    for key in keys:
        before_path = before_map[key]
        after_path = after_map[key]
        before_metrics = image_metrics(before_path)
        after_metrics = image_metrics(after_path)
        if not before_metrics["nonblank"] or not after_metrics["nonblank"]:
            raise RuntimeError(f"Blank/near-blank QA render: {key}")
        with Image.open(before_path).convert("RGB") as left, Image.open(after_path).convert("RGB") as right:
            left = left.resize((1200, 675), Image.Resampling.LANCZOS)
            right = right.resize((1200, 675), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (2400, 745), (241, 244, 246))
            canvas.paste(left, (0, 70))
            canvas.paste(right, (1200, 70))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, 1200, 70), fill=(42, 52, 61))
            draw.rectangle((1200, 0, 2400, 70), fill=(19, 73, 96))
            draw.text((32, 17), "ДО — A.1 / Rev.P2", font=label_font, fill="white")
            draw.text((1232, 17), "ПОСЛЕ — A.1 / Rev.P3", font=label_font, fill="white")
            draw.text((930, 718), key.replace("20_QA_", ""), font=title_font, fill=(34, 44, 52))
            output = COMPARE_DIR / (key + "_COMPARE.png")
            canvas.save(output, optimize=True)
        pairs.append(
            {
                "camera_id": key.replace("20_QA_", ""),
                "before": {"file": before_path.name, **before_metrics},
                "after": {"file": after_path.name, **after_metrics},
                "comparison": {
                    "file": output.name,
                    "size_bytes": output.stat().st_size,
                    "sha256": sha256_file(output),
                },
            }
        )
    return pairs


def build_contact_sheet(compare_files: list[Path]) -> Path:
    thumb_w, thumb_h = 960, 298
    columns = 2
    rows = (len(compare_files) + columns - 1) // columns
    header_h = 90
    canvas = Image.new("RGB", (columns * thumb_w, header_h + rows * thumb_h), (235, 239, 242))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas.width, header_h), fill=(19, 73, 96))
    draw.text((36, 22), "A.1 / Rev.P3 — контрольная ведомость геометрии дорог и примыканий", font=font(30), fill="white")
    for index, path in enumerate(compare_files):
        with Image.open(path).convert("RGB") as image:
            image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            x0 = (index % columns) * thumb_w
            y0 = header_h + (index // columns) * thumb_h
            x = x0 + (thumb_w - image.width) // 2
            y = y0 + (thumb_h - image.height) // 2
            canvas.paste(image, (x, y))
    output = ROOT / "20_RevP3_Visual_QA_ContactSheet.jpg"
    canvas.save(output, quality=92, subsampling=0)
    return output


def write_readme(qa: dict) -> Path:
    acceptance = qa["acceptance"]
    lines = [
        "# A.1 / Rev.P3 Road & Apron Coordination",
        "",
        "## Назначение",
        "",
        "Редакция исправляет дороги D1–D6, дорожные слои и сервисные примыкания без перемещения зданий, оборудования, резервуаров и технологических сетей.",
        "",
        "## Итог автоматического контроля",
        "",
        f"- Открытые критические наружные коллизии: **{acceptance['open_external_critical_clashes']}**",
        f"- Максимальное пересечение дорожного слоя со зданием: **{acceptance['maximum_layer_building_intersection_m2']:.6f} м²**",
        f"- Максимальный продольный уклон: **{acceptance['maximum_longitudinal_grade_pct']:.3f}%**",
        f"- Минимальный горизонтальный радиус: **{acceptance['minimum_horizontal_radius_m']:.3f} м**",
        f"- Максимальный разрыв на стыке: **{acceptance['maximum_junction_gap_m']:.6f} м**",
        f"- Максимальная вертикальная ступень: **{max(acceptance['maximum_junction_vertical_step_m'], acceptance['maximum_road_apron_vertical_step_m']):.6f} м**",
        f"- Статус: **{acceptance['status']}**",
        "",
        "## Основные файлы",
        "",
        "- `20_Модель_A1_RevP3_RoadQA.glb` — основная модель.",
        "- `20_Модель_A1_RevP3_RoadQA.obj` — контрольный обменный формат.",
        "- `20_Road_QA_Report_RevP3.json` — числовой QA.",
        "- `20_RevP3_Version_Manifest.json` — версия и состав выдачи.",
        "- `20_SHA256SUMS_RevP3.txt` — контрольные суммы файлов комплекта.",
        "- `qa_png/` и `qa_compare/` — обязательные виды до/после с одинаковыми камерами.",
        "",
        "## Ограничение",
        "",
        "Swept-path выполнен как консервативная 2D-проверка при отсутствии утверждённого шаблона расчётного автомобиля. На стадии П требуется подтверждение AutoTURN или эквивалентом.",
    ]
    output = ROOT / "20_README_RevP3.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main():
    for name in CORE_NAMES:
        path = ROOT / name
        if not path.exists():
            raise FileNotFoundError(path)

    qa_path = ROOT / "20_Road_QA_Report_RevP3.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    if qa.get("acceptance", {}).get("status") != "PASS":
        raise RuntimeError("Rev.P3 numerical QA is not PASS")
    if qa["acceptance"]["open_external_critical_clashes"] != 0:
        raise RuntimeError("Critical clashes remain")

    pairs = build_comparisons()
    compare_files = sorted(COMPARE_DIR.glob("*_COMPARE.png"))
    contact_sheet = build_contact_sheet(compare_files)
    readme = write_readme(qa)

    visual_manifest = {
        "revision": "A.1/Rev.P3 Road & Apron Coordination",
        "camera_pairs": pairs,
        "camera_pair_count": len(pairs),
        "all_before_after_nonblank": all(p["before"]["nonblank"] and p["after"]["nonblank"] for p in pairs),
        "contact_sheet": {
            "file": contact_sheet.name,
            "size_bytes": contact_sheet.stat().st_size,
            "sha256": sha256_file(contact_sheet),
        },
    }
    visual_path = ROOT / "20_Visual_QA_Report_RevP3.json"
    visual_path.write_text(json.dumps(visual_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    version_manifest = {
        "revision": "A.1/Rev.P3 Road & Apron Coordination",
        "source_revision": "A.1/Rev.P2 Exterior Coordination & Visual QA",
        "source_file": "20_Модель_A1_RevP2_ExteriorQA.glb",
        "source_immutable_commit": "2af60d5b22917bf28f24685e42d9d83f519524f9",
        "source_sha256": "cb26e1ac38f7919c522d4d289d952ed3a5e543e5cec3759ed4a3ea96e8f278fd",
        "build_code_commit": os.environ.get("GITHUB_SHA", "local"),
        "build_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "acceptance_status": qa["acceptance"]["status"],
        "open_external_critical_clashes": qa["acceptance"]["open_external_critical_clashes"],
        "files": {},
        "note": "Buildings, equipment, tanks and process networks remain fixed; only road/apron and local site-interface geometry was revised.",
    }
    for path in [ROOT / name for name in CORE_NAMES] + [visual_path, contact_sheet, readme]:
        version_manifest["files"][path.name] = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
    version_path = ROOT / "20_RevP3_Version_Manifest.json"
    version_path.write_text(json.dumps(version_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    checksum_targets = [
        ROOT / "20_Модель_A1_RevP3_RoadQA.glb",
        ROOT / "20_Модель_A1_RevP3_RoadQA.obj",
        qa_path,
        visual_path,
        version_path,
        readme,
        contact_sheet,
        *sorted(PNG_DIR.glob("*.png")),
        *sorted(COMPARE_DIR.glob("*.png")),
    ]
    checksum_path = ROOT / "20_SHA256SUMS_RevP3.txt"
    checksum_path.write_text(
        "\n".join(f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in checksum_targets) + "\n",
        encoding="utf-8",
    )

    zip_path = ROOT / "20_Комплект_A1_RevP3_RoadQA.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and path != zip_path and not path.name.startswith("20_Release_SHA256"):
                archive.write(path, path.relative_to(ROOT))

    release_hash_path = ROOT / "20_Release_SHA256_RevP3.txt"
    release_hash_path.write_text(
        f"{sha256_file(zip_path)}  {zip_path.name}\n"
        f"{sha256_file(ROOT / '20_Модель_A1_RevP3_RoadQA.glb')}  20_Модель_A1_RevP3_RoadQA.glb\n"
        f"{sha256_file(ROOT / '20_Модель_A1_RevP3_RoadQA.obj')}  20_Модель_A1_RevP3_RoadQA.obj\n"
        f"{sha256_file(qa_path)}  20_Road_QA_Report_RevP3.json\n",
        encoding="utf-8",
    )
    print("REV_P3_PACKAGE_PASS")


if __name__ == "__main__":
    main()
