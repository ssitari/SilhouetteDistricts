#!/usr/bin/env python3
"""
The two stripe models: districts bounded by meridians, or by parallels.

  meridian - borders run north-south (lines of constant LONGITUDE), districts
             numbered from the east edge of the state westward.
  parallel - borders run east-west (lines of constant LATITUDE), districts
             numbered from the south edge northward.

These are the simple baselines the silhouette models are not. Every block is
sorted on a single coordinate, population is accumulated, and the cuts fall
where it crosses k/n. There is no anchor, no erosion, and -- unlike both
silhouette variants -- nothing to enforce: half-planes are disjoint and
exhaustive by construction, so the districts partition the state exactly. The
whole method is a sort and a cumulative sum.

CUT IN GEOGRAPHIC COORDINATES. A meridian is a line of constant longitude, so
in lon/lat it is axis-aligned and the cut is exact. Doing it in projected metres
instead would give lines that look perfectly straight on the map but are not
meridians -- in Albers a meridian converges poleward and is visibly curved.

Which means the district polygons must be SEGMENTIZED before reprojecting. A
slab in lon/lat has four corners; reproject those alone and the edges become
straight chords in the target CRS, quietly turning a true meridian back into
the projected-space version we just rejected. Densifying first keeps the curve.

Districts are frequently multi-part -- a strip crosses Michigan's two peninsulas
or several Hawaiian islands -- which is expected and allowed.

    python scripts/build_stripes.py --mode meridian --all --gis
    python scripts/build_stripes.py --mode parallel MI HI
"""

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box

import fetch_data
import pl94
from build_districts import LOBE_MIN_AREA_SHARE, SOLVE_SIMPLIFY_M, crs_for

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
GEO_CRS = "EPSG:4269"          # the CRS the Census publishes both sources in
SEGMENTIZE_DEG = 0.02          # ~2 km; keeps reprojected meridians curved
PAD = 0.5                      # degrees of slack on the outer slabs


