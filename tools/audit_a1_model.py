from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import requests
import trimesh
from pygltflib import GLTF2


def safe_name(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def main() -> None:
    source_url = os.environ["SOURCE_ZIP_URL"]
    work = Path("work")
    work.mkdir(exist_ok=True)
    archive = work / "stage7.zip"
    with requests.get(source_url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with archive.open("wb") as f:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"Downloaded {archive.stat().st_size} bytes")

    extract = work / "src"
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
        print("ZIP entries:")
        for name in zf.namelist():
            print("  ", name)

    glbs = sorted(extract.rglob("*.glb"), key=lambda p: p.stat().st_size, reverse=True)
    if not glbs:
        raise RuntimeError("No GLB found in archive")
    glb = glbs[0]
    print(f"Using GLB: {glb} ({glb.stat().st_size} bytes)")

    gltf = GLTF2().load_binary(str(glb))
    print(f"gltf nodes={len(gltf.nodes or [])}, meshes={len(gltf.meshes or [])}, materials={len(gltf.materials or [])}")
    for index, node in enumerate(gltf.nodes or []):
        name = safe_name(node.name)
        extras = node.extras if node.extras else None
        if index < 300 or extras:
            print(f"NODE {index:04d} mesh={node.mesh} name={name!r} extras={json.dumps(extras, ensure_ascii=False) if extras else ''}")

    scene = trimesh.load(str(glb), force="scene", process=False)
    if not isinstance(scene, trimesh.Scene):
        scene = trimesh.Scene(scene)
    print("SCENE BOUNDS", scene.bounds.tolist())
    print("SCENE EXTENTS", scene.extents.tolist())
    print("GEOMETRY COUNT", len(scene.geometry))

    report = []
    categories = Counter()
    helper_pattern = re.compile(r"axis|helper|guide|clash|clearance|reserve|boundary|contour|line|route|path|rfi|temp|debug|ос[ьи]|вспом|границ|резерв|траектор|коллиз", re.I)
    road_pattern = re.compile(r"road|drive|serp|loop|access|fire|проезд|дорог|серпант|въезд|выезд", re.I)
    terrain_pattern = re.compile(r"terrain|ground|relief|terrace|slope|land|рельеф|земл|террас|откос", re.I)
    wall_pattern = re.compile(r"retaining|wall|подпор|стен", re.I)
    utility_pattern = re.compile(r"pipe|utility|network|duct|cable|water|sewer|gas|oil|сеть|труб|кабел|вод|канал|газ|масл", re.I)

    for name, geom in scene.geometry.items():
        bounds = np.asarray(geom.bounds, dtype=float)
        extents = np.asarray(geom.extents, dtype=float)
        faces = int(len(getattr(geom, "faces", [])))
        vertices = int(len(getattr(geom, "vertices", [])))
        low = name.lower()
        if helper_pattern.search(name):
            category = "helper"
        elif road_pattern.search(name):
            category = "road"
        elif terrain_pattern.search(name):
            category = "terrain"
        elif wall_pattern.search(name):
            category = "wall"
        elif utility_pattern.search(name):
            category = "utility"
        else:
            category = "other"
        categories[category] += 1
        report.append({
            "name": name,
            "category": category,
            "vertices": vertices,
            "faces": faces,
            "bounds": bounds.round(4).tolist(),
            "extents": extents.round(4).tolist(),
            "watertight": bool(getattr(geom, "is_watertight", False)),
            "volume": float(getattr(geom, "volume", 0.0)),
        })

    report.sort(key=lambda r: (r["category"], -r["faces"], r["name"]))
    print("CATEGORY COUNTS", dict(categories))
    for item in report:
        print("GEOM", json.dumps(item, ensure_ascii=False))

    out = Path("audit")
    out.mkdir(exist_ok=True)
    (out / "model_audit.json").write_text(json.dumps({
        "glb": str(glb),
        "bounds": np.asarray(scene.bounds).tolist(),
        "extents": np.asarray(scene.extents).tolist(),
        "categories": dict(categories),
        "geometry": report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AUDIT_DONE")


if __name__ == "__main__":
    main()
