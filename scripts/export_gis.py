#!/usr/bin/env python3
"""
Export the solved districts as real GeoJSON polygons.

The web map never builds a ring. It paints solid scaled copies back to front and
lets z-order produce the annulus, which is why the payload is fifty outlines and
a table of scale factors instead of 435 polygons. That trick does not survive
contact with GIS, so this script materialises what the map only implies:

    district k = (copy_k  clipped to the lobe)  minus  copy_(k-1)

Subtracting the UNCLIPPED inner copy is deliberate. Anything of it that fell
outside the lobe was already removed by the clip, so the difference cannot leave
a sliver of inner district stranded in the outer one.

Two things that fall out of the construction and are worth trusting:

  - Ring k's inner edge is ring k-1's outer edge, the same arc, so the result is
    a clean coverage with no gaps or slivers between districts.
  - Districts 2..n are genuine polygons with interior rings. Multi-lobe states
    (Michigan's two peninsulas, Hawaii's seven islands) come out as
    MultiPolygons, which is the honest representation of a district that really
    is in several pieces.

The national map's Alaska and Hawaii insets are a DISPLAY transform and are not
applied here. Exported states sit at their true locations, so the layer will not
look like the map. That is correct, not a bug.

    python scripts/export_gis.py                    # all states, one file, WGS84
    python scripts/export_gis.py --states IL MI HI  # just these, one file each
    python scripts/export_gis.py --crs EPSG:5070    # keep projected metres
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely import affinity
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ROOT / "data" / "derived"
OUT = ROOT / "data" / "gis"


def clean(geom):
    """GEOS can hand back a self-touching ring after a difference; fix quietly."""
    if geom.is_empty or geom.is_valid:
        return geom
    fixed = geom.buffer(0)
    return fixed if not fixed.is_empty else geom


def districts_for(spec):
    """Yield (k, geometry) for each district in one state, in its native CRS."""
    lobes = [(Polygon(l["outline"]), tuple(l["anchor"])) for l in spec["lobes"]]
    breaks = spec["breaks"]

    # Cache each scale factor's copy per lobe: every copy is used twice, once as
    # a district's outer edge and once as the next district's inner edge.
    copies = []
    for poly, anchor in lobes:
        per_lobe = {}
        for k, s in enumerate(breaks):
            if s <= 0:
                per_lobe[k] = None
            elif s >= 1.0:
                per_lobe[k] = poly
            else:
                per_lobe[k] = affinity.scale(poly, xfact=s, yfact=s, origin=anchor)
        copies.append(per_lobe)

    # A point belongs to the SMALLEST k whose copy contains it -- that is what
    # the back-to-front painting produces on screen, since every smaller copy is
    # drawn on top. So each ring subtracts the union of ALL inner copies, not
    # merely the previous one.
    #
    # Subtracting only copy_(k-1) is wrong for exactly the reason this project
    # needs the farthest ray crossing: on a concave lobe the copies are not
    # monotonically nested, so a piece of district 3 can sit outside copy_5 and
    # inside copy_6 and end up claimed twice. That bug double-covered 1.5% of
    # Illinois before this was fixed.
    accum = [None] * len(lobes)

    for k in range(1, spec["seats"] + 1):
        parts = []
        for li, ((poly, _), per_lobe) in enumerate(zip(lobes, copies)):
            outer = per_lobe[k]
            if outer is None or outer.is_empty:
                continue
            band = clean(outer.intersection(poly))
            prior = accum[li]
            if prior is not None and not prior.is_empty:
                band = clean(band.difference(prior))
            accum[li] = outer if prior is None else clean(shapely.union_all([prior, outer]))
            if not band.is_empty and band.area > 0:
                parts.append(band)
        if parts:
            yield k, clean(shapely.union_all(parts))


def build(usps, target_crs):
    spec = json.loads((DERIVED / f"{usps.lower()}_districts.json").read_text(encoding="utf-8"))
    rows, geoms = [], []
    for k, geom in districts_for(spec):
        rows.append({
            "usps": spec["usps"],
            "state": spec["state"],
            "district": k,
            "seats": spec["seats"],
            "population": spec["district_pop"][k - 1],
            "area_km2": spec["district_area_km2"][k - 1],
            "density_km2": spec["district_density"][k - 1],
            "s_inner": spec["breaks"][k - 1],
            "s_outer": spec["breaks"][k],
            "ring_width": round(spec["breaks"][k] - spec["breaks"][k - 1], 6),
            "pieces": len(geom.geoms) if geom.geom_type == "MultiPolygon" else 1,
        })
        geoms.append(geom)

    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=spec["crs"])

    # Checks against the solver's own numbers, before any reprojection distorts
    # area. A silent mismatch here would mean the boolean rebuild disagrees with
    # the map, which is the whole thing this script must not do.
    pop_ok = gdf["population"].sum() == spec["population"]
    solved = sum(spec["district_area_km2"])
    rebuilt = gdf.geometry.area.sum() / 1e6
    area_err = abs(rebuilt - solved) / solved if solved else 0.0
    invalid = int((~gdf.geometry.is_valid).sum())

    return gdf.to_crs(target_crs), {
        "usps": usps, "districts": len(gdf), "pop_ok": pop_ok,
        "area_err": area_err, "invalid": invalid,
        "pieces_max": int(gdf["pieces"].max()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--states", nargs="*", default=[], help="USPS codes; default all")
    ap.add_argument("--crs", default="EPSG:4326",
                    help="output CRS (default EPSG:4326, per the GeoJSON spec)")
    ap.add_argument("--separate", action="store_true",
                    help="one file per state instead of one combined file")
    # OGR writes 15 significant digits by default, which more than doubles the
    # file for precision no census geometry has. Six decimal degrees is ~0.11 m.
    ap.add_argument("--precision", type=int, default=6,
                    help="coordinate decimal places (default 6, ~0.11 m)")
    args = ap.parse_args()

    targets = [s.upper() for s in args.states] or sorted(
        f.name[:2].upper() for f in DERIVED.glob("*_districts.json"))
    OUT.mkdir(parents=True, exist_ok=True)

    frames, report = [], []
    for usps in targets:
        gdf, qa = build(usps, args.crs)
        report.append(qa)
        if args.separate or len(targets) == 1:
            path = OUT / f"{usps.lower()}_districts.geojson"
            gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=args.precision)
            print(f"  {usps}  {len(gdf):>2} districts -> {path.name} "
                  f"({path.stat().st_size/1e3:.0f} KB)")
        else:
            frames.append(gdf)

    if frames:
        allgdf = pd.concat(frames, ignore_index=True)
        allgdf = gpd.GeoDataFrame(allgdf, geometry="geometry", crs=args.crs)
        path = OUT / "districts.geojson"
        allgdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=args.precision)
        print(f"\n{len(allgdf)} districts, {len(frames)} states -> "
              f"{path.relative_to(ROOT)} ({path.stat().st_size/1e6:.2f} MB)")

    df = pd.DataFrame(report)
    bad = df[(~df["pop_ok"]) | (df["area_err"] > 0.01) | (df["invalid"] > 0)]
    print(f"\nCRS out: {args.crs}   districts: {df['districts'].sum()}")
    print(f"population matches solver: {df['pop_ok'].all()}")
    print(f"worst area disagreement vs solver: {df['area_err'].max():.4%}")
    print(f"invalid geometries: {df['invalid'].sum()}")
    multi = df[df["pieces_max"] > 1]
    if len(multi):
        print("multi-piece districts in: " +
              ", ".join(f"{r.usps}({r.pieces_max})" for r in multi.itertuples()))
    if len(bad):
        print("\nCHECK THESE:")
        print(bad.to_string(index=False))


if __name__ == "__main__":
    main()
