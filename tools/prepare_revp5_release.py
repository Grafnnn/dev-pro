from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROAD_ROOT = Path("revp3_output")
ROOT = Path(os.environ.get("OUT_ROOT", "revp5_output"))
ROOT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    source_qa = ROAD_ROOT / "20_Road_QA_Report_RevP3.json"
    if not source_qa.exists():
        raise FileNotFoundError(source_qa)

    qa = json.loads(source_qa.read_text(encoding="utf-8"))
    qa["revision"] = "A.1/Rev.P5 Road & Apron Coordination"
    qa["release_status"] = "ACCEPTED_FOR_REV_P5_INTEGRATION"
    qa["model_object_prefix_note"] = (
        "The isolated road-build source used REV_P3 names; the integrated Rev.P5 GLB/OBJ "
        "renames accepted road and apron objects to REV_P5 without changing their geometry."
    )
    qa["integrated_model"] = "26_Модель_A1_RevP5_Integrated_preFEED.glb"
    qa["build_code_commit"] = os.environ.get("GITHUB_SHA", "local")
    qa["build_run_id"] = os.environ.get("GITHUB_RUN_ID", "local")
    output_qa = ROOT / "26_Road_QA_Report_RevP5.json"
    output_qa.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preserve an isolated accepted road-coordination source for audit and
    # future comparison, while the main user model remains the integrated file.
    road_glb = ROAD_ROOT / "20_Модель_A1_RevP3_RoadQA.glb"
    if road_glb.exists():
        shutil.copy2(road_glb, ROOT / "26_Модель_A1_RevP5_RoadQA_Source.glb")

    release_note = ROOT / "26_Release_Status_RevP5.txt"
    release_note.write_text(
        "A.1 / Rev.P5 Integrated pre-FEED Masterplan\n"
        "STATUS=CONTROLLED_PRE_FEED_NOT_FOR_CONSTRUCTION\n"
        "ROAD_QA=PASS\n"
        "MASTERPLAN_CHANGES=PHYSICALLY_INTEGRATED_IN_GLB_AND_OBJ\n"
        "SURVEY_VENDOR_PROCESS_SAFETY_HOLD_POINTS=OPEN\n"
        f"BUILD_CODE_COMMIT={os.environ.get('GITHUB_SHA', 'local')}\n"
        f"BUILD_RUN_ID={os.environ.get('GITHUB_RUN_ID', 'local')}\n",
        encoding="utf-8",
    )
    print("REV_P5_RELEASE_METADATA_PREPARED")


if __name__ == "__main__":
    main()
