#!/usr/bin/env python3
"""
Bake each state's starting slot in the five-colour cycle into the web bundle.

The offsets come from `preview_national_models.state_offsets` -- greedy graph
colouring over state adjacency -- so the page and the figures in docs/ agree
rather than drifting apart. Adjacency needs geopandas and the boundary
shapefile; the browser has neither, so it is computed once here and stored
next to meta.placement, which is already static per-state data of the same kind.

    python scripts/add_color_offsets.py
"""

import json
from pathlib import Path

from preview_national_models import state_offsets

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "districts.json"


def main():
    data = json.loads(BUNDLE.read_text())
    codes = [s["usps"] for s in data["states"]]

    offsets = state_offsets(codes)
    data["meta"]["color_offsets"] = {c: offsets[c] for c in sorted(codes)}
    data["meta"]["color_cycle"] = 5

    BUNDLE.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  wrote {len(offsets)} offsets to {BUNDLE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
