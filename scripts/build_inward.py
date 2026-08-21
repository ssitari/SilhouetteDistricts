#!/usr/bin/env python3
"""
The inward variant: districts as erosion bands measured from the state border.

Instead of scaling the outline about an anchor, every block is given its
distance to the state boundary. Blocks are sorted by that distance, population
is accumulated, and the cut points become inward offsets. District 1 is the
outermost collar; the last district is whatever core survives.

What this buys, and what it costs, are both structural:

  + Nesting is free. Erosion is monotone, so erode(P,d2) is always inside
    erode(P,d1). The bands partition the state with no running union, no
    double-covering, and no boolean subtlety at all.
  + The anchor disappears. No centroid, no pole of inaccessibility, no
    star-shapedness requirement, no farthest-ray-crossing trick.
  - The silhouette degrades. Offsetting keeps straight edges parallel and
    convex corners sharp, but narrow features (panhandles, capes) are eaten
    entirely, and a non-square rectangle grows progressively squarer instead of
    keeping its proportions.
  - The compact payload dies. An eroded ring is not a transform of the outline,
    so every district needs its own geometry shipped.

The open question this script answers is whether fragmentation actually
improves. It should move rather than vanish: outer collars wrap the whole
boundary and stay connected, but erosion severs a shape at its narrow waists,
so the INNER districts should break up where the homothety's inner districts
were cleanest.

    python scripts/build_inward.py NY MI CO FL HI   # named states, with comparison
    python scripts/build_inward.py --all --gis      # all 50 + GeoJSON
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon

import fetch_data
import pl94
from build_districts import crs_for, lobes_for
from export_gis import clean, districts_for

NL = chr(10)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "derived_inward"
GIS = ROOT / "data" / "gis_inward"

# ROUND, and not for aesthetics -- for correctness. Blocks are binned by their
# Euclidean distance to the border, and the set of points at distance >= d is by
# definition the erosion by a DISK, which is exactly what a round join computes.
# Mitre computes a different shape, so the drawn bands would not correspond to
# the distance bands the population was assigned from.
#
# Mitre was the original choice, to keep Colorado's corners sharp. It also
# collapsed to an empty geometry at large offsets -- Ohio's shells vanished at
# 120 km while its deepest populated block sits at 148 km -- which is how the
# mismatch surfaced. Round gives 3,808 km2 there. Sharp corners were not worth
# geometry that disagreed with its own coordinate.
JOIN_STYLE = 1


def erode(poly, d):
    if d <= 0:
        return poly
    e = poly.buffer(-d, join_style=JOIN_STYLE)
    return clean(e) if not e.is_empty else e


def parts_of(geom):
    if geom.is_empty:
        return []
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def solve_inward(usps, states_gdf, seats_df):
    row = states_gdf[states_gdf["STUSPS"] == usps].iloc[0]
    name = row["NAME"]
    seats = int(seats_df[seats_df["state"].str.casefold() == name.casefold()].iloc[0]["seats"])

    blocks = pl94.load_blocks(pl94.fetch_pl(name, usps))
    occ = blocks[blocks["pop"] > 0]
    crs = crs_for(usps)
    pts = gpd.GeoSeries(gpd.points_from_xy(occ["lon"], occ["lat"]),
                        crs="EPSG:4269").to_crs(crs)
    xs, ys = pts.x.to_numpy(), pts.y.to_numpy()

    geom = gpd.GeoSeries([row["geometry"]], crs=states_gdf.crs).to_crs(crs).iloc[0]
    lobes = [p for p, _ in lobes_for(geom, row["ALAND"])]
    whole = MultiPolygon(lobes) if len(lobes) > 1 else lobes[0]

    # Distance from each block to the nearest border. Blocks outside the
    # generalised outline -- coastal ones, mostly -- are pinned to 0 rather than
    # given a negative depth, so they land in the outermost district where they
    # belong instead of sorting past it.
    P = shapely.points(xs, ys)
    d = shapely.distance(P, whole.boundary)
    inside = shapely.contains_xy(whole, xs, ys)
    d = np.where(inside, d, 0.0)

    order = np.argsort(d, kind="stable")
    pop = occ["pop"].to_numpy()[order]
    d_sorted = d[order]
    cum = np.cumsum(pop)
    total = int(cum[-1])

    offsets = [0.0]
    for k in range(1, seats):
        j = int(np.searchsorted(cum, total * k / seats, side="left"))
        offsets.append(float(d_sorted[min(j, len(d_sorted) - 1)]))

    # District k is the band between offset k-1 and offset k; the last district
    # is everything deeper than the final offset.
    # Erosion is monotone in theory, so it is tempting to take each shell
    # straight from the original polygon and trust them to nest. They do not.
    # GEOS's buffer approximates the true offset curve, each shell approximates
    # it independently, and where consecutive offsets sit closer together than
    # that error the two shells CROSS. Subtracting only the next shell then
    # leaves fragments of much deeper ones behind -- 24,000 km2 of self-overlap
    # in Texas, whose big metros all sit at a similar depth so a dozen offsets
    # crowd into a narrow band.
    #
    # Intersecting each shell with its predecessor forces containment, which
    # makes the bands a partition by construction. Note this is the same failure
    # as the outward variant's double-covering, in a different disguise.
    shells = []
    for p_ in lobes:
        chain, prev = [], None
        for o in offsets:
            sh = erode(p_, o)
            if prev is not None:
                sh = clean(sh.intersection(prev)) if not sh.is_empty else sh
            chain.append(sh)
            prev = sh
        shells.append(chain)
    rings = []
    for k in range(seats):
        band = []
        for li in range(len(lobes)):
            outer = shells[li][k]
            if outer.is_empty:
                continue
            inner = shells[li][k + 1] if k + 1 < seats else None
            b = clean(outer.difference(inner)) if inner is not None and not inner.is_empty else outer
            if not b.is_empty and b.area > 0:
                band.append(b)
        rings.append(clean(shapely.union_all(band)) if band else Polygon())

    # Population actually landing in each band, by the same distance rule.
    edges = np.array(offsets + [np.inf])
    which = np.clip(np.searchsorted(edges, d_sorted, side="right") - 1, 0, seats - 1)
    got = np.bincount(which, weights=pop, minlength=seats).astype(int)

    # Does geometry agree with population assignment: is every block binned into
    # district k actually inside district k's polygon?
    #
    # Scored only over blocks that lie within the state outline at all. cb_500k
    # is generalised, so a large share of coastal population sits outside the
    # drawn boundary -- two thirds of New York's outermost district, which is
    # Manhattan and Brooklyn falling seaward of a 1:500,000 shoreline. Those
    # blocks are pinned to distance 0 and belong in the outermost district;
    # counting them as failures would measure the cartography, not the method.
    ins_sorted = inside[order]
    inside_frac = 1.0
    for k in range(seats):
        m = (which == k) & ins_sorted
        if not m.any() or rings[k].is_empty:
            continue
        hit = shapely.contains_xy(rings[k], xs[order][m], ys[order][m])
        w = pop[m]
        inside_frac = min(inside_frac, float(w[hit].sum() / w.sum()))

    outside_outline = float(pop[~ins_sorted].sum() / pop.sum())

    union = shapely.union_all([r for r in rings if not r.is_empty])
    part_sum = sum(r.area for r in rings)
    overlap = (part_sum - union.area) / union.area if union.area else 0.0
    empty = [k + 1 for k, r in enumerate(rings) if r.is_empty]

    merged = [shapely.union_all([shells[li][k] for li in range(len(lobes))
                                 if not shells[li][k].is_empty]) or Polygon()
              for k in range(seats)]

    return rings, merged, {
        "usps": usps,
        "_overlap_frac": overlap,
        "_pop_inside_geom": inside_frac,
        "_pop_outside_outline": outside_outline,
        "_empty_districts": empty, "state": name, "seats": seats, "population": total, "crs": crs,
        "offsets": offsets,
        "district_pop": got.tolist(),
        "district_pieces": [len(parts_of(r)) for r in rings],
        "district_area_km2": [round(r.area / 1e6, 1) for r in rings],
        "lobes": [[[round(x, 1), round(y, 1)] for x, y in p.exterior.coords] for p in lobes],
        "shells": [
            [[[round(x, 1), round(y, 1)] for x, y in q.exterior.coords]
             for li in range(len(lobes)) for q in parts_of(shells[li][k])]
            for k in range(seats)
        ],
        "_max_dev": float(np.abs((got - total / seats) / (total / seats)).max()),
    }


def write_gis(usps, rings, merged, res, target_crs="EPSG:4326"):
    import pandas as pd
    rows = [{
        "usps": usps, "state": res["state"], "district": k + 1, "seats": res["seats"],
        "population": res["district_pop"][k],
        "area_km2": res["district_area_km2"][k],
        "density_km2": round(res["district_pop"][k] / res["district_area_km2"][k], 1)
                       if res["district_area_km2"][k] > 0 else 0.0,
        "offset_inner_m": round(res["offsets"][k], 1),
        "offset_outer_m": round(res["offsets"][k + 1], 1) if k + 1 < res["seats"] else None,
        "pieces": res["district_pieces"][k],
    } for k in range(res["seats"])]
    # Simplify the SHELLS, then rebuild the bands from them. Simplifying each
    # band on its own moves the two sides of a shared edge independently and
    # opens slivers between neighbours; doing it here means band k and band k+1
    # are cut by the identical simplified curve, so the coverage stays exact.
    # Re-chain afterwards, since simplification can break nesting the same way
    # the raw erosion did.
    simp, prev = [], None
    for m in merged:
        g = m.simplify(100.0, preserve_topology=True) if not m.is_empty else m
        if g.is_empty or g.area <= 0:
            g = m
        if prev is not None and not g.is_empty:
            g = clean(g.intersection(prev))
        simp.append(g)
        prev = g

    trimmed = []
    for k in range(len(rings)):
        outer = simp[k]
        inner = simp[k + 1] if k + 1 < len(simp) else None
        b = clean(outer.difference(inner)) if inner is not None and not inner.is_empty else outer
        trimmed.append(b if not b.is_empty else rings[k])
    gdf = gpd.GeoDataFrame(rows, geometry=trimmed, crs=res["crs"]).to_crs(target_crs)
    GIS.mkdir(parents=True, exist_ok=True)
    path = GIS / f"{usps.lower()}_inward.geojson"
    gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)
    return gdf, path


def main():
    import argparse, time
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("states", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gis", action="store_true", help="also write GeoJSON bands")
    args = ap.parse_args()

    states_gdf = gpd.read_file(fetch_data.fetch_state_boundaries())
    seats_df = fetch_data.load_seats()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.all:
        apportioned = set(seats_df["state"].str.casefold())
        targets = sorted(r["STUSPS"] for _, r in states_gdf.iterrows()
                         if r["NAME"].casefold() in apportioned)
    else:
        targets = [s.upper() for s in args.states] or ["NY", "MI", "CO", "FL", "HI"]

    print(f"{'st':>3} {'seats':>5} | {'outward (current)':>26} | {'inward (erosion)':>26}")
    print(f"{'':>3} {'':>5} | {'contig':>7}{'max pcs':>9}{'pop dev':>10} | "
          f"{'contig':>7}{'max pcs':>9}{'pop dev':>10}")
    print("-" * 74)

    summary, frames, locked = [], [], []
    for usps in targets:
        t0 = time.time()
        try:
            rings, merged, res = solve_inward(usps, states_gdf, seats_df)
        except Exception as exc:
            print(f"{usps:>3}  !! {type(exc).__name__}: {exc}")
            continue
        (OUT / f"{usps.lower()}_inward.json").write_text(json.dumps(res), encoding="utf-8")
        if args.gis:
            try:
                gdf, _ = write_gis(usps, rings, merged, res)
                frames.append(gdf)
            except PermissionError:
                # Almost always the file is open in a desktop GIS. Keep going and
                # report it at the end rather than losing the whole run.
                locked.append(usps)

        old_path = ROOT / "data" / "derived" / f"{usps.lower()}_districts.json"
        op, oc, om, od = [], 0, 0, float("nan")
        if old_path.exists():
            old = json.loads(old_path.read_text(encoding="utf-8"))
            op = old.get("district_pieces", [])
            oc, om = sum(1 for p in op if p == 1), (max(op) if op else 0)
            od = old["qa"]["max_abs_deviation"]

        np_ = res["district_pieces"]
        nc, nm = sum(1 for p in np_ if p == 1), max(np_)
        summary.append({"usps": usps, "seats": res["seats"],
                        "out_contig": oc, "out_max_pieces": om, "out_pop_dev": od,
                        "in_contig": nc, "in_max_pieces": nm,
                        "in_pop_dev": res["_max_dev"], "seconds": round(time.time() - t0, 1)})
        print(f"{usps:>3} {res['seats']:>5} | {oc:>3}/{len(op) or res['seats']:<3}{om:>9}"
              f"{od:>10.4%} | {nc:>3}/{len(np_):<3}{nm:>9}{res['_max_dev']:>10.4%}"
              f"   {time.time()-t0:5.1f}s"
              f"{'  OVERLAP %.3f%%' % (res['_overlap_frac']*100) if res['_overlap_frac'] > 1e-6 else ''}"
              f"{'  EMPTY ' + str(res['_empty_districts']) if res['_empty_districts'] else ''}"
              f"{'  MISBINNED %.2f%%' % ((1-res['_pop_inside_geom'])*100) if res['_pop_inside_geom'] < 0.98 else ''}",
              flush=True)

    if summary:
        import pandas as pd
        df = pd.DataFrame(summary)
        df.to_csv(OUT / "summary_inward.csv", index=False)
        tot = df["seats"].sum()
        print(NL + "=" * 74)
        print(f"{len(df)} states, {tot} districts")
        print(f"single-piece districts   outward {df['out_contig'].sum():>4}/{tot}"
              f"   inward {df['in_contig'].sum():>4}/{tot}")
        print(f"worst fragmentation      outward {df['out_max_pieces'].max():>4}"
              f"       inward {df['in_max_pieces'].max():>4}")
        print(f"worst population dev     outward {df['out_pop_dev'].max():.4%}"
              f"   inward {df['in_pop_dev'].max():.4%}")
        print(NL + "states where inward is WORSE fragmented:")
        w = df[df["in_max_pieces"] > df["out_max_pieces"]]
        print("  none" if w.empty else w[["usps","seats","out_max_pieces","in_max_pieces"]].to_string(index=False))

    if locked:
        print(NL + "LOCKED (open in another program, not rewritten): " + ", ".join(locked))

    if frames:
        import pandas as pd
        allg = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True),
                                geometry="geometry", crs="EPSG:4326")
        path = GIS / "districts_inward.geojson"
        allg.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=6)
        print(NL + f"GeoJSON: {len(allg)} districts -> {path.relative_to(ROOT)} "
              f"({path.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
