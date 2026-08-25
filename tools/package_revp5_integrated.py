from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
PNG = ROOT / "qa_png"
COMPARE = ROOT / "qa_compare"
COMPARE.mkdir(parents=True, exist_ok=True)

REVISION = "A.1/Rev.P5 Integrated pre-FEED Masterplan"
ARCHIVE_NAME = "26_Комплект_A1_RevP5_Integrated_preFEED.zip"
MANIFEST_NAME = "26_RevP5_Version_Manifest.json"
MEMBER_SUMS_NAME = "26_SHA256SUMS_RevP5.txt"
DETACHED_SUMS_NAME = "26_Release_SHA256_RevP5.txt"
ENGINEERING_REVIEW_NAME = "26_Engineering_Visual_Review_RevP5.json"

REPRODUCIBLE_SCRIPT_MINIMUM = {
    "integrate_revp5_masterplan.py",
    "revp5_blender_meshqa.py",
    "render_revp5_masterplan_qa.py",
    "prepare_revp5_release.py",
    "package_revp5_integrated.py",
}

ENGINEERING_VISUAL_CHECKS = (
    "camera_pair_identity",
    "overall_site_layout_and_feature_visibility",
    "terrain_road_and_apron_seating",
    "d3_d5_junction_continuity_and_overlap",
    "bld05_to_d3_service_ramp",
    "masterplan_additions_clearance_and_collisions",
)


def build_code_commit() -> str:
    override = os.environ.get("BUILD_CODE_COMMIT")
    if override:
        return override
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local-unversioned"

CORE = [
    "26_Модель_A1_RevP5_Integrated_preFEED.glb",
    "26_Модель_A1_RevP5_Integrated_preFEED.obj",
    "26_Integrated_QA_Report_RevP5.json",
    "26_Road_QA_Report_RevP5.json",
    "26_Blender_Road_Mesh_QA_RevP5.json",
    "26_Masterplan_Change_Register_RevP5.json",
    "26_Masterplan_Change_Register_RevP5.csv",
    "26_Release_Status_RevP5.txt",
]

CHANGE_REGISTER_SCHEMA = (
    "Object_Name",
    "Category",
    "Data_Status",
    "Area_m2",
    "Bounds_XY",
    "Description",
    "Spatial_Role",
)

REQUIRED_MASTERPLAN_FEATURES = (
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
)

