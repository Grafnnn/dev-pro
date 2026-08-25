#!/usr/bin/env python3
"""Apply the transparent final Rev.P5 station-surface/TIN delta."""

from pathlib import Path
import subprocess


REPOSITORY = Path(__file__).resolve().parents[1]
PATCH = Path(__file__).with_suffix(".diff")


def main() -> None:
    if not PATCH.is_file():
        raise RuntimeError(f"Missing controlled patch asset: {PATCH}")
    subprocess.run(
        ["git", "apply", "--check", str(PATCH)],
        cwd=REPOSITORY,
        check=True,
    )
    subprocess.run(
        ["git", "apply", str(PATCH)],
        cwd=REPOSITORY,
        check=True,
    )
    print("REV_P5_CONTINUOUS_STATION_SURFACE_PATCHED")


if __name__ == "__main__":
    main()
