#!/usr/bin/env python3
"""
Solve the nested-silhouette districts for one or more states.

The method, in one paragraph. A state is decomposed into lobes (its major
polygon parts -- one for most states, two for Michigan, seven for Hawaii). Each
lobe gets an anchor point. Every populated census block is given a radial
coordinate s in [0,1]: the scale factor at which a copy of that lobe's outline,
shrunk about the anchor, would pass through the block. Blocks are then sorted by
s statewide, population is accumulated, and the k-th district boundary is the s
where the running total crosses k/n of the state. District k is the region
between scaled outline s(k-1) and scaled outline s(k) -- an annulus, except for
district 1, which is a solid scaled copy of the state.

Two consequences worth stating plainly:

  - Ring width is inverse population density along that radial band. Where the
    ring is thin, people are packed. This is what the map actually measures.
  - Because s is measured per lobe but sorted statewide, district k picks up a
    ring from every lobe at the same relative radius. Michigan's districts come
    in two pieces; Hawaii's in seven. They are equal-population statewide.

The radial coordinate uses the FARTHEST ray-boundary crossing, not the nearest.
That is what makes the method survive states that are not star-shaped about
their anchor -- Idaho's panhandle, Oklahoma's, Maryland's. Every s stays in
[0,1] and the scaled outlines still nest, at the cost of the outer rings poking
across the state boundary where a lobe is deeply concave. That overhang is real
and is reported, not hidden.

Usage:
    python scripts/build_districts.py IL ID MI
"""

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import affinity
from shapely.geometry import Polygon

import fetch_data
import pl94

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ROOT / "data" / "derived"

# CONUS Albers equal area. Homothetic scaling is only meaningful in a projected
# CRS, and an equal-area one keeps "population per unit area" honest.
CRS_WORK = "EPSG:5070"

# Alaska and Hawaii sit far outside CONUS Albers' zone of validity, where it
# does not merely distort but shears the outline into something that is not the
# state's silhouette at all -- and the silhouette is the entire premise. Each
# gets an equal-area projection centered on itself. Because every state is drawn
# from its own outline, anchor and scale factors, mixing CRSs across states costs
# nothing: national layout places AK and HI as insets anyway, exactly as
# geoAlbersUsa does.
CRS_BY_STATE = {
    "AK": "EPSG:3338",
    "HI": ("+proj=aea +lat_1=19 +lat_2=22 +lat_0=20.5 +lon_0=-157 "
           "+datum=NAD83 +units=m +no_defs"),
}


def crs_for(usps: str) -> str:
    return CRS_BY_STATE.get(usps, CRS_WORK)

# A polygon part becomes its own lobe at or above this share of state land area.
# Below it, the part is dropped from the drawn silhouette and its blocks are
# assigned to the nearest surviving lobe. At 1% Michigan keeps its two
# peninsulas and sheds Isle Royale; Hawaii keeps its seven inhabited islands.
LOBE_MIN_AREA_SHARE = 0.01

# Tolerance for simplifying lobe outlines before solving. See lobes_for.
SOLVE_SIMPLIFY_M = 250.0


def anchor_for(poly: Polygon) -> tuple[float, float]:
    """
    A visually centered point guaranteed to lie inside the polygon.

    The plain centroid falls outside its own state often enough to matter
    (Michigan into Lake Michigan, Hawaii into open ocean). Pole of
    inaccessibility -- the interior point farthest from any edge -- is both
    always inside and better centered for a map, which is the only thing the
    anchor has to be: it carries no analytical meaning here.
    """
    try:
        from shapely.algorithms.polylabel import polylabel
        tol = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) / 1000
        p = polylabel(poly, tolerance=max(tol, 1.0))
    except Exception:
        p = poly.representative_point()
    return float(p.x), float(p.y)


