from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

MODULE_PATH = Path("tools/build_revp3_roadqa.py")
spec = importlib.util.spec_from_file_location("revp3_builder", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def radius_details(path: np.ndarray, spacing: float = 2.5) -> dict:
    sampled = module.resample_xy(path, spacing)
    rows = []
    for index in range(1, len(sampled) - 1):
        radius = module.circle_radius(sampled[index - 1, :2], sampled[index, :2], sampled[index + 1, :2])
        if np.isfinite(radius):
            rows.append(
                {
                    "radius_m": float(radius),
                    "index": int(index),
                    "previous": sampled[index - 1, :2].tolist(),
                    "point": sampled[index, :2].tolist(),
                    "next": sampled[index + 1, :2].tolist(),
                }
            )
    rows.sort(key=lambda row: row["radius_m"])
    return {
        "sampled_points": int(len(sampled)),
        "minimum": rows[0] if rows else None,
        "smallest_20": rows[:20],
    }


def main() -> None:
    paths = module.build_paths()
    report = {}
    for code, road_paths in paths.items():
        report[code] = [radius_details(path) for path in road_paths]
    output = Path("revp3_path_diagnostics.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
