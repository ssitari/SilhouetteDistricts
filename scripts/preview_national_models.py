#!/usr/bin/env python3
"""
National maps of all four districting models, in the five-colour symbology.

    python scripts/preview_national_models.py            # 2x2 comparison + singles
    python scripts/preview_national_models.py --only inward

THE PALETTE IS CYCLIC, so only ADJACENT separation matters -- district k and
k+1 must be tellable apart; district 1 and district 9 never touch. That makes
the hue ORDER a real decision rather than a cosmetic one.

Validated with the dataviz validator, scoring the wrap-around pair as well:

    order                  worst adjacent fill dE   stroke dE
    tan green blue yellow cyan      6.3                14.4     <- used here
    tan cyan green blue yellow      3.3                 6.0     <- as supplied

Reordering nearly doubles both. The fills stay below the dE 15 floor even so,
which is the point of the paired design: the tints carry mass, and the darker
strokes -- all of which clear 3:1 against the surface -- carry the boundaries.
Fills alone could not separate neighbouring districts and are not asked to.

All four models are drawn in each state's own working CRS and share the outward
bundle's Alaska and Hawaii inset transforms, so the four maps are registered to
each other and directly comparable.
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapely
from matplotlib.patches import PathPatch, Polygon as MplPolygon
from matplotlib.path import Path as MplPath
from shapely import affinity

from build_districts import crs_for

ROOT = Path(__file__).resolve().parent.parent
MODELS = ["outward", "inward", "meridian", "parallel"]

# Okabe-Ito derived tints with matching dark strokes, ordered so the two closest
# hue pairs (green/cyan in the fills, green/teal in the strokes) never sit next
# to each other in the cycle. See the module docstring.
FILLS = ["#f3d9b8", "#c5e3d0", "#c9d6ee", "#f7e6b0", "#c9e4e8"]
STROKES = ["#8c5c14", "#1d6b46", "#20447e", "#8a7213", "#2f6d78"]
LW = 0.28

# The colours repeat every five districts and mean nothing on their own. Say so
# on the figure: a reader who sees five hues on a map will assume they encode
# something, and here they only keep neighbours apart.
SUBTITLE = ("colours cycle every five districts and carry no meaning — "
            "they separate neighbours; every district holds an equal share "
            "of its state's 2020 population")

TITLES = {
    "outward": "outward — scaled copies of the state, centre out",
    "inward": "inward — erosion bands, border in",
    "meridian": "meridian — constant longitude, east to west",
    "parallel": "parallel — constant latitude, south to north",
}


def pair(k):
    """Fill and stroke for district k (1-indexed), cycled."""
    return FILLS[(k - 1) % 5], STROKES[(k - 1) % 5]


def placed(geom, p):
    if p is None:
        return geom
    g = affinity.scale(geom, xfact=p["scale"], yfact=p["scale"], origin=(0, 0))
    return affinity.translate(g, xoff=p["translate"][0], yoff=p["translate"][1])


def patch_for(geom, fc, ec):
    """A PathPatch that honours interior rings, so donut districts stay donuts."""
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    paths = []
    for q in polys:
        if q.is_empty:
            continue
        paths.append(MplPath(np.asarray(q.exterior.coords)))
        for hole in q.interiors:
            paths.append(MplPath(np.asarray(hole.coords)))
    if not paths:
        return None
    return PathPatch(MplPath.make_compound_path(*paths), facecolor=fc,
                     edgecolor=ec, linewidth=LW, joinstyle="round")


def draw_outward(ax, spec, p):
    for lobe in spec["lobes"]:
        o = np.asarray(lobe["outline"])
        a = np.asarray(lobe["anchor"])
        base = placed(shapely.Polygon(o), p)
        clip = MplPolygon(np.asarray(base.exterior.coords), closed=True,
                          facecolor="none", edgecolor="none", transform=ax.transData)
        ax.add_patch(clip)
        # Back to front: each smaller copy covers the middle of the last, so the
        # visible band is the district and its stroke marks that band's outer edge.
        for k in range(spec["seats"], 0, -1):
            fc, ec = pair(k)
            g = placed(shapely.Polygon(a + (o - a) * spec["breaks"][k]), p)
            pt = MplPolygon(np.asarray(g.exterior.coords), closed=True,
                            facecolor=fc, edgecolor=ec, linewidth=LW)
            ax.add_patch(pt)
            pt.set_clip_path(clip)


def draw_inward(ax, res, p):
    # Shells nest, so painting outermost first and each deeper one on top leaves
    # district k+1 visible in its own band.
    for k, shell in enumerate(res["shells"]):
        fc, ec = pair(k + 1)
        for ring in shell:
            g = placed(shapely.Polygon(ring), p)
            ax.add_patch(MplPolygon(np.asarray(g.exterior.coords), closed=True,
                                    facecolor=fc, edgecolor=ec, linewidth=LW))


def draw_stripes(ax, usps, model, p):
    g = gpd.read_file(ROOT / f"data/gis_{model}" / f"{usps.lower()}_{model}.geojson")
    g = g.to_crs(crs_for(usps)).sort_values("district")
    for _, r in g.iterrows():
        fc, ec = pair(int(r["district"]))
        patch = patch_for(placed(r.geometry, p), fc, ec)
        if patch is not None:
            ax.add_patch(patch)


def render(ax, model, meta):
    for f in sorted((ROOT / "data" / "derived").glob("*_districts.json")):
        usps = f.name[:2].upper()
        p = meta["placement"].get(usps)
        if model == "outward":
            draw_outward(ax, json.loads(f.read_text(encoding="utf-8")), p)
        elif model == "inward":
            src = ROOT / "data/derived_inward" / f"{usps.lower()}_inward.json"
            if src.exists():
                draw_inward(ax, json.loads(src.read_text(encoding="utf-8")), p)
        else:
            src = ROOT / f"data/gis_{model}" / f"{usps.lower()}_{model}.geojson"
            if src.exists():
                draw_stripes(ax, usps, model, p)

    x0, y0, x1, y1 = meta["frame_bbox"]
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=MODELS)
    ap.add_argument("--dpi", type=int, default=110)
    args = ap.parse_args()

    meta = json.loads((ROOT / "data" / "districts.json").read_text(encoding="utf-8"))["meta"]
    x0, y0, x1, y1 = meta["frame_bbox"]
    aspect = (y1 - y0) / (x1 - x0)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)

    todo = [args.only] if args.only else MODELS
    for model in todo:
        fig, ax = plt.subplots(figsize=(15, 15 * aspect), dpi=args.dpi)
        render(ax, model, meta)
        ax.set_title(TITLES[model], fontsize=13, loc="left", color="#1a1a1a", pad=14)
        fig.text(0.01, 0.005, SUBTITLE, fontsize=9, color="#6b7280", ha="left")
        fig.tight_layout(rect=(0, 0.02, 1, 1))
        out = docs / f"national_{model}_5c.png"
        fig.savefig(out, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"wrote {out.relative_to(ROOT)}")

    if not args.only:
        fig, axes = plt.subplots(2, 2, figsize=(24, 24 * aspect), dpi=args.dpi)
        for ax, model in zip(axes.ravel(), MODELS):
            render(ax, model, meta)
            ax.set_title(TITLES[model], fontsize=13, loc="left", color="#1a1a1a", pad=10)
        fig.text(0.01, 0.005, SUBTITLE, fontsize=11, color="#6b7280", ha="left")
        fig.tight_layout(rect=(0, 0.015, 1, 1))
        out = docs / "national_four_models.png"
        fig.savefig(out, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