def radial_coord(anchor, boundary, xs, ys):
    """
    s for each point: |p - a| divided by the anchor-to-boundary distance along
    the same ray, taking the farthest crossing.

    Vectorized: one ray per point, a single batched intersection against the
    lobe's exterior ring, then a grouped max over the resulting coordinates.
    """
    ax, ay = anchor
    dx, dy = xs - ax, ys - ay
    d = np.hypot(dx, dy)
    safe = np.where(d > 0, d, 1.0)
    ux, uy = dx / safe, dy / safe

    minx, miny, maxx, maxy = boundary.bounds
    far = 2.0 * np.hypot(maxx - minx, maxy - miny)

    n = len(xs)
    coords = np.empty((2 * n, 2))
    coords[0::2, 0] = ax
    coords[0::2, 1] = ay
    coords[1::2, 0] = ax + ux * far
    coords[1::2, 1] = ay + uy * far
    idx = np.repeat(np.arange(n), 2)
    rays = shapely.linestrings(coords, indices=idx)

    hits = shapely.intersection(rays, boundary)
    hx, hidx = shapely.get_coordinates(hits, return_index=True)

    R = np.zeros(n)
    if len(hx):
        np.maximum.at(R, hidx, np.hypot(hx[:, 0] - ax, hx[:, 1] - ay))

    s = np.divide(d, R, out=np.ones(n), where=R > 0)
    return np.clip(s, 0.0, 1.0), R


def lobes_for(geom, land_area):
    """
    Major polygon parts, largest first, as (polygon, share_of_land_area).

    Parts are simplified on the way out, and that is a performance decision with
    a correctness argument behind it. Ray-casting cost is linear in vertex
    count, and Michigan's cb_500k shoreline carries ~15,000 of them: solving it
    unsimplified took 345 seconds, nearly all of it in the ray pass. At a 250 m
    tolerance the anchor-to-boundary distance moves by well under 0.3% of a
    typical radius, which is far below the width of the thinnest ring we draw.

    The argument for it: the web map draws a 300 m-simplified outline, so
    solving against a comparably simplified boundary makes the breakpoints agree
    with the geometry a reader actually sees. Solving at full resolution and
    drawing simplified would be the inconsistent choice, not this.
    """
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    parts.sort(key=lambda p: p.area, reverse=True)
    total = sum(p.area for p in parts)
    kept = [p for p in parts if p.area / total >= LOBE_MIN_AREA_SHARE] or [parts[0]]

    out = []
    for p in kept:
        small = p.simplify(SOLVE_SIMPLIFY_M, preserve_topology=True)
        if small.is_empty or small.area <= 0:
            small = p
        if small.geom_type == "MultiPolygon":
            small = max(small.geoms, key=lambda g: g.area)
        out.append((small, p.area / total))
    return out


