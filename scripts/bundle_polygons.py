#!/usr/bin/env python3
"""
Merge the inward / meridian / parallel solutions into web payloads.

Why this exists alongside bundle.py
-----------------------------------
The outward model ships as one outline per state plus a table of scale factors,
because every district there IS the state outline scaled about a fixed point.
435 districts for 0.85 MB. None of the other three models can do that:

  inward    erosion shells -- offsetting is not a homothety, so the shape
            changes as it goes in and no scale factor reproduces it
  meridian  half-plane cuts; a meridian is a straight but TILTED line in Albers
  parallel  a parallel is an ARC in Albers, so the cut is curved

They split two ways on whether the bands can still be left to z-order.

INWARD still can, and does. The solver already emits `shells`: shells[0] is the
whole state and shells[k] is the state eroded to district k+1's inner edge, so
successive differences ARE the districts -- verified against district_area_km2
to the metre. Those nest, so the app paints them largest first and z-order
carves the bands exactly as it does for the outward model. Only the source of
the nested shapes differs: generated from a scale factor there, shipped here.

MERIDIAN and PARALLEL cannot. Their slabs are disjoint, and the nested form
would be strictly worse: the cumulative union at level k re-carries every bit of
coastline west of cut k, so meridian goes from 0.7 MB as slabs to 3.6 MB nested.
They ship as disjoint polygons and the app draws each one directly.

Both forms reach the app as the same thing -- a list of shapes per state, one
per district, painted largest first -- so there is a single code path. Disjoint
shapes do not care about paint order, and nested ones need exactly that order.

Framing
-------
frame_bbox, placement and color_offsets are copied verbatim from the outward
bundle rather than recomputed. All four models are solved from the same cb_500k
outlines, so the extents agree anyway -- but copying makes them agree exactly,
which is what lets a reader flip between the four maps and see only the
districting change.

Geometry sources differ by model: inward carries its shells in the derived JSON
already in the state's own CRS, while the stripe models keep geometry only in
the GeoJSON exports, in WGS84, so those are projected back per state.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import LinearRing, Polygon, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parent.parent
OUTWARD = ROOT / "data" / "districts.json"

MODELS = {
    "inward":   {"derived": "derived_inward",   "gis": "gis_inward",   "suffix": "inward"},
    "meridian": {"derived": "derived_meridian", "gis": "gis_meridian", "suffix": "meridian"},
    "parallel": {"derived": "derived_parallel", "gis": "gis_parallel", "suffix": "parallel"},
}

# At national scale a state is ~150 px wide -- about 3 km per pixel -- so a
# tolerance of 600 m is a fifth of a pixel. That matters more here than it does
# for the outward model: these districts are simplified INDEPENDENTLY of each
# other, so any tolerance also bounds how far two neighbours can drift apart
# along a boundary they are supposed to share. Keeping it well under a pixel is
# what keeps that drift invisible rather than a visible seam.
DEFAULT_TOL = {"inward": 600.0, "meridian": 400.0, "parallel": 400.0}


def rings_of(geom):
    """Every ring of a (Multi)Polygon, exteriors and holes alike.

    They go into a single <path> drawn with fill-rule: evenodd, which resolves
    containment on its own -- so the bundle never has to record which ring is a
    hole, and a district that is both multi-part and holed (Michigan's outermost
    collar spans two lobes) needs no special case.
    """
    if geom.is_empty:
        return []
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for p in polys:
        out.append(list(p.exterior.coords))
        out.extend(list(r.coords) for r in p.interiors)
    return out


def clean(geom, tol):
    if not geom.is_valid:
        geom = geom.buffer(0)
    small = geom.simplify(tol, preserve_topology=True)
    return geom if small.is_empty or small.area <= 0 else small


def simplify_rings(rings, tol):
    """Simplify a flat ring list WITHOUT reinterpreting it.

    An inward shell arrives as a bare list of rings, some of which are holes --
    the erosion of a state with a bay in it. Rebuilding a polygon from them and
    unioning fills those holes, which is how California's outermost shell first
    came out 180x too large. Each ring is instead simplified on its own and
    handed through in place, leaving the exterior/hole question to fill-rule:
    evenodd at draw time, exactly as the solver's own GeoJSON export leaves it.
    """
    out = []
    for r in rings:
        if len(r) < 4:
            continue
        ring = LinearRing(r)
        small = ring.simplify(tol, preserve_topology=False)
        # simplify can degenerate a small island to a sliver; keep the original.
        coords = list(small.coords) if len(small.coords) >= 4 else list(ring.coords)
        out.append(coords)
    return out


def ring_out(ring):
    """Decimetre precision, and drop the repeated closing point -- the renderer
    closes every ring with Z."""
    pts = [[round(x, 1), round(y, 1)] for x, y in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def load_state(model, derived_path, tol):
    spec = json.loads(derived_path.read_text(encoding="utf-8"))
    usps, crs = spec["usps"], spec["crs"]

    if model == "inward":
        # Already in the state's own CRS, and already NESTED: shells[0] is the
        # whole state and shells[k] is the state eroded to district k+1's inner
        # edge, so successive differences are the districts. That is the same
        # back-to-front structure the outward model gets from its scale factors,
        # so the app paints these the same way and z-order carves the bands.
        shapes = [simplify_rings(shell, tol) for shell in spec["shells"]]
    else:
        # Stripe models keep geometry only in the WGS84 export.
        gis = ROOT / "data" / MODELS[model]["gis"] / f"{usps.lower()}_{MODELS[model]['suffix']}.geojson"
        fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        feats = sorted(json.loads(gis.read_text(encoding="utf-8"))["features"],
                       key=lambda f: f["properties"]["district"])
        shapes = [rings_of(clean(shp_transform(fwd, shape(f["geometry"])), tol))
                  for f in feats]

    if len(shapes) != spec["seats"]:
        raise SystemExit(f"{usps} {model}: {len(shapes)} shapes for {spec['seats']} seats")

    pop = spec["district_pop"]
    area = spec["district_area_km2"]
    dens = spec.get("district_density") or [
        round(p / a, 1) if a else 0.0 for p, a in zip(pop, area)]

    return {
        "usps": usps,
        "state": spec["state"],
        "seats": spec["seats"],
        "population": spec["population"],
        "crs": crs,
        "district_pop": pop,
        "district_area_km2": area,
        "district_density": dens,
        "district_pieces": spec.get("district_pieces", [1] * spec["seats"]),
        "shapes": [[ring_out(r) for r in sh] for sh in shapes],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--tolerance", type=float, default=None,
                    help="override the per-model default, in metres")
    args = ap.parse_args()

    if not OUTWARD.exists():
        raise SystemExit("data/districts.json missing. Run bundle.py first -- the "
                         "national frame is copied from it so all four models register.")
    om = json.loads(OUTWARD.read_text(encoding="utf-8"))["meta"]

    for model in args.models:
        tol = args.tolerance if args.tolerance is not None else DEFAULT_TOL[model]
        d = ROOT / "data" / MODELS[model]["derived"]
        files = sorted(d.glob(f"*_{MODELS[model]['suffix']}.json"))
        if not files:
            raise SystemExit(f"No solved states in data/{MODELS[model]['derived']}.")

        states = [load_state(model, f, tol) for f in files]
        rings = sum(len(s) for st in states for s in st["shapes"])
        pts = sum(len(r) for st in states for s in st["shapes"] for r in s)

        bundle = {
            "meta": {
                "generated": date.today().isoformat(),
                "model": model,
                # Whether shapes[k+1] sits inside shapes[k]. True for inward,
                # where the app paints largest-first and lets z-order carve the
                # bands; false for the stripe models, whose slabs are disjoint
                # and where paint order is therefore irrelevant. The app uses it
                # for one thing only: a nested model's outermost shape IS the
                # state outline, so it gets the full-weight silhouette stroke.
                "shapes_nested": model == "inward",
                "simplify_tolerance_m": tol,
                "conus_crs": om["conus_crs"],
                # Copied, not recomputed: identical framing is what lets the four
                # maps be compared by flipping between them.
                "frame_bbox": om["frame_bbox"],
                "placement": om["placement"],
                "color_offsets": om["color_offsets"],
                "color_cycle": om["color_cycle"],
                "seats_total": sum(s["seats"] for s in states),
                "contiguous_districts": sum(
                    sum(1 for p in s["district_pieces"] if p == 1) for s in states),
                "population_total": sum(s["population"] for s in states),
                "sources": om["sources"],
            },
            "states": sorted(states, key=lambda s: s["usps"]),
        }

        out = ROOT / "data" / f"{model}.json"
        out.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
        mb = out.stat().st_size / 1e6
        print(f"{model:9} {len(states)} states  {bundle['meta']['seats_total']} seats  "
              f"{rings:,} rings  {pts:,} points  tol {tol:.0f} m  ->  {mb:.2f} MB")
        if mb > 3:
            print("   NOTE: over 3 MB; raise --tolerance before publishing")


if __name__ == "__main__":
    main()
