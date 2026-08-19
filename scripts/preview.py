#!/usr/bin/env python3
"""
Render a derived state to PNG as a geometry check.

Draws the districts back to front -- outermost scaled copy first, each smaller
copy painted over it -- so the rings appear without any boolean geometry. That
is the same trick the web map will use, so this preview also validates the
rendering approach, not just the numbers.

    python scripts/preview.py IL ID MI
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
DERIVED = ROOT / "data" / "derived"


def scaled(outline, anchor, s):
    pts = np.asarray(outline)
    a = np.asarray(anchor)
    return a + (pts - a) * s


# Alternating fills. A sequential ramp turns a 17-ring state into a smooth
# gradient in which no single district can be picked out; two alternating tones
# keep every boundary legible down to sub-1% ring widths, which is exactly where
# the interesting crowding happens.
TWO_TONE = ("#12384f", "#e2e8ec")


def draw(ax, spec, _cmap=None):
    breaks = spec["breaks"]
    n = spec["seats"]
    for lobe in spec["lobes"]:
        outline, anchor = lobe["outline"], lobe["anchor"]

        # Scaled copies of a concave lobe can cross their own boundary -- 6% of
        # ring area in Michigan, which reads as districts spilling into Lake
        # Huron. Clip the whole group to the lobe rather than doing boolean
        # geometry per ring, so the stored data stays outline + scale factors.
        clip = MplPolygon(np.asarray(outline), closed=True, facecolor="none",
                          edgecolor="none", transform=ax.transData)
        ax.add_patch(clip)  # must be in the axes for set_clip_path to take effect

        # Back to front: district n is the largest scaled copy, district 1 the
        # smallest. Painting in this order leaves each district visible only in
        # the band the next-smaller copy does not cover. No edge stroke -- the
        # outer rings are thinner than any hairline, so a stroke would erase the
        # bands rather than separate them. Contrast does the separating.
        for k in range(n, 0, -1):
            patch = MplPolygon(scaled(outline, anchor, breaks[k]), closed=True,
                               facecolor=TWO_TONE[k % 2], edgecolor="none", linewidth=0)
            ax.add_patch(patch)
            patch.set_clip_path(clip)

    allpts = np.vstack([np.asarray(l["outline"]) for l in spec["lobes"]])
    pad = 0.03 * (allpts[:, 0].max() - allpts[:, 0].min())
    ax.set_xlim(allpts[:, 0].min() - pad, allpts[:, 0].max() + pad)
    ax.set_ylim(allpts[:, 1].min() - pad, allpts[:, 1].max() + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"{spec['state']} — {n} districts", fontsize=11)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="+")
    ap.add_argument("--out", default="preview.png")
    args = ap.parse_args()

    specs = [json.loads((DERIVED / f"{s.lower()}_districts.json").read_text()) for s in args.states]
    cmap = plt.get_cmap("viridis")

    fig, axes = plt.subplots(1, len(specs), figsize=(5 * len(specs), 6), dpi=110)
    axes = np.atleast_1d(axes)
    for ax, spec in zip(axes, specs):
        draw(ax, spec, cmap)
    fig.tight_layout()
    out = ROOT / args.out
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
