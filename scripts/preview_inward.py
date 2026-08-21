#!/usr/bin/env python3
"""Side-by-side: outward homothety vs inward erosion, same states, same palette."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

ROOT = Path(__file__).resolve().parent.parent
TWO_TONE = ("#12384f", "#ccd9e2")
OUTLINE = "#94a3b8"


def frame(ax, pts, title):
    span = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])) * 1.06
    cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
    ax.set_xlim(cx - span / 2, cx + span / 2)
    ax.set_ylim(cy - span / 2, cy + span / 2)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=9)


def draw_outward(ax, spec):
    for lobe in spec["lobes"]:
        outline = np.asarray(lobe["outline"]); a = np.asarray(lobe["anchor"])
        clip = MplPolygon(outline, closed=True, facecolor="none", edgecolor="none",
                          transform=ax.transData)
        ax.add_patch(clip)
        for k in range(spec["seats"], 0, -1):
            patch = MplPolygon(a + (outline - a) * spec["breaks"][k], closed=True,
                               facecolor=TWO_TONE[k % 2], edgecolor="none")
            ax.add_patch(patch); patch.set_clip_path(clip)
        ax.add_patch(MplPolygon(outline, closed=True, facecolor="none",
                                edgecolor=OUTLINE, lw=0.6))
    return np.vstack([np.asarray(l["outline"]) for l in spec["lobes"]])


def draw_inward(ax, res):
    # Shells are nested, so painting them in order -- whole state first, each
    # deeper erosion on top -- leaves district k+1 visible in exactly the band
    # between shell k and shell k+1. Same trick as the main map, no holes.
    for k, shell in enumerate(res["shells"]):
        for ring in shell:
            ax.add_patch(MplPolygon(np.asarray(ring), closed=True,
                                    facecolor=TWO_TONE[(k + 1) % 2], edgecolor="none"))
    for ring in res["lobes"]:
        ax.add_patch(MplPolygon(np.asarray(ring), closed=True, facecolor="none",
                                edgecolor=OUTLINE, lw=0.6))
    return np.vstack([np.asarray(r) for r in res["lobes"]])


def main():
    states = [s.upper() for s in sys.argv[1:]] or ["NY", "FL", "MI", "CO", "ID", "HI"]
    fig, axes = plt.subplots(2, len(states), figsize=(2.6 * len(states), 5.8), dpi=115)
    for c, usps in enumerate(states):
        spec = json.loads((ROOT / "data/derived" / f"{usps.lower()}_districts.json").read_text())
        res = json.loads((ROOT / "data/derived_inward" / f"{usps.lower()}_inward.json").read_text())
        op = spec.get("district_pieces", [1])
        frame(axes[0][c], draw_outward(axes[0][c], spec),
              f"{usps} · {spec['seats']} · outward\nmax {max(op)} pieces")
        frame(axes[1][c], draw_inward(axes[1][c], res),
              f"{usps} · inward\nmax {max(res['district_pieces'])} pieces")
    fig.tight_layout()
    out = ROOT / "docs" / "inward_vs_outward.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