UNINTENDED_CACHE_DIRECTORY_NAMES = {
    "__pycache__",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
UNINTENDED_CACHE_FILE_NAMES = {
    ".coverage",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
UNINTENDED_CACHE_FILE_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def relative_name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def file_record(path: Path, role: str | None = None) -> dict:
    record = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
    if role is not None:
        record["role"] = role
    return record


def validate_register_rows(rows, source: str) -> list[dict]:
    if not isinstance(rows, list):
        raise RuntimeError(f"{source} must contain a JSON array of change-register rows")
    if len(rows) != len(REQUIRED_MASTERPLAN_FEATURES):
        raise RuntimeError(
            f"{source} must contain exactly {len(REQUIRED_MASTERPLAN_FEATURES)} rows; "
            f"found {len(rows)}"
        )

    expected_schema = set(CHANGE_REGISTER_SCHEMA)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError(f"{source} row {index + 1} is not an object")
        actual_schema = set(row)
        if actual_schema != expected_schema:
            raise RuntimeError(
                f"{source} row {index + 1} schema mismatch; "
                f"missing={sorted(expected_schema - actual_schema)}, "
                f"extra={sorted(actual_schema - expected_schema)}"
            )

    names = [row["Object_Name"] for row in rows]
    if tuple(names) != REQUIRED_MASTERPLAN_FEATURES:
        missing = sorted(set(REQUIRED_MASTERPLAN_FEATURES) - set(names))
        extra = sorted(set(names) - set(REQUIRED_MASTERPLAN_FEATURES))
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise RuntimeError(
            f"{source} feature sequence does not match the exact Rev.P5 register; "
            f"missing={missing}, extra={extra}, duplicates={duplicates}, names={names}"
        )
    return rows


def validate_change_register(qa: dict) -> None:
    json_path = ROOT / "26_Masterplan_Change_Register_RevP5.json"
    csv_path = ROOT / "26_Masterplan_Change_Register_RevP5.csv"

    register = validate_register_rows(
        json.loads(json_path.read_text(encoding="utf-8")),
        json_path.name,
    )
    qa_required = qa.get("required_features")
    if qa_required != list(REQUIRED_MASTERPLAN_FEATURES):
        raise RuntimeError(
            "Integrated QA required_features does not match the exact 19-feature Rev.P5 register"
        )
    qa_register = validate_register_rows(
        qa.get("masterplan_changes"),
        "26_Integrated_QA_Report_RevP5.json masterplan_changes",
    )
    if qa_register != register:
        raise RuntimeError(
            "JSON change register does not exactly match integrated QA masterplan_changes"
        )
    if qa.get("missing_required_features") != []:
        raise RuntimeError("Integrated QA reports missing required Rev.P5 features")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CHANGE_REGISTER_SCHEMA:
            raise RuntimeError(
                f"{csv_path.name} header must be exactly {list(CHANGE_REGISTER_SCHEMA)}; "
                f"found {reader.fieldnames}"
            )
        csv_rows = list(reader)
    if len(csv_rows) != len(REQUIRED_MASTERPLAN_FEATURES):
        raise RuntimeError(
            f"{csv_path.name} must contain exactly {len(REQUIRED_MASTERPLAN_FEATURES)} rows; "
            f"found {len(csv_rows)}"
        )
    csv_names = [row["Object_Name"] for row in csv_rows]
    if tuple(csv_names) != REQUIRED_MASTERPLAN_FEATURES:
        raise RuntimeError(
            f"{csv_path.name} feature sequence does not match the exact Rev.P5 register: {csv_names}"
        )

    for index, (csv_row, json_row) in enumerate(zip(csv_rows, register), start=1):
        normalized = dict(csv_row)
        try:
            normalized["Area_m2"] = (
                None if normalized["Area_m2"] == "" else float(normalized["Area_m2"])
            )
            normalized["Bounds_XY"] = (
                None if normalized["Bounds_XY"] == "" else json.loads(normalized["Bounds_XY"])
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{csv_path.name} row {index} contains invalid numeric or Bounds_XY data"
            ) from exc
        if normalized != json_row:
            raise RuntimeError(
                f"{csv_path.name} row {index} does not exactly match the JSON change register"
            )


def get_font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
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
    if len(before) != 7 or len(after) != 7 or set(before) != set(after):
        raise RuntimeError(
            "Expected exactly 7 matching identical-camera before/after pairs; "
            f"before={sorted(before)}, after={sorted(after)}"
        )
    keys = sorted(before)
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
    if len(files) != 7:
        raise RuntimeError(f"Expected 7 comparison images for contact sheet, got {len(files)}")
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


def review_binding(pairs: list[dict], visual_path: Path, sheet: Path) -> dict:
    model = ROOT / CORE[0]
    return {
        "integrated_model": {"file": model.name, **file_record(model)},
        "visual_qa_report": {"file": visual_path.name, **file_record(visual_path)},
        "contact_sheet": {"file": sheet.name, **file_record(sheet)},
        "camera_comparisons": [
            {
                "camera": item["camera"],
                "file": f"qa_compare/{item['comparison']['file']}",
                "size_bytes": item["comparison"]["size_bytes"],
                "sha256": item["comparison"]["sha256"],
            }
            for item in pairs
        ],
    }


def write_review_template(path: Path, binding: dict) -> None:
    template = {
        "schema_version": 1,
        "revision": REVISION,
        "status": "PENDING",
        "reviewer": {"name": "", "role": ""},
        "reviewed_at_utc": "",
        "reviewed_pair_count": len(binding["camera_comparisons"]),
        "evidence": binding,
        "required_checks": {
            check: {"status": "PENDING", "comment": ""}
            for check in ENGINEERING_VISUAL_CHECKS
        },
        "camera_reviews": [
            {
                "camera": item["camera"],
                "comparison_file": item["file"],
                "comparison_sha256": item["sha256"],
                "status": "PENDING",
                "findings": [],
            }
            for item in binding["camera_comparisons"]
        ],
        "open_blocking_findings": [
            "Complete the engineering visual review and replace PENDING values before release packaging."
        ],
    }
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_engineering_review(path: Path, binding: dict) -> dict:
    if not path.exists():
        write_review_template(path, binding)
        raise RuntimeError(
            f"Engineering visual review is required; complete generated template {path} and rerun packaging"
        )
    review = json.loads(path.read_text(encoding="utf-8"))
    if review.get("schema_version") != 1:
        raise RuntimeError("Engineering visual review schema_version must be 1")
    if review.get("revision") != REVISION:
        raise RuntimeError("Engineering visual review revision does not match the release")
    if review.get("status") != "PASS":
        raise RuntimeError("Engineering visual review status is not PASS")

    reviewer = review.get("reviewer", {})
    if not str(reviewer.get("name", "")).strip() or not str(reviewer.get("role", "")).strip():
        raise RuntimeError("Engineering visual review requires reviewer name and role")
    reviewed_at = str(review.get("reviewed_at_utc", "")).strip()
    try:
        timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("Engineering visual review requires an ISO-8601 reviewed_at_utc") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise RuntimeError("Engineering visual review reviewed_at_utc must include a timezone")

    evidence = review.get("evidence", {})
    for key in ("integrated_model", "visual_qa_report", "contact_sheet"):
        expected = binding[key]
        actual = evidence.get(key, {})
        if actual.get("file") != expected["file"] or actual.get("sha256") != expected["sha256"]:
            raise RuntimeError(f"Engineering visual review is stale for {key}")

    expected_cameras = {item["camera"]: item for item in binding["camera_comparisons"]}
    evidence_cameras = evidence.get("camera_comparisons", [])
    evidence_map = {item.get("camera"): item for item in evidence_cameras if isinstance(item, dict)}
    if len(evidence_cameras) != len(evidence_map) or set(evidence_map) != set(expected_cameras):
        raise RuntimeError("Engineering visual review evidence does not cover the exact seven cameras")
    for camera, expected in expected_cameras.items():
        actual = evidence_map[camera]
        if actual.get("file") != expected["file"] or actual.get("sha256") != expected["sha256"]:
            raise RuntimeError(f"Engineering visual review evidence is stale for camera {camera}")

    checks = review.get("required_checks", {})
    for check in ENGINEERING_VISUAL_CHECKS:
        value = checks.get(check, {})
        status = value.get("status") if isinstance(value, dict) else value
        if status != "PASS":
            raise RuntimeError(f"Engineering visual review check is not PASS: {check}")

    camera_reviews = review.get("camera_reviews", [])
    camera_map = {item.get("camera"): item for item in camera_reviews if isinstance(item, dict)}
    if len(camera_reviews) != len(camera_map) or set(camera_map) != set(expected_cameras):
        raise RuntimeError("Engineering visual review decisions do not cover the exact seven cameras")
    for camera, expected in expected_cameras.items():
        item = camera_map[camera]
        if item.get("status") != "PASS":
            raise RuntimeError(f"Engineering visual review camera is not PASS: {camera}")
        if item.get("comparison_file") != expected["file"] or item.get("comparison_sha256") != expected["sha256"]:
            raise RuntimeError(f"Engineering visual review camera decision is stale: {camera}")

    if review.get("reviewed_pair_count") != len(expected_cameras):
        raise RuntimeError("Engineering visual review pair count is not 7")
    if review.get("open_blocking_findings") != []:
        raise RuntimeError("Engineering visual review has open blocking findings")
    return review


def require_reproducible_scripts() -> list[Path]:
    directory = ROOT / "reproducible_scripts"
    if not directory.is_dir():
        raise RuntimeError(f"Reproducible scripts directory is missing: {directory}")

    unintended = []
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        has_cache_directory = any(
            part in UNINTENDED_CACHE_DIRECTORY_NAMES for part in relative.parts
        )
        has_cache_filename = (
            path.name in UNINTENDED_CACHE_FILE_NAMES
            or (path.is_file() and path.suffix.lower() in UNINTENDED_CACHE_FILE_SUFFIXES)
        )
        if has_cache_directory or has_cache_filename:
            unintended.append(relative.as_posix())
    if unintended:
        raise RuntimeError(
            "Reproducible scripts contain unintended cache artifacts; clean the directory "
            "before packaging: " + ", ".join(sorted(unintended))
        )

    scripts = sorted(path for path in directory.rglob("*") if path.is_file())
    names = {path.name for path in scripts}
    missing = sorted(REPRODUCIBLE_SCRIPT_MINIMUM - names)
    if missing:
        raise RuntimeError(f"Required reproducible release scripts are missing: {missing}")
    if any(path.stat().st_size == 0 for path in scripts):
        raise RuntimeError("Reproducible scripts contain an empty file")
    return scripts


def collect_payload_files(excluded: set[Path]) -> list[Path]:
    files = sorted(path for path in ROOT.rglob("*") if path.is_file() and path not in excluded)
    if not files:
        raise RuntimeError("Release payload is empty")
    return files


def checksum_lines(paths: list[Path]) -> str:
    return "\n".join(f"{sha256_file(path)}  {relative_name(path)}" for path in sorted(paths)) + "\n"


def checksum_entries(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in entries:
            raise RuntimeError(f"Duplicate checksum entry: {name}")
        entries[name] = digest
    return entries


def main() -> None:
    source_commit = build_code_commit()
    archive = ROOT / ARCHIVE_NAME
    manifest_path = ROOT / MANIFEST_NAME
    sums = ROOT / MEMBER_SUMS_NAME
    release = ROOT / DETACHED_SUMS_NAME
    for stale in (archive, manifest_path, sums, release):
        stale.unlink(missing_ok=True)

    for name in CORE:
        path = ROOT / name
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    qa = json.loads((ROOT / "26_Integrated_QA_Report_RevP5.json").read_text(encoding="utf-8"))
    if qa.get("status") != "PASS_CONTROLLED_PRE_FEED":
        raise RuntimeError("Integrated QA is not PASS_CONTROLLED_PRE_FEED")
    if qa.get("blender_road_mesh_qa", {}).get("status") != "PASS":
        raise RuntimeError("Final Blender road-mesh QA is not PASS")
    validate_change_register(qa)
    acceptance = qa.get("acceptance", {})
    strict_numeric_gates = {
        "d3_d5_full_seam_vertical_step": acceptance.get("d3_d5_maximum_full_seam_vertical_step_m", float("inf")) <= 0.005001,
        "d3_d5_blended_grade": acceptance.get("d3_d5_blended_maximum_centerline_grade_pct", float("inf")) <= 6.000001,
        "d3_d5_resultant_surface_grade": acceptance.get("d3_d5_maximum_resultant_surface_grade_pct", float("inf")) <= 100.0 * math.hypot(0.06, 0.02) + 1.0e-6,
        "d3_d5_road_shoulder_nesting": acceptance.get("d3_d5_minimum_road_shoulder_vertical_overlap_m", -float("inf")) > 0.005,
        "d3_d5_road_shoulder_nesting_upper_bound": acceptance.get("d3_d5_maximum_road_shoulder_vertical_overlap_m", float("inf")) <= 0.25,
        "d3_d5_shoulder_subbase_nesting": acceptance.get("d3_d5_minimum_shoulder_subbase_vertical_overlap_m", -float("inf")) > 0.005,
        "d3_d5_shoulder_subbase_nesting_upper_bound": acceptance.get("d3_d5_maximum_shoulder_subbase_vertical_overlap_m", float("inf")) <= 0.12,
        "d3_d5_no_reverse_grade": acceptance.get("d3_d5_reverse_grade_sample_count", -1) == 0,
        "bay_nominal_formation_fill": acceptance.get("emergency_bay_maximum_nominal_formation_fill_m", float("inf")) <= 0.500001,
        "bay_nominal_formation_cut": acceptance.get("emergency_bay_maximum_nominal_formation_cut_m", float("inf")) <= 1.000001,
        "bay_no_unsupported_gap": acceptance.get("emergency_bay_maximum_actual_unsupported_gap_m", float("inf")) <= 1.0e-6,
        "bay_actual_foundation_cut": acceptance.get("emergency_bay_maximum_actual_foundation_cut_m", float("inf")) <= 0.950001,
        "bay_residual_ground_key_in": acceptance.get("emergency_bay_minimum_residual_ground_key_in_m", -float("inf")) >= 0.099999,
        "bay_exact_tin_ground_key_in": acceptance.get("emergency_bay_minimum_exact_tin_ground_key_in_m", -float("inf")) >= 0.099999,
        "bay_exact_tin_foundation_cut": acceptance.get("emergency_bay_maximum_exact_tin_foundation_cut_m", float("inf")) <= 0.950001,
        "bay_single_engineered_bottom_plane": acceptance.get("emergency_bay_foundation_bottom_is_single_plane") is True,
        "bay_bottom_plane_grade": acceptance.get("emergency_bay_foundation_bottom_plane_grade_pct", float("inf")) <= 6.000001,
        "bay_bottom_plane_planarity": acceptance.get("emergency_bay_foundation_bottom_planarity_residual_m", float("inf")) <= 1.0e-8,
        "bay_top_surface_affinity": acceptance.get("emergency_bay_top_affine_residual_m", float("inf")) <= 1.0e-8,
        "bay_exact_tin_coverage": acceptance.get("emergency_bay_exact_tin_coverage_delta_m2", float("inf")) <= 1.0e-6,
        "bay_exact_tin_cells_present": acceptance.get("emergency_bay_exact_tin_triangle_count", 0) > 0 and acceptance.get("emergency_bay_exact_tin_extrema_vertex_count", 0) >= 3,
        "bay_outer_foundation_watertight": acceptance.get("emergency_bay_outer_foundation_watertight") is True,
        "bay_outer_foundation_manifold": acceptance.get("emergency_bay_outer_foundation_open_or_nonmanifold_edges", -1) == 0,
        "bay_outer_foundation_connected": acceptance.get("emergency_bay_outer_foundation_connected_components", -1) == 1,
        "bay_minimum_foundation_thickness": acceptance.get("emergency_bay_minimum_actual_foundation_thickness_m", -float("inf")) >= 0.499999,
        "bay_maximum_foundation_thickness": acceptance.get("emergency_bay_maximum_actual_foundation_thickness_m", float("inf")) <= 1.050001,
        "bay_support_partition_overlap": acceptance.get("emergency_bay_support_partition_pairwise_overlap_m2", float("inf")) <= 1.0e-6,
        "bay_support_partition_coverage": acceptance.get("emergency_bay_support_partition_coverage_gap_m2", float("inf")) <= 1.0e-6,
        "bay_original_terrain_sha": acceptance.get("emergency_bay_source_terrain_sha_verified") is True,
        "heavy_haul_clearance_coordination": acceptance.get("heavy_haul_unapproved_clearance_overlap_count", -1) == 0,
    }
    failed_numeric_gates = [name for name, passed in strict_numeric_gates.items() if not passed]
    if failed_numeric_gates:
        raise RuntimeError(
            "Strict D3-D5 / emergency-bay numeric release gates failed: "
            + ", ".join(failed_numeric_gates)
        )

    for stale_comparison in COMPARE.glob("*.png"):
        stale_comparison.unlink()
    pairs = build_comparisons()
    sheet = contact_sheet(sorted(COMPARE.glob("*.png")))
    visual = {
        "revision": REVISION,
        "status": "PASS_AUTOMATED_VISUAL_EVIDENCE",
        "identical_camera_pair_count": len(pairs),
        "all_images_nonblank": all(item["before"]["nonblank"] and item["after"]["nonblank"] for item in pairs),
        "pairs": pairs,
        "contact_sheet": {"file": sheet.name, "size_bytes": sheet.stat().st_size, "sha256": sha256_file(sheet)},
    }
    visual_path = ROOT / "26_Visual_QA_Report_RevP5.json"
    visual_path.write_text(json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")

    engineering_review_path = ROOT / ENGINEERING_REVIEW_NAME
    binding = review_binding(pairs, visual_path, sheet)
    engineering_review = validate_engineering_review(engineering_review_path, binding)
    require_reproducible_scripts()

    release_note = ROOT / "26_Release_Status_RevP5.txt"
    release_lines = [
        line
        for line in release_note.read_text(encoding="utf-8").splitlines()
        if not line.startswith("ENGINEERING_VISUAL_REVIEW=")
    ]
    release_lines.append("ENGINEERING_VISUAL_REVIEW=PASS")
    release_note.write_text("\n".join(release_lines) + "\n", encoding="utf-8")

    readme = ROOT / "26_README_RevP5.md"
    acceptance = qa["acceptance"]
    road_acceptance = qa["road_acceptance_reused"]
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
        f"- D3-D5 maximum full-seam step: `{acceptance['d3_d5_maximum_full_seam_vertical_step_m']:.6f} m`\n"
        f"- D3-D5 maximum coordinated layer grade: `{acceptance['d3_d5_blended_maximum_centerline_grade_pct']:.3f}%`\n"
        f"- D3-D5 maximum resultant surface grade: `{acceptance['d3_d5_maximum_resultant_surface_grade_pct']:.3f}%`\n"
        f"- D3-D5 ROAD/SHOULDER vertical engagement min/max: `{acceptance['d3_d5_minimum_road_shoulder_vertical_overlap_m']:.6f} / {acceptance['d3_d5_maximum_road_shoulder_vertical_overlap_m']:.6f} m`\n"
        f"- D3-D5 SHOULDER/SUBBASE vertical engagement min/max: `{acceptance['d3_d5_minimum_shoulder_subbase_vertical_overlap_m']:.6f} / {acceptance['d3_d5_maximum_shoulder_subbase_vertical_overlap_m']:.6f} m`\n"
        f"- D3-D5 reverse-grade samples: `{acceptance['d3_d5_reverse_grade_sample_count']}`\n"
        f"- D3 bay nominal formation fill/cut: `{acceptance['emergency_bay_maximum_nominal_formation_fill_m']:.3f} / {acceptance['emergency_bay_maximum_nominal_formation_cut_m']:.3f} m`\n"
        f"- D3 bay unsupported foundation gap: `{acceptance['emergency_bay_maximum_actual_unsupported_gap_m']:.9f} m`\n"
        f"- D3 bay actual foundation cut / residual key-in: `{acceptance['emergency_bay_maximum_actual_foundation_cut_m']:.3f} / {acceptance['emergency_bay_minimum_residual_ground_key_in_m']:.3f} m`\n"
        f"- D3 bay exact clipped-TIN cells / extrema vertices: `{acceptance['emergency_bay_exact_tin_triangle_count']} / {acceptance['emergency_bay_exact_tin_extrema_vertex_count']}`\n"
        f"- D3 bay exact TIN coverage delta: `{acceptance['emergency_bay_exact_tin_coverage_delta_m2']:.9f} m²`\n"
        f"- D3 bay single foundation-plane grade / planarity residual: `{acceptance['emergency_bay_foundation_bottom_plane_grade_pct']:.3f}% / {acceptance['emergency_bay_foundation_bottom_planarity_residual_m']:.9f} m`\n"
        f"- D3 bay top-surface affine fit residual: `{acceptance['emergency_bay_top_affine_residual_m']:.9f} m`\n"
        f"- D3 bay actual foundation thickness min/max: `{acceptance['emergency_bay_minimum_actual_foundation_thickness_m']:.3f} / {acceptance['emergency_bay_maximum_actual_foundation_thickness_m']:.3f} m`\n"
        f"- Blender BVH road self-intersections: `{acceptance['blender_non_adjacent_road_triangle_self_intersections']}`\n"
        f"- maximum road grade: `{road_acceptance['maximum_longitudinal_grade_pct']:.3f}%`\n"
        f"- minimum horizontal radius: `{road_acceptance['minimum_horizontal_radius_m']:.3f} m`\n"
        f"- BLD_05 service ramp grade: `{acceptance['bld05_ramp_grade_pct']:.3f}%`\n\n"
        "## Инженерный визуальный контроль\n\n"
        f"- статус: `{engineering_review['status']}`\n"
        f"- reviewer: `{engineering_review['reviewer']['name']}` / `{engineering_review['reviewer']['role']}`\n"
        f"- reviewed_at_utc: `{engineering_review['reviewed_at_utc']}`\n"
        f"- проверено одинаковых пар камер: `{engineering_review['reviewed_pair_count']}`\n"
        "- открытые блокирующие замечания: `0`\n\n"
        "Открытые vendor/survey/process/safety hold points перечислены в QA JSON и не скрыты моделью.\n",
        encoding="utf-8",
    )

    control_files = {archive, manifest_path, sums, release}
    payload_files = collect_payload_files(control_files)
    payload_records = {relative_name(path): file_record(path) for path in payload_files}
    archive_members = sorted([*payload_records, MANIFEST_NAME, MEMBER_SUMS_NAME])
    manifest = {
        "schema_version": 2,
        "revision": REVISION,
        "status": "CONTROLLED_PRE_FEED_NOT_FOR_CONSTRUCTION",
        "source_immutable_commit_revp2": "2af60d5b22917bf28f24685e42d9d83f519524f9",
        "source_revp2_sha256": "cb26e1ac38f7919c522d4d289d952ed3a5e543e5cec3759ed4a3ea96e8f278fd",
        "build_code_commit": source_commit,
        "build_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "engineering_visual_review": {
            "file": engineering_review_path.name,
            "status": engineering_review["status"],
            "reviewer": engineering_review["reviewer"],
            "reviewed_at_utc": engineering_review["reviewed_at_utc"],
            "sha256": sha256_file(engineering_review_path),
        },
        "archive": {
            "file": ARCHIVE_NAME,
            "member_count": len(archive_members),
            "members": archive_members,
            "excluded_by_design": [
                ARCHIVE_NAME,
                DETACHED_SUMS_NAME,
            ],
        },
        "checksum_policy": {
            "manifest_files": "SHA-256 covers every payload member; manifest and member checksum are inventoried separately to avoid self-reference.",
            "member_checksum": f"{MEMBER_SUMS_NAME} covers every ZIP member except itself.",
            "detached_checksum": f"{DETACHED_SUMS_NAME} is outside the ZIP and covers the ZIP plus every other release file except itself.",
        },
        "files": payload_records,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    checksum_targets = sorted([*payload_files, manifest_path])
    sums.write_text(checksum_lines(checksum_targets), encoding="utf-8")

    package_targets = sorted([*checksum_targets, sums])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in package_targets:
            package.write(path, relative_name(path))
    with zipfile.ZipFile(archive) as package:
        bad = package.testzip()
        if bad is not None:
            raise RuntimeError(f"Corrupt ZIP member: {bad}")
        names = set(package.namelist())
        expected_names = {relative_name(path) for path in package_targets}
        if names != expected_names:
            raise RuntimeError(
                f"ZIP membership mismatch; missing={sorted(expected_names - names)}, extra={sorted(names - expected_names)}"
            )
        if DETACHED_SUMS_NAME in names or ARCHIVE_NAME in names:
            raise RuntimeError("ZIP must not contain itself or its detached release checksum")

    member_entries = checksum_entries(sums)
    expected_checksum_names = {relative_name(path) for path in checksum_targets}
    if set(member_entries) != expected_checksum_names:
        raise RuntimeError("Member SHA256 file does not cover the complete non-self archive content")
    for path in checksum_targets:
        if member_entries[relative_name(path)] != sha256_file(path):
            raise RuntimeError(f"Member SHA256 mismatch: {relative_name(path)}")

    detached_targets = sorted(path for path in ROOT.rglob("*") if path.is_file() and path != release)
    release.write_text(checksum_lines(detached_targets), encoding="utf-8")
    detached_entries = checksum_entries(release)
    if set(detached_entries) != {relative_name(path) for path in detached_targets}:
        raise RuntimeError("Detached release checksum does not cover the complete release composition")
    if detached_entries.get(archive.name) != sha256_file(archive):
        raise RuntimeError("Detached release checksum does not match the ZIP")
    print("REV_P5_INTEGRATED_PACKAGE_PASS")


if __name__ == "__main__":
    main()