def build_state(usps: str, states_gdf: pd.DataFrame, seats_df: pd.DataFrame, verbose=True):
    row = states_gdf[states_gdf["STUSPS"] == usps]
    if row.empty:
        sys.exit(f"{usps}: not in the cartographic boundary file")
    row = row.iloc[0]
    name = row["NAME"]

    seat_row = seats_df[seats_df["state"].str.casefold() == name.casefold()]
    if seat_row.empty:
        sys.exit(f"{name}: no apportionment row (DC and territories have no seats)")
    seats = int(seat_row.iloc[0]["seats"])

    blocks = pl94.load_blocks(pl94.fetch_pl(name, usps))
    occupied = blocks[blocks["pop"] > 0].copy()

    crs = crs_for(usps)
    pts = gpd.GeoSeries(
        gpd.points_from_xy(occupied["lon"], occupied["lat"]), crs="EPSG:4269"
    ).to_crs(crs)
    xs = pts.x.to_numpy()
    ys = pts.y.to_numpy()

    geom = gpd.GeoSeries([row["geometry"]], crs=states_gdf.crs).to_crs(crs).iloc[0]
    lobes = lobes_for(geom, row["ALAND"])
    # polylabel is not cheap and the anchor is needed in four places; fix it once
    # so every stage of the solve and the emitted file agree on the same point.
    anchors = [anchor_for(p) for p, _ in lobes]

    # Assign each block to a lobe by proximity. Containment is the wrong test:
    # cb_500k is generalized, so a lot of genuinely coastal blocks sit just
    # outside the drawn outline.
    polys = [p for p, _ in lobes]
    dists = np.column_stack([shapely.distance(shapely.points(xs, ys), p) for p in polys])
    lobe_of = dists.argmin(axis=1)

    s = np.empty(len(occupied))
    overhang = np.zeros(len(lobes), dtype=int)
    for i, (poly, _) in enumerate(lobes):
        m = lobe_of == i
        if not m.any():
            continue
        s_i, _ = radial_coord(anchors[i], poly.exterior, xs[m], ys[m])
        s[m] = s_i
        overhang[i] = int((dists[m, i] > 0).sum())

    occupied["s"] = s
    occupied["lobe"] = lobe_of

    order = occupied.sort_values("s", kind="stable")
    cum = order["pop"].cumsum().to_numpy()
    total_pop = int(cum[-1])
    s_sorted = order["s"].to_numpy()

    # Breakpoints: the s at which the running population crosses k/n.
    breaks = [0.0]
    for k in range(1, seats):
        target = total_pop * k / seats
        j = int(np.searchsorted(cum, target, side="left"))
        breaks.append(float(s_sorted[min(j, len(s_sorted) - 1)]))
    breaks.append(1.0)
    breaks = sorted(breaks)

    # QA: what each district actually got, versus the ideal.
    edges = np.array(breaks)
    which = np.clip(np.searchsorted(edges, s_sorted, side="right") - 1, 0, seats - 1)
    got = np.bincount(which, weights=order["pop"].to_numpy(), minlength=seats).astype(int)
    ideal = total_pop / seats
    dev = (got - ideal) / ideal

    # Does a scaled copy escape its own lobe? Using the farthest ray crossing
    # keeps every s in [0,1], but on a deeply concave lobe a shrunk outline can
    # still cross the real boundary. Measure it rather than assume it away.
    # The same pass produces the drawn area of each district. Area has to be
    # measured on the CLIPPED copy, since that is what the map actually shows,
    # and it is what turns ring width into a real density rather than a
    # unitless one -- letting the two encodings be checked against each other.
    escape = 0.0
    cum_area = np.zeros(len(breaks))
    for (poly, _), (ax_, ay_) in zip(lobes, anchors):
        for i, b in enumerate(breaks):
            if b <= 0:
                continue
            if b >= 1.0:
                cum_area[i] += poly.area
                continue
            copy = affinity.scale(poly, xfact=b, yfact=b, origin=(ax_, ay_))
            if copy.area <= 0:
                continue
            # One boolean op, not two: the escaped area is whatever the
            # intersection did not keep, so difference() is redundant.
            inter = copy.intersection(poly).area
            cum_area[i] += inter
            escape = max(escape, 1.0 - inter / copy.area)

    area_km2 = np.diff(cum_area) / 1e6
    density = np.divide(got, area_km2, out=np.zeros(seats), where=area_km2 > 0)

    result = {
        "state": name,
        "usps": usps,
        "seats": seats,
        "population": total_pop,
        "ideal_per_district": round(ideal, 1),
        "crs": crs,
        "breaks": [round(b, 6) for b in breaks],
        "district_pop": got.tolist(),
        "district_area_km2": [round(float(a), 1) for a in area_km2],
        "district_density": [round(float(d), 1) for d in density],
        "lobes": [
            {
                "anchor": [round(a[0], 1), round(a[1], 1)],
                "area_share": round(share, 4),
                "outline": [[round(x, 1), round(y, 1)] for x, y in p.exterior.coords],
            }
            for (p, share), a in zip(lobes, anchors)
        ],
        "qa": {
            "district_pop": got.tolist(),
            "max_abs_deviation": round(float(np.abs(dev).max()), 5),
            "blocks_total": int(len(blocks)),
            "blocks_occupied": int(len(occupied)),
            "blocks_outside_outline": int(overhang.sum()),
            "max_ring_escape_frac": round(float(escape), 5),
        },
    }

    if verbose:
        print(f"\n=== {name} ({usps}) — {seats} seats")
        print(f"  population {total_pop:,}   ideal/district {ideal:,.0f}")
        print(f"  lobes: {len(lobes)}  " +
              ", ".join(f"{sh:.1%}" for _, sh in lobes))
        print(f"  blocks {len(blocks):,} ({len(occupied):,} occupied), "
              f"{overhang.sum():,} outside the generalized outline")
        print(f"  max population deviation: {np.abs(dev).max():.3%}")
        print(f"  max ring escape outside lobe: {escape:.3%} of ring area")
        widths = np.diff(edges)
        print(f"  thinnest ring {widths.min():.4f}  thickest {widths.max():.4f} "
              f"(ratio {widths.max()/max(widths.min(),1e-9):.0f}x)")
        nz = density[density > 0]
        if len(nz):
            print(f"  district density {nz.min():,.0f} to {nz.max():,.0f} people/km2 "
                  f"({nz.max()/nz.min():.0f}x)")

    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="*", help="USPS codes, e.g. IL ID MI")
    ap.add_argument("--all", action="store_true", help="every apportioned state")
    args = ap.parse_args()

    # Left in its native CRS; build_state reprojects per state, since Alaska and
    # Hawaii do not share CONUS Albers.
    states_gdf = gpd.read_file(fetch_data.fetch_state_boundaries())
    seats_df = fetch_data.load_seats()

    if args.all:
        apportioned = set(seats_df["state"].str.casefold())
        targets = sorted(
            r["STUSPS"] for _, r in states_gdf.iterrows()
            if r["NAME"].casefold() in apportioned
        )
    else:
        targets = [s.upper() for s in args.states]
    if not targets:
        sys.exit("Name some states, or pass --all.")

    DERIVED.mkdir(parents=True, exist_ok=True)
    summary, failed = [], []
    for i, usps in enumerate(targets, 1):
        t0 = time.time()
        print(f"\n[{i}/{len(targets)}]", end="")
        try:
            result = build_state(usps, states_gdf, seats_df)
        except Exception as exc:
            print(f"  !! {usps} failed: {type(exc).__name__}: {exc}")
            failed.append(usps)
            continue
        out = DERIVED / f"{usps.lower()}_districts.json"
        out.write_text(json.dumps(result), encoding="utf-8")
        w = np.diff(np.array(result["breaks"]))
        dens = np.array([d for d in result["district_density"] if d > 0])
        summary.append({
            "density_min": round(float(dens.min()), 1) if len(dens) else 0.0,
            "density_max": round(float(dens.max()), 1) if len(dens) else 0.0,
            "density_ratio": round(float(dens.max() / dens.min()), 1) if len(dens) else 0.0,
            "usps": usps,
            "state": result["state"],
            "seats": result["seats"],
            "population": result["population"],
            "lobes": len(result["lobes"]),
            "thinnest_ring": round(float(w.min()), 5),
            "thickest_ring": round(float(w.max()), 5),
            "ring_ratio": round(float(w.max() / max(w.min(), 1e-9)), 1),
            "max_pop_dev": result["qa"]["max_abs_deviation"],
            "ring_escape": result["qa"]["max_ring_escape_frac"],
            "kb": round(out.stat().st_size / 1e3, 1),
            "seconds": round(time.time() - t0, 1),
        })
        print(f"  -> {out.name} ({out.stat().st_size/1e3:.0f} KB, {time.time()-t0:.1f}s)")

    if summary:
        df = pd.DataFrame(summary).sort_values("ring_ratio", ascending=False)
        path = DERIVED / "summary.csv"
        df.to_csv(path, index=False)
        print(f"\n{'='*70}\nwrote {path.relative_to(ROOT)}  "
              f"({len(df)} states, {df['kb'].sum()/1e3:.1f} MB total)\n")
        print("Most lopsided states (ring_ratio = thickest ring / thinnest):")
        print(df.head(12)[["usps", "seats", "ring_ratio", "max_pop_dev",
                           "ring_escape", "lobes"]].to_string(index=False))
        print("\nWorst population deviation:")
        print(df.nlargest(5, "max_pop_dev")[["usps", "seats", "max_pop_dev"]]
              .to_string(index=False))
        print("\nWorst ring escape (fraction of ring area outside the lobe):")
        print(df.nlargest(5, "ring_escape")[["usps", "seats", "ring_escape", "lobes"]]
              .to_string(index=False))
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")


if __name__ == "__main__":
    main()
