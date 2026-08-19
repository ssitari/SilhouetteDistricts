#!/usr/bin/env python3
"""
Render the bundled national map to PNG.

Draws straight from data/districts.json using the same back-to-front paint, the
same clip per lobe and the same inset placement the web app uses, so this is a
check on the shipped payload rather than on the solver's intermediate output.

    python scripts/preview_national.py
    python scripts/preview_national.py --grid    # small multiples
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "districts.json"

TWO_TONE = ("#12384f", "#ccd9e2")
OUTLINE = "#94a3b8"


def scaled(outline, anchor, s):
    a = np.asarray(anchor)
    return a + (np.asarray(outline) - a) * s


def place(pts, p):
    return pts * p["scale"] + np.asarray(p["translate"]) if p else pts


def draw_state(ax, st, placement=None, lw=0.5):
    for lobe in st["lobes"]:
        outline, anchor = lobe["outline"], lobe["anchor"]
        base = place(np.asarray(outline), placement)
        clip = MplPolygon(base, closed=True, facecolor="none", edgecolor="none",
                          transform=ax.transData)
        ax.add_patch(clip)
        for k in range(st["seats"], 0, -1):
            pts = place(scaled(outline, anchor, st["breaks"][k]), placement)
            patch = MplPolygon(pts, closed=True, facecolor=TWO_TONE[k % 2],
                               edgecolor="none", linewidth=0)
            ax.add_patch(patch)
            patch.set_clip_path(clip)
        ax.add_patch(MplPolygon(base, closed=True, facecolor="none",
                                edgecolor=OUTLINE, linewidth=lw))


def ring_ratio(st):
    w = np.diff(np.array(st["breaks"]))
    return float(w.max() / max(w.min(), 1e-9))


def national(bundle, out):
    meta = bundle["meta"]
    x0, y0, x1, y1 = meta["frame_bbox"]
    fig, ax = plt.subplots(figsize=(16, 16 * (y1 - y0) / (x1 - x0)), dpi=110)
    for st in bundle["states"]:
        draw_state(ax, st, meta["placement"].get(st["usps"]))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


def grid(bundle, out):
    states = sorted(bundle["states"], key=ring_ratio, reverse=True)
    cols = 8
    rows = int(np.ceil(len(states) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(2.1 * cols, 2.3 * rows), dpi=110)
    for ax, st in zip(axes.ravel(), states):
        draw_state(ax, st, lw=0.4)
        pts = np.vstack([np.asarray(l["outline"]) for l in st["lobes"]])
        span = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]))
        cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
        half = span / 2 + 0.06 * span
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(f"{st['usps']} · {st['seats']} · {ring_ratio(st):.0f}×", fontsize=8)
    for ax in axes.ravel()[len(states):]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", action="store_true")
    args = ap.parse_args()
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    if args.grid:
        grid(bundle, ROOT / "preview_grid.png")
    else:
        national(bundle, ROOT / "preview_national.png")


if __name__ == "__main__":
    main()
