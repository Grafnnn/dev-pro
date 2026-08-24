from pathlib import Path

path = Path("tools/build_revp3_roadqa.py")
text = path.read_text(encoding="utf-8")

# BLD_05 is located on the upper pyrolysis terrace.  The nearest planar road
# polygon in the automatic apron search is the lower D5 product loop, more than
# eight metres below the foundation deck.  Treating that short nearest-distance
# link as a service apron creates an impossible cliff and the 8.593 m mesh edge
# recorded by the last Rev.P3 build.  The integrated Rev.P5 model adds a proper
# long ramp to D3 at matching elevation.  Therefore the generic nearest-road
# apron generator must not create a duplicate BLD_05 apron.
needle = '''        code = name.replace("_FOUNDATION_DECK", "")
        deck = all_decks[name]
'''
replacement = '''        code = name.replace("_FOUNDATION_DECK", "")
        if code == "BLD_05":
            continue
        deck = all_decks[name]
'''
if needle not in text:
    raise RuntimeError("build_aprons code/deck block not found")
text = text.replace(needle, replacement, 1)

# Record the controlled omission in the numerical QA instead of silently
# dropping it.  The integrated builder must close this interface.
needle2 = '''        "changed_elements": ["D1-D6 road corridors", "road layers", "service aprons", "local retaining-wall/rail openings"],
'''
replacement2 = '''        "changed_elements": ["D1-D6 road corridors", "road layers", "service aprons except BLD_05", "local retaining-wall/rail openings"],
        "controlled_interfaces_for_integrated_model": [
            {
                "id": "IFC-R05",
                "object": "BLD_05",
                "requirement": "Dedicated long service ramp from upper pyrolysis terrace to D3; no short connection to lower D5",
                "status": "TRANSFERRED_TO_REV_P5_INTEGRATION",
            }
        ],
'''
if needle2 not in text:
    raise RuntimeError("QA changed_elements block not found")
text = text.replace(needle2, replacement2, 1)

path.write_text(text, encoding="utf-8")
print("REV_P5_ROAD_FINALIZE_PATCHED")
