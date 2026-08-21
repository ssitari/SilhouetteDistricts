#!/usr/bin/env python3
"""
National map of the inward (erosion) variant.

Reuses the outward bundle's inset placement and frame: both variants solve each
state in the same per-state CRS, so Alaska and Hawaii need the same transforms
and the two national maps are directly comparable at a glance.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

ROOT = Path(__file__).resolve().parent.parent
TWO_TONE = ("#12384f", "#ccd9e2")
OUTLINE = "#94a3b8"

meta = json.loads((ROOT / "data" / "districts.json").read_text(encoding="utf-8"))["meta"]
x0, y0, x1, y1 = meta["frame_bbox"]

fig, ax = plt.subplots(figsize=(16, 16 * (y1 - y0) / (x1 - x0)), dpi=110)

for f in sorted((ROOT / "data" / "derived_inward").glob("*_inward.json")):
    res = json.loads(f.read_text(encoding="utf-8"))
    p = meta["placement"].get(res["usps"])
    put = (lambda a: np.asarray(a) * p["scale"] + np.asarray(p["translate"])) if p else np.asarray

    # Shells nest, so painting whole-state first and each deeper erosion on top
    # leaves district k+1 showing in exactly its band -- no holes needed.
    for k, shell in enumerate(res["shells"]):
        for ring in shell:
            ax.add_patch(MplPolygon(put(ring), closed=True,
                                    facecolor=TWO_TONE[(k + 1) % 2], edgecolor="none"))
    for ring in res["lobes"]:
        ax.add_patch(MplPolygon(put(ring), closed=True, facecolor="none",
                                edgecolor=OUTLINE, linewidth=0.5))

ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
ax.set_aspect("equal"); ax.axis("off")
fig.tight_layout()
out = ROOT / "docs" / "national_inward.png"
fig.savefig(out, bbox_inches="tight", facecolor="white")
print(f"wrote {out}")
