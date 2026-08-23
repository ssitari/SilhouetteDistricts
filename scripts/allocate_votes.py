#!/usr/bin/env python3
"""
Allocate a past election to the four districting models.

This is NOT a prediction. Nobody ran in these districts. It takes real votes
already cast and asks where they would have landed under each geometry, which is
what redistricting analysts mean by a partisan index.

Because all four models redistribute the SAME ballots, any quirk of the chosen
election -- a strong candidate, an odd turnout year -- lands identically in all
four and cancels in the comparison. That is why one race is enough here, where a
composite of several would be needed to characterise a district in isolation.

    python scripts/allocate_votes.py --state IL --vest "C:/.../il_2020.shp"

METHOD

  1. Join blocks to VTDs by GEOID. VEST's precincts for Illinois are Census 2020
     VTDs, and VTDs are built FROM blocks, so blocks nest inside them exactly:
     10,081 of 10,084 match outright, covering 99.98% of the state. This is a
     lookup, not areal interpolation -- no slivers, no precinct-name matching.
     The handful of VTDs VEST edited (documented merges in Washington and
     Winnebago counties) fall back to a point-in-polygon join.

  2. Split each VTD's votes among its blocks in proportion to VOTING-AGE
     population. Weighting by total population would over-credit blocks with
     more children, which is systematically suburban.

  3. Assign blocks to districts using each model's own stored coordinate, then
     sum. The district populations this produces must match the ones already
     published for each model, which is the check that the assignment is right.

WHAT THE RESULT DOES AND DOES NOT REST ON

  Within a VTD, votes are assumed to be spread in proportion to voting-age
  population -- i.e. partisanship is uniform inside the VTD. That assumption
  only bites where a district boundary CUTS a VTD, so the script reports, per
  model, the share of population living in a split VTD. That number is the
  honest error budget: a model that splits few VTDs is reporting almost
  measured values, one that splits many is leaning on the assumption.
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon

import pl94
from build_districts import crs_for, radial_coord

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived_votes"
DEM, REP = "G20PREDBID", "G20PRERTRU"


# ---------------------------------------------------------------------------
# Block -> district, one function per model, each reading that model's artifact

def assign_outward(usps, blocks, xs, ys):
    spec = json.loads((ROOT / "data/derived" / f"{usps.lower()}_districts.json")
                      .read_text(encoding="utf-8"))
    polys = [Polygon(l["outline"]) for l in spec["lobes"]]
    anchors = [tuple(l["anchor"]) for l in spec["lobes"]]
    pts = shapely.points(xs, ys)
    lobe_of = np.column_stack([shapely.distance(pts, p) for p in polys]).argmin(axis=1)

    s = np.empty(len(xs))
    for i, poly in enumerate(polys):
        m = lobe_of == i
        if m.any():
            s[m], _ = radial_coord(anchors[i], poly.exterior, xs[m], ys[m])
    edges = np.array(spec["breaks"])
    return np.clip(np.searchsorted(edges, s, side="right") - 1, 0, spec["seats"] - 1), spec


def assign_inward(usps, blocks, xs, ys):
    res = json.loads((ROOT / "data/derived_inward" / f"{usps.lower()}_inward.json")
                     .read_text(encoding="utf-8"))
    whole = shapely.union_all([Polygon(r) for r in res["lobes"]])
    d = shapely.distance(shapely.points(xs, ys), whole.boundary)
    d = np.where(shapely.contains_xy(whole, xs, ys), d, 0.0)
    edges = np.array(res["offsets"] + [np.inf])
    return np.clip(np.searchsorted(edges, d, side="right") - 1, 0, res["seats"] - 1), res


def assign_stripe(usps, mode, blocks):
    res = json.loads((ROOT / f"data/derived_{mode}" / f"{usps.lower()}_{mode}.json")
                     .read_text(encoding="utf-8"))
    if mode == "meridian":
        coord = -blocks["lon"].to_numpy()
        cuts = [-v for v in res["cuts_lon"]]
    else:
        coord = blocks["lat"].to_numpy()
        cuts = list(res["cuts_lat"])
    edges = np.array([-np.inf] + cuts + [np.inf])
    return np.clip(np.searchsorted(edges, coord, side="right") - 1, 0, res["seats"] - 1), res


def assign_enacted(usps, blocks):
    """
    The real map, as a fifth column: Illinois's enacted 118th-Congress districts.

    Assigned by point-in-polygon rather than from a stored coordinate, since
    this map has no generating rule -- that is the whole point of including it.
    The four models show what geometry alone produces; this shows what gets
    added when people draw the lines with intent.

    It also brings its own independent check. Congressional districts must be
    equal in population to within about a person, so if the block assignment is
    right, the district populations will come out essentially identical. Nothing
    in this pipeline forces that, so it is a genuine test of the join.
    """
    path = ROOT / "data" / "raw" / "cb_2023_us_cd118_500k.zip"
    if not path.exists():
        import fetch_data
        fetch_data.download(
            "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_cd118_500k.zip",
            path)
    cd = gpd.read_file(path)
    cd = cd[cd["STATEFP"] == FIPS[usps]][["CD118FP", "geometry"]].sort_values("CD118FP")
    cd = cd.reset_index(drop=True)

    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(blocks["lon"], blocks["lat"]),
                           crs="EPSG:4269")
    hit = gpd.sjoin(pts, cd.reset_index(names="idx"), predicate="within", how="left")
    hit = hit[~hit.index.duplicated(keep="first")]
    which = np.array(hit["idx"], dtype=float)  # writable copy for the fallback

    if np.isnan(which).any():
        # cb_500k is generalised, so a few shoreline blocks sit outside every
        # district. Fall back to the nearest one.
        miss = np.isnan(which)
        near = gpd.sjoin_nearest(pts[miss], cd.reset_index(names="idx"), how="left")
        near = near[~near.index.duplicated(keep="first")]
        which[miss] = near["idx"].to_numpy()
        print(f"  enacted: {int(miss.sum()):,} blocks matched by nearest district")

    return which.astype(int), {"seats": len(cd), "labels": cd["CD118FP"].tolist()}


FIPS = {"IL": "17"}


# ---------------------------------------------------------------------------

def allocate_blocks(usps, vest_path):
    """
    Blocks with their allocated Democratic and Republican votes.

    Split out so the illustrated walkthrough draws the same objects this
    script counts. Two copies of the allocation would eventually disagree,
    and the figures would then illustrate something the numbers do not say.
    """
    # --- blocks, with voting-age population and their VTD id -----------------
    blocks = pl94.load_blocks(ROOT / "data" / "raw" / f"{usps.lower()}2020.pl.zip",
                              with_vap=True)
    occ = blocks[blocks["pop"] > 0].reset_index(drop=True)
    print(f"{usps}: {len(blocks):,} blocks, {len(occ):,} occupied, "
          f"pop {blocks['pop'].sum():,}, VAP {blocks['vap'].sum():,}")

    # --- precincts -----------------------------------------------------------
    vest = gpd.read_file(vest_path)
    vest = vest[["GEOID20", DEM, REP, "geometry"]].copy()
    tot_d, tot_r = int(vest[DEM].sum()), int(vest[REP].sum())
    print(f"VEST: {len(vest):,} precincts, D {tot_d:,} R {tot_r:,} "
          f"-> D {tot_d/(tot_d+tot_r):.4%} two-party")

    # --- join blocks to precincts -------------------------------------------
    known = set(vest["GEOID20"])
    occ["pid"] = occ["vtd"].where(occ["vtd"].isin(known))
    miss = occ["pid"].isna()
    if miss.any():
        # Only the VTDs VEST edited. Fall back to point-in-polygon.
        pts = gpd.GeoDataFrame(
            occ.loc[miss, ["geoid"]],
            geometry=gpd.points_from_xy(occ.loc[miss, "lon"], occ.loc[miss, "lat"]),
            crs="EPSG:4269")
        hit = gpd.sjoin(pts, vest[["GEOID20", "geometry"]], predicate="within", how="left")
        hit = hit[~hit.index.duplicated(keep="first")]
        occ.loc[miss, "pid"] = hit["GEOID20"].to_numpy()
        print(f"  {int(miss.sum()):,} blocks fell back to a spatial join "
              f"({int(occ.loc[miss, 'pop'].sum()):,} people); "
              f"{int(occ['pid'].isna().sum()):,} still unmatched")
    occ = occ[occ["pid"].notna()].reset_index(drop=True)

    # --- split precinct votes among blocks by VAP ---------------------------
    votes = vest.set_index("GEOID20")[[DEM, REP]]
    grp = occ.groupby("pid")
    w = occ["vap"].to_numpy(dtype=float)
    denom = grp["vap"].transform("sum").to_numpy(dtype=float)
    # A precinct whose blocks record no voting-age population still has votes;
    # fall back to total population, then to an equal split.
    alt = occ["pop"].to_numpy(dtype=float)
    alt_den = grp["pop"].transform("sum").to_numpy(dtype=float)
    n_in = grp["pid"].transform("size").to_numpy(dtype=float)
    share = np.where(denom > 0, w / np.where(denom > 0, denom, 1),
                     np.where(alt_den > 0, alt / np.where(alt_den > 0, alt_den, 1), 1 / n_in))

    occ["dem"] = occ["pid"].map(votes[DEM]).to_numpy() * share
    occ["rep"] = occ["pid"].map(votes[REP]).to_numpy() * share

    got_d, got_r = occ["dem"].sum(), occ["rep"].sum()
    print(f"  allocated: D {got_d:,.0f} R {got_r:,.0f}  "
          f"(retained {(got_d+got_r)/(tot_d+tot_r):.4%} of the two-party vote)")

    return occ, vest, tot_d, tot_r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="IL")
    ap.add_argument("--vest", required=True, help="path to the VEST shapefile")
    args = ap.parse_args()
    usps = args.state.upper()

    occ, vest, tot_d, tot_r = allocate_blocks(usps, args.vest)
    got_d, got_r = occ["dem"].sum(), occ["rep"].sum()

    # --- assign to districts under each model -------------------------------
    proj = gpd.GeoSeries(gpd.points_from_xy(occ["lon"], occ["lat"]),
                         crs="EPSG:4269").to_crs(crs_for(usps))
    xs, ys = proj.x.to_numpy(), proj.y.to_numpy()

    models = {
        "outward": lambda: assign_outward(usps, occ, xs, ys),
        "inward": lambda: assign_inward(usps, occ, xs, ys),
        "meridian": lambda: assign_stripe(usps, "meridian", occ),
        "parallel": lambda: assign_stripe(usps, "parallel", occ),
        "enacted": lambda: assign_enacted(usps, occ),
    }

    rows, summary = [], []
    for name, fn in models.items():
        which, spec = fn()
        seats = spec["seats"]
        pop = np.bincount(which, weights=occ["pop"], minlength=seats)
        dem = np.bincount(which, weights=occ["dem"], minlength=seats)
        rep = np.bincount(which, weights=occ["rep"], minlength=seats)
        share_d = dem / np.where(dem + rep > 0, dem + rep, 1)

        # Two different checks, depending on what there is to check against.
        # The four models have published district populations to reproduce. The
        # enacted map does not, but it must be near-exactly equal by law, so its
        # own evenness is the test.
        pub = spec.get("district_pop")
        if pub is not None:
            pub = np.array(pub, dtype=float)
            pop_err = float(np.abs(pop - pub).max() / pub.mean())
        else:
            pop_err = float(np.abs(pop - pop.mean()).max() / pop.mean())

        # How much of the state sits in a VTD this model splits? That is the
        # share of the answer resting on within-VTD uniformity.
        vt = pd.DataFrame({"pid": occ["pid"], "d": which, "pop": occ["pop"]})
        nd = vt.groupby("pid")["d"].nunique()
        split_pop = vt[vt["pid"].isin(nd[nd > 1].index)]["pop"].sum()

        for k in range(seats):
            rows.append({"model": name, "district": k + 1, "population": int(pop[k]),
                         "dem": round(dem[k], 1), "rep": round(rep[k], 1),
                         "dem_two_party": round(float(share_d[k]), 5)})
        summary.append({
            "model": name, "seats": seats,
            "dem_seats": int((share_d > 0.5).sum()),
            "min_share": round(float(share_d.min()), 4),
            "max_share": round(float(share_d.max()), 4),
            "spread": round(float(share_d.max() - share_d.min()), 4),
            "stdev": round(float(share_d.std(ddof=0)), 4),
            "split_vtd_pop_pct": round(100 * split_pop / occ["pop"].sum(), 2),
            "pop_check": round(pop_err, 6),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / f"{usps.lower()}_allocation.csv", index=False)
    df = pd.DataFrame(summary)
    df.to_csv(OUT / f"{usps.lower()}_summary.csv", index=False)

    statewide = got_d / (got_d + got_r)
    print()
    print(f"statewide two-party Democratic share: {statewide:.4%}")
    print(f"proportional expectation: {statewide * summary[0]['seats']:.1f} of "
          f"{summary[0]['seats']} seats")
    print()
    print(df.to_string(index=False))
    print()
    print(f"wrote {(OUT / f'{usps.lower()}_allocation.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
