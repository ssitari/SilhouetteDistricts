#!/usr/bin/env python3
"""
Illustrated walkthrough: how a past election gets allocated to a districting plan.

Five figures, each one step, written for a workshop rather than a paper:

  1  precincts, as published            what you start with
  2  one precinct, zoomed               the split, and the only assumption in it
  3  blocks carrying allocated votes    the intermediate product
  4  five plans, coloured by margin     the result, spatially
  5  sorted district profiles           the result, and the argument

    python scripts/walkthrough_il.py --vest "C:/.../il_2020.shp"

Everything is drawn from allocate_votes.allocate_blocks and the published
allocation CSV, so the pictures and the numbers cannot drift apart.

A red-blue diverging ramp is the right call here even though this collection
usually avoids it. Elsewhere it is a hazard because a party-coded palette reads
as party affiliation whether or not the legend says so -- but here the quantity
IS party affiliation, so the convention helps instead of lying. Neutral grey at
50%, per the rule that a diverging scale gets two hues and a grey midpoint.
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import Polygon as MplPolygon
from shapely.geometry import Polygon

from allocate_votes import (DEM, REP, allocate_blocks, assign_enacted, assign_inward,
                            assign_outward, assign_stripe)
from build_districts import crs_for

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "walkthrough"
USPS = "IL"
MODELS = ["enacted", "outward", "inward", "meridian", "parallel"]

CMAP = LinearSegmentedColormap.from_list("partisan", [
    "#67001f", "#b2182b", "#d6604d", "#f4a582", "#fddbc7",
    "#f0f0f0",
    "#d1e5f0", "#92c5de", "#4393c3", "#2166ac", "#053061",
])
NORM = TwoSlopeNorm(vmin=0.20, vcenter=0.50, vmax=0.80)
INK, MUTED, RULE = "#1a1a1a", "#6b7280", "#d4d4d8"


def finish(ax, title, sub=None):
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=12, loc="left", color=INK, pad=10)
    if sub:
        ax.text(0, 1.005, sub, transform=ax.transAxes, fontsize=9,
                color=MUTED, va="bottom")


def colorbar(fig, ax, label):
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=NORM)
    cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label(label, fontsize=9, color=MUTED)
    cb.ax.tick_params(labelsize=8, colors=MUTED)
    cb.outline.set_visible(False)


# ---------------------------------------------------------------------------

def fig1_precincts(vest, out):
    v = vest.copy()
    v["share"] = v[DEM] / (v[DEM] + v[REP]).replace(0, np.nan)
    fig, ax = plt.subplots(figsize=(9, 11), dpi=130)
    v.to_crs(crs_for(USPS)).plot(ax=ax, column="share", cmap=CMAP, norm=NORM,
                                 linewidth=0.05, edgecolor="#ffffff")
    finish(ax, "1 · What you start with: 10,083 precincts",
           "VEST 2020 presidential results, joined to Census VTD boundaries")
    colorbar(fig, ax, "Democratic share, two-party")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)


def fig2_one_precinct(occ, vest, which_out, out):
    """A precinct that a district boundary cuts: where the assumption lives."""
    df = pd.DataFrame({"pid": occ["pid"], "d": which_out, "pop": occ["pop"],
                       "vap": occ["vap"], "lon": occ["lon"], "lat": occ["lat"]})
    g = df.groupby("pid").agg(n=("d", "size"), nd=("d", "nunique"), pop=("pop", "sum"))
    cand = g[(g["nd"] == 2) & (g["n"].between(12, 60)) & (g["pop"] > 1500)]
    if cand.empty:
        cand = g[g["nd"] == 2].head(1)
    pid = cand.sort_values("pop", ascending=False).index[0]

    sub = df[df["pid"] == pid]
    prec = vest[vest["GEOID20"] == pid].iloc[0]
    dem, rep = float(prec[DEM]), float(prec[REP])

    fig, ax = plt.subplots(figsize=(9, 8), dpi=130)
    poly = gpd.GeoSeries([prec.geometry], crs="EPSG:4269").to_crs(crs_for(USPS))
    poly.plot(ax=ax, facecolor="#fafafa", edgecolor=INK, linewidth=1.4)

    pts = gpd.GeoSeries(gpd.points_from_xy(sub["lon"], sub["lat"]),
                        crs="EPSG:4269").to_crs(crs_for(USPS))
    districts = sorted(sub["d"].unique())
    marks = ["#762a83", "#1b7837"]   # deliberately not red or blue
    for i, d in enumerate(districts):
        m = (sub["d"] == d).to_numpy()
        share = sub.loc[m, "vap"].sum() / sub["vap"].sum()
        ax.scatter(pts.x[m], pts.y[m], s=8 + 420 * sub.loc[m, "vap"] / sub["vap"].max(),
                   color=marks[i % 2], alpha=.75, edgecolor="white", linewidth=.5,
                   label=f"district {d + 1}: {share:.1%} of the precinct's VAP "
                         f"→ {dem * share:,.0f} D / {rep * share:,.0f} R")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.02), frameon=False, fontsize=9)
    finish(ax, "2 · The one assumption: votes follow voting-age population",
           f"Precinct {pid} reported {dem:,.0f} D and {rep:,.0f} R. A district "
           f"boundary cuts it, so the votes are split by the VAP on each side.")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)
    return pid


def fig3_blocks(occ, out):
    v = occ["dem"] + occ["rep"]
    share = np.where(v > 0, occ["dem"] / np.where(v > 0, v, 1), np.nan)
    order = np.argsort(v.to_numpy())          # heaviest blocks drawn last
    pts = gpd.GeoSeries(gpd.points_from_xy(occ["lon"], occ["lat"]),
                        crs="EPSG:4269").to_crs(crs_for(USPS))

    fig, ax = plt.subplots(figsize=(9, 11), dpi=130)
    ax.scatter(pts.x.to_numpy()[order], pts.y.to_numpy()[order],
               c=share[order], cmap=CMAP, norm=NORM,
               s=np.clip(v.to_numpy()[order] / 12, 0.15, 14), linewidths=0)
    finish(ax, "3 · Every block now carries votes",
           "278,166 occupied blocks. Colour is margin; size is votes. The split "
           "adds no new detail to partisanship — it adds detail to WHERE the votes are.")
    colorbar(fig, ax, "Democratic share, two-party")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)


def model_patches(ax, model, shares):
    """Draw one plan, each district filled by its allocated Democratic share."""
    if model == "outward":
        spec = json.loads((ROOT / "data/derived/il_districts.json").read_text())
        for lobe in spec["lobes"]:
            o, a = np.asarray(lobe["outline"]), np.asarray(lobe["anchor"])
            clip = MplPolygon(o, closed=True, facecolor="none", edgecolor="none",
                              transform=ax.transData)
            ax.add_patch(clip)
            for k in range(spec["seats"], 0, -1):
                pt = MplPolygon(a + (o - a) * spec["breaks"][k], closed=True,
                                facecolor=CMAP(NORM(shares[k - 1])), edgecolor="white",
                                linewidth=.2)
                ax.add_patch(pt)
                pt.set_clip_path(clip)
        return np.vstack([np.asarray(l["outline"]) for l in spec["lobes"]])

    if model == "inward":
        res = json.loads((ROOT / "data/derived_inward/il_inward.json").read_text())
        for k, shell in enumerate(res["shells"]):
            for ring in shell:
                ax.add_patch(MplPolygon(np.asarray(ring), closed=True,
                                        facecolor=CMAP(NORM(shares[k])),
                                        edgecolor="white", linewidth=.2))
        return np.vstack([np.asarray(r) for r in res["lobes"]])

    if model == "enacted":
        cd = gpd.read_file(ROOT / "data/raw/cb_2023_us_cd118_500k.zip")
        cd = cd[cd["STATEFP"] == "17"].sort_values("CD118FP").to_crs(crs_for(USPS))
    else:
        cd = gpd.read_file(ROOT / f"data/gis_{model}/il_{model}.geojson")
        cd = cd.sort_values("district").to_crs(crs_for(USPS))
    cd = cd.reset_index(drop=True)
    cd["share"] = shares[: len(cd)]
    cd.plot(ax=ax, column="share", cmap=CMAP, norm=NORM, edgecolor="white", linewidth=.35)
    b = cd.total_bounds
    return np.array([[b[0], b[1]], [b[2], b[3]]])


def fig4_maps(alloc, out):
    # Constrained layout, because the colourbar is added after the axes and
    # tight_layout would reserve space against the pre-colourbar geometry.
    fig, axes = plt.subplots(1, 5, figsize=(19, 6.6), dpi=130,
                             layout="constrained")
    for ax, model in zip(axes, MODELS):
        shares = alloc[alloc["model"] == model].sort_values("district")["dem_two_party"].to_numpy()
        pts = model_patches(ax, model, shares)
        span = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1])) * 1.04
        cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
        ax.set_xlim(cx - span / 2, cx + span / 2)
        ax.set_ylim(cy - span / 2, cy + span / 2)
        # Illinois is tall and narrow, so an equal-aspect panel shrinks to fit
        # the width and then centres, dropping the map away from its own title.
        # Anchor north so the title stays attached to the map.
        ax.set_anchor("N")
        n_comp = int(((shares > .45) & (shares < .55)).sum())
        finish(ax, f"{model}", f"{int((shares > .5).sum())} Dem seats · "
                               f"{n_comp} competitive")
    fig.suptitle("4 · The same votes, five plans", fontsize=14, x=0.01,
                 ha="left")
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=NORM)
    cb = fig.colorbar(sm, ax=axes.tolist(), orientation="horizontal",
                      fraction=0.025, pad=0.03, aspect=55)
    cb.set_label("Democratic share of the two-party vote", fontsize=9, color=MUTED)
    cb.ax.tick_params(labelsize=8, colors=MUTED)
    cb.outline.set_visible(False)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)


def fig5_profiles(alloc, statewide, out):
    fig, ax = plt.subplots(figsize=(11, 7.5), dpi=130)
    ax.axhspan(.45, .55, color="#f4f4f5", zorder=0)
    ax.axhline(.5, color=RULE, lw=1, zorder=1)
    ax.plot([-.5, 4.35], [statewide, statewide], color=MUTED, lw=1,
            ls=(0, (4, 3)), zorder=1)
    ax.text(4.42, statewide, f"statewide {statewide:.1%}", fontsize=9,
            color=MUTED, va="center")

    for i, model in enumerate(MODELS):
        s = np.sort(alloc[alloc["model"] == model]["dem_two_party"].to_numpy())
        x = np.full(len(s), i, dtype=float) + np.linspace(-.28, .28, len(s))
        ax.plot(x, s, color=RULE, lw=1, zorder=2)
        ax.scatter(x, s, c=s, cmap=CMAP, norm=NORM, s=68, zorder=3,
                   edgecolor="white", linewidth=.7)
        n_comp = int(((s > .45) & (s < .55)).sum())
        ax.annotate(f"{int((s > .5).sum())} seats", (i, -0.105),
                    xycoords=("data", "axes fraction"), ha="center",
                    fontsize=10.5, color=INK, fontweight="600",
                    annotation_clip=False)
        ax.annotate(f"{n_comp} competitive", (i, -0.148),
                    xycoords=("data", "axes fraction"), ha="center",
                    fontsize=9, color=MUTED, annotation_clip=False)

    ax.set_xticks(range(len(MODELS)))
    ax.set_xticklabels(MODELS, fontsize=11)
    ax.set_xlim(-.5, 5.35)
    ax.set_ylim(.2, .93)
    ax.set_yticks([.2, .3, .4, .5, .6, .7, .8, .9])
    ax.set_yticklabels([f"{int(v*100)}%" for v in ax.get_yticks()], fontsize=9)
    ax.set_ylabel("Democratic share of the two-party vote", fontsize=10, color=MUTED)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(RULE)
    ax.tick_params(colors=MUTED)
    ax.set_title("5 · Districts sorted, within each plan", fontsize=14, loc="left", pad=12)
    fig.text(0.02, -0.10,
             "Shaded band is 45–55%. The enacted map has one district in it; the ring "
             "models have six each. Dashed line is the statewide result.",
             fontsize=9.5, color=MUTED, ha="left")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vest", required=True)
    args = ap.parse_args()
    DOCS.mkdir(parents=True, exist_ok=True)

    occ, vest, tot_d, tot_r = allocate_blocks(USPS, args.vest)
    alloc = pd.read_csv(ROOT / "data/derived_votes/il_allocation.csv")
    statewide = occ["dem"].sum() / (occ["dem"].sum() + occ["rep"].sum())

    proj = gpd.GeoSeries(gpd.points_from_xy(occ["lon"], occ["lat"]),
                         crs="EPSG:4269").to_crs(crs_for(USPS))
    which_out, _ = assign_outward(USPS, occ, proj.x.to_numpy(), proj.y.to_numpy())

    fig1_precincts(vest, DOCS / "1_precincts.png")
    fig2_one_precinct(occ, vest, which_out, DOCS / "2_one_precinct.png")
    fig3_blocks(occ, DOCS / "3_blocks.png")
    fig4_maps(alloc, DOCS / "4_five_plans.png")
    fig5_profiles(alloc, statewide, DOCS / "5_profiles.png")


if __name__ == "__main__":
    main()