def solve_stripes(usps, mode, states_gdf, seats_df):
    row = states_gdf[states_gdf["STUSPS"] == usps].iloc[0]
    name = row["NAME"]
    seats = int(seats_df[seats_df["state"].str.casefold() == name.casefold()].iloc[0]["seats"])

    blocks = pl94.load_blocks(pl94.fetch_pl(name, usps))
    occ = blocks[blocks["pop"] > 0]
    lon = occ["lon"].to_numpy()
    lat = occ["lat"].to_numpy()
    pop = occ["pop"].to_numpy()

    # Keep only the major landmasses, so a stray offshore block cannot drag a
    # cut far past the state. Same 1% rule the other models use.
    #
    # Decompose in PROJECTED metres, then bring the lobes back to lon/lat.
    # lobes_for simplifies at SOLVE_SIMPLIFY_M = 250, which means 250 metres --
    # handing it degrees applies a 250-DEGREE tolerance and dissolves the state.
    # That failure is quiet in exactly the wrong way: the cuts come from block
    # coordinates and stay correct, so only the polygons are wrong.
    proj_crs = crs_for(usps)
    geo = gpd.GeoSeries([row["geometry"]], crs=states_gdf.crs).to_crs(GEO_CRS).iloc[0]

    # Select and simplify the lobes IN PLACE in lon/lat rather than round-tripping
    # through projected metres. A straight border in Albers is a curve in lon/lat
    # and vice versa, so going out and back turns edges into chords and moves the
    # area by up to a percent -- Nevada, whose borders are long straight runs, came
    # out 1% too big. The published boundary is lon/lat, so lon/lat is where it
    # should stay. The 1% part test is a ratio, so degrees are fine for it; only
    # the simplification tolerance needs converting.
    tol_deg = SOLVE_SIMPLIFY_M / 111_320.0
    parts = list(geo.geoms) if geo.geom_type == "MultiPolygon" else [geo]
    parts.sort(key=lambda p: p.area, reverse=True)
    tot_area = sum(p.area for p in parts)
    kept = [p for p in parts if p.area / tot_area >= LOBE_MIN_AREA_SHARE] or [parts[0]]

    lobes = []
    for p in kept:
        small = p.simplify(tol_deg, preserve_topology=True)
        if small.is_empty or small.area <= 0:
            small = p
        if small.geom_type == "MultiPolygon":
            small = max(small.geoms, key=lambda g: g.area)
        lobes.append(small)
    whole = shapely.union_all(lobes)

    # Segmentize the reference the same way the districts are, or the invariant
    # compares a densified sum against an undensified whole and reports an error
    # that is entirely its own. It bit hardest on Kansas, Iowa and North Dakota --
    # the states whose borders ARE parallels and meridians, so straight in lon/lat
    # and most curved once projected.
    state_area_km2 = float(
        gpd.GeoSeries([shapely.segmentize(whole, SEGMENTIZE_DEG)], crs=GEO_CRS)
        .to_crs(proj_crs).area.iloc[0]) / 1e6

    # meridian: order east -> west, so the coordinate decreases as k rises.
    # parallel: order south -> north.
    coord = -lon if mode == "meridian" else lat
    order = np.argsort(coord, kind="stable")
    c_sorted, p_sorted = coord[order], pop[order]
    cum = np.cumsum(p_sorted)
    total = int(cum[-1])

    cuts = []
    for k in range(1, seats):
        j = int(np.searchsorted(cum, total * k / seats, side="left"))
        cuts.append(float(c_sorted[min(j, len(c_sorted) - 1)]))

    minx, miny, maxx, maxy = whole.bounds
    edges = [-np.inf] + cuts + [np.inf]

    polys, geoms = [], []
    for k in range(seats):
        lo, hi = edges[k], edges[k + 1]
        if mode == "meridian":
            # coord = -lon, so coord in [lo, hi] means lon in [-hi, -lo]. The
            # negation swaps which END is unbounded: hi = +inf is the WESTERN
            # limit, lo = -inf the eastern one. Getting that backwards makes
            # districts 1 and n claim the same side of the state.
            x_low = (minx - PAD) if not np.isfinite(hi) else -hi
            x_high = (maxx + PAD) if not np.isfinite(lo) else -lo
            slab = box(x_low, miny - PAD, x_high, maxy + PAD)
        else:
            y0 = miny - PAD if not np.isfinite(lo) else lo
            y1 = maxy + PAD if not np.isfinite(hi) else hi
            slab = box(minx - PAD, y0, maxx + PAD, y1)
        g = whole.intersection(slab)
        polys.append(g)
        geoms.append(shapely.segmentize(g, SEGMENTIZE_DEG) if not g.is_empty else g)

    proj = gpd.GeoSeries(geoms, crs=GEO_CRS).to_crs(proj_crs)
    areas = [round(a / 1e6, 1) for a in proj.area]

    # The slabs are exhaustive, so they must reconstruct the whole state. This is
    # the check that would have caught the degrees-for-metres bug immediately.
    coverage = sum(areas) / state_area_km2 if state_area_km2 else 0.0

    which = np.clip(np.searchsorted(np.array(edges), c_sorted, side="right") - 1, 0, seats - 1)
    got = np.bincount(which, weights=p_sorted, minlength=seats).astype(int)
    dev = float(np.abs((got - total / seats) / (total / seats)).max())

    u = shapely.union_all([p for p in polys if not p.is_empty])
    overlap = (sum(p.area for p in polys) - u.area) / u.area if u.area else 0.0
    pieces = [len(p.geoms) if p.geom_type == "MultiPolygon" else (0 if p.is_empty else 1)
              for p in polys]

    key = "cuts_lon" if mode == "meridian" else "cuts_lat"
    return geoms, {
        "usps": usps, "state": name, "seats": seats, "mode": mode,
        "population": total, "crs": crs_for(usps),
        key: [round(-c if mode == "meridian" else c, 6) for c in cuts],
        "district_pop": got.tolist(),
        "district_area_km2": areas,
        "district_density": [round(p / a, 1) if a > 0 else 0.0 for p, a in zip(got, areas)],
        "district_pieces": pieces,
        "_max_dev": dev, "_overlap_frac": overlap, "_coverage": coverage,
        "_empty": [k + 1 for k, p in enumerate(polys) if p.is_empty],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("states", nargs="*")
    ap.add_argument("--mode", choices=["meridian", "parallel"], required=True)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gis", action="store_true")
    args = ap.parse_args()

    out = ROOT / "data" / ("derived_" + args.mode)
    gis = ROOT / "data" / ("gis_" + args.mode)
    out.mkdir(parents=True, exist_ok=True)

    states_gdf = gpd.read_file(fetch_data.fetch_state_boundaries())
    seats_df = fetch_data.load_seats()
    if args.all:
        ok = set(seats_df["state"].str.casefold())
        targets = sorted(r["STUSPS"] for _, r in states_gdf.iterrows()
                         if r["NAME"].casefold() in ok)
    else:
        targets = [s.upper() for s in args.states] or ["MI", "HI", "CO", "NY"]

    rows, frames, locked = [], [], []
    for usps in targets:
        t0 = time.time()
        geoms, res = solve_stripes(usps, args.mode, states_gdf, seats_df)
        (out / (usps.lower() + "_" + args.mode + ".json")).write_text(
            json.dumps(res), encoding="utf-8")

        if args.gis:
            gdf = gpd.GeoDataFrame([{
                "usps": usps, "state": res["state"], "district": k + 1,
                "seats": res["seats"], "mode": args.mode,
                "population": res["district_pop"][k],
                "area_km2": res["district_area_km2"][k],
                "density_km2": res["district_density"][k],
                "pieces": res["district_pieces"][k],
            } for k in range(res["seats"])], geometry=geoms, crs=GEO_CRS).to_crs("EPSG:4326")
            gis.mkdir(parents=True, exist_ok=True)
            try:
                gdf.to_file(gis / (usps.lower() + "_" + args.mode + ".geojson"),
                            driver="GeoJSON", COORDINATE_PRECISION=6)
                frames.append(gdf)
            except PermissionError:
                locked.append(usps)

        contig = sum(1 for p in res["district_pieces"] if p == 1)
        rows.append({"usps": usps, "seats": res["seats"], "contig": contig,
                     "max_pieces": max(res["district_pieces"]), "pop_dev": res["_max_dev"],
                     "overlap": res["_overlap_frac"], "coverage": res["_coverage"]})
        flags = ""
        if res["_overlap_frac"] > 1e-6:
            flags += "  OVERLAP %.4f%%" % (res["_overlap_frac"] * 100)
        if res["_empty"]:
            flags += "  EMPTY " + str(res["_empty"])
        if abs(res["_coverage"] - 1.0) > 0.005:
            flags += "  COVERAGE %.2f%%" % (res["_coverage"] * 100)
        print(f"{usps:>3} {res['seats']:>3}  contig {contig:>3}/{res['seats']:<3} "
              f"max pieces {max(res['district_pieces']):>3}  dev {res['_max_dev']:>8.4%}"
              f"  {time.time()-t0:5.1f}s" + flags, flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(out / ("summary_" + args.mode + ".csv"), index=False)
    tot = df["seats"].sum()
    print(NL + "=" * 70)
    print(f"{args.mode}: {len(df)} states, {tot} districts")
    print(f"single-piece districts: {df['contig'].sum()}/{tot} "
          f"({df['contig'].sum()/tot:.1%})")
    print(f"worst fragmentation:    {df['max_pieces'].max()}")
    print(f"worst population dev:   {df['pop_dev'].max():.4%}")
    print(f"worst self-overlap:     {df['overlap'].max():.8%}")
    print(f"worst coverage error:   {(df['coverage'] - 1.0).abs().max():.6%}")
    if locked:
        print("LOCKED (not rewritten): " + ", ".join(locked))
    if frames:
        allg = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True),
                                geometry="geometry", crs="EPSG:4326")
        path = gis / ("districts_" + args.mode + ".geojson")
        allg.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)
        print(f"GeoJSON: {len(allg)} districts -> {path.relative_to(ROOT)} "
              f"({path.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
