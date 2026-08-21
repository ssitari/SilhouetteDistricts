#!/usr/bin/env python3
"""
All four districting models, same states, same palette, one figure.

    python scripts/preview_models.py NY MI FL CO HI
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

from build_districts import crs_for

ROOT = Path(__file__).resolve().parent.parent
TWO_TONE = ("#12384f", "#ccd9e2")
OUTLINE = "#94a3b8"
MODELS = ["outward", "inward", "meridian", "parallel"]


def add(ax, geom, color):
    """Draw a shapely polygon or multipolygon, honouring interior rings."""
    parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for q in parts:
        if q.is_empty:
            continue
        ax.add_patch(MplPolygon(np.asarray(q.exterior.coords), closed=True,
                                facecolor=color, edgecolor="none"))
        for hole in q.interiors:
            ax.add_patch(MplPolygon(np.asarray(hole.coords), closed=True,
                                    facecolor="white", edgecolor="none"))


def draw(ax, usps, model):
    if model == "outward":
        spec = json.loads((ROOT / "data/derived" / f"{usps.lower()}_districts.json").read_text())
        pts = []
        for lobe in spec["lobes"]:
            o = np.asarray(lobe["outline"]); a = np.asarray(lobe["anchor"]); pts.append(o)
            clip = MplPolygon(o, closed=True, facecolor="none", edgecolor="none",
                              transform=ax.transData)
            ax.add_patch(clip)
            for k in range(spec["seats"], 0, -1):
                pt = MplPolygon(a + (o - a) * spec["breaks"][k], closed=True,
                                facecolor=TWO_TONE[k % 2], edgecolor="none")
                ax.add_patch(pt); pt.set_clip_path(clip)
            ax.add_patch(MplPolygon(o, closed=True, facecolor="none",
                                    edgecolor=OUTLINE, lw=0.6))
        n = spec["seats"]
        pieces = max(spec.get("district_pieces", [1]))
        return np.vstack(pts), n, pieces

    if model == "inward":
        res = json.loads((ROOT / "data/derived_inward" / f"{usps.lower()}_inward.json").read_text())
        for k, shell in enumerate(res["shells"]):
            for ring in shell:
                ax.add_patch(MplPolygon(np.asarray(ring), closed=True,
                                        facecolor=TWO_TONE[(k + 1) % 2], edgecolor="none"))
        for ring in res["lobes"]:
            ax.add_patch(MplPolygon(np.asarray(ring), closed=True, facecolor="none",
                                    edgecolor=OUTLINE, lw=0.6))
        return (np.vstack([np.asarray(r) for r in res["lobes"]]),
                res["seats"], max(res["district_pieces"]))

    g = gpd.read_file(ROOT / f"data/gis_{model}" / f"{usps.lower()}_{model}.geojson")
    g = g.to_crs(crs_for(usps)).sort_values("district")
    for _, r in g.iterrows():
        add(ax, r.geometry, TWO_TONE[int(r["district"]) % 2])
    b = g.total_bounds
    return (np.array([[b[0], b[1]], [b[2], b[3]]]), len(g), int(g["pieces"].max()))


def main():
    states = [s.upper() for s in sys.argv[1:]] or ["NY", "MI", "FL", "CO", "HI"]
    fig, axes = plt.subplots(len(MODELS), len(states),
                             figsize=(2.6 * len(states), 2.9 * len(MODELS)), dpi=115)
    for r, model in enumerate(MODELS):
        for c, usps in enumerate(states):
            ax = axes[r][c]
            pts, n, pieces = draw(ax, usps, model)
            span = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])) * 1.06
            cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
            ax.set_xlim(cx - span / 2, cx + span / 2)
            ax.set_ylim(cy - span / 2, cy + span / 2)
            ax.set_aspect("equal"); ax.axis("off")
            ax.set_title(f"{usps} · {model}" + (f"{chr(10)}max {pieces} pieces"),
                         fontsize=8)
    fig.tight_layout()
    out = ROOT / "docs" / "four_models.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
