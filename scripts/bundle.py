#!/usr/bin/env python3
"""
Merge the per-state solutions into one web payload.

Two jobs.

SIMPLIFY. The solver works from cb_500k outlines, which carry far more vertices
than any screen can show: at national scale a state is ~150 px wide, or about
3 km per pixel. Simplifying to a 300 m tolerance is a tenth of a pixel there and
half a pixel in a full-window single-state view, so it is invisible at both
sizes while cutting the payload severalfold. The rings are drawn as transforms
of this one outline, so simplifying it once shrinks all 435 districts at once --
which is the whole reason the payload stays small enough to ship as a single
fetch.

PLACE. Every CONUS state is already solved in EPSG:5070, so their coordinates
share one frame and the national map is just a direct draw. Alaska and Hawaii
are solved in their own equal-area projections and therefore need explicit inset
transforms, the same compromise geoAlbersUsa makes. Those transforms are
computed here, not hardcoded in the app.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ROOT / "data" / "derived"
OUT = ROOT / "data" / "districts.json"

SIMPLIFY_M = 300.0

# Fraction of the CONUS bounding-box width each inset is scaled to, and where its
# lower-left corner sits as a fraction of that box. The y offsets are negative:
# the insets hang below CONUS rather than inside it, because at the sizes
# geoAlbersUsa uses, an Alaska tucked into the lower left corner overlaps the
# Southwest. The frame is widened to fit them instead.
# Alaska is deliberately below true relative size, as on most US maps, and it is
# a single district so there is no ring structure to lose. Hawaii is deliberately
# ABOVE it: at a truthful scale its islands are specks, and it is the only state
# whose districts come in seven pieces, which is worth being able to see.
INSETS = {
    "AK": {"scale_frac": 0.30, "at": (0.02, -0.25)},
    "HI": {"scale_frac": 0.22, "at": (0.40, -0.20)},
}


def simplify_outline(outline, tol):
    """Simplify a closed ring, preserving its topology and its closure."""
    poly = Polygon(outline)
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
    small = poly.simplify(tol, preserve_topology=True)
    if small.is_empty or small.area <= 0:
        small = poly
    return [[round(x, 1), round(y, 1)] for x, y in small.exterior.coords]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tolerance", type=float, default=SIMPLIFY_M,
                    help="simplification tolerance in metres")
    args = ap.parse_args()

    files = sorted(DERIVED.glob("*_districts.json"))
    if not files:
        raise SystemExit("No solved states in data/derived. Run build_districts.py --all.")

    states, before, after = [], 0, 0
    for f in files:
        spec = json.loads(f.read_text(encoding="utf-8"))
        for lobe in spec["lobes"]:
            before += len(lobe["outline"])
            lobe["outline"] = simplify_outline(lobe["outline"], args.tolerance)
            after += len(lobe["outline"])
        states.append(spec)

    # CONUS extent, used both to frame the map and to size the insets.
    conus = [s for s in states if s["usps"] not in INSETS]
    pts = np.vstack([np.asarray(l["outline"]) for s in conus for l in s["lobes"]])
    x0, y0, x1, y1 = pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()
    w, h = x1 - x0, y1 - y0

    placement = {}
    fx0, fy0, fx1, fy1 = x0, y0, x1, y1
    for usps, cfg in INSETS.items():
        s = next((st for st in states if st["usps"] == usps), None)
        if s is None:
            continue
        p = np.vstack([np.asarray(l["outline"]) for l in s["lobes"]])
        sx0, sy0, sx1, sy1 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
        k = (w * cfg["scale_frac"]) / max(sx1 - sx0, 1.0)
        tx = x0 + cfg["at"][0] * w - sx0 * k
        ty = y0 + cfg["at"][1] * h - sy0 * k
        placement[usps] = {"scale": round(float(k), 6),
                           "translate": [round(float(tx), 1), round(float(ty), 1)]}
        # Grow the frame to contain the placed inset.
        fx0, fy0 = min(fx0, sx0 * k + tx), min(fy0, sy0 * k + ty)
        fx1, fy1 = max(fx1, sx1 * k + tx), max(fy1, sy1 * k + ty)

    bundle = {
        "meta": {
            "generated": date.today().isoformat(),
            "simplify_tolerance_m": args.tolerance,
            "conus_crs": "EPSG:5070",
            "conus_bbox": [round(float(v), 1) for v in (x0, y0, x1, y1)],
            # Full drawing extent including the placed insets: the app's viewBox.
            "frame_bbox": [round(float(v), 1) for v in (fx0, fy0, fx1, fy1)],
            "placement": placement,
            "seats_total": sum(s["seats"] for s in states),
            "contiguous_districts": sum(
                sum(1 for p in s.get("district_pieces", []) if p == 1) for s in states),
            "population_total": sum(s["population"] for s in states),
            "sources": {
                "population": "2020 Census P.L. 94-171 Redistricting Data, block level",
                "boundaries": "US Census cb_2020_us_state_500k cartographic boundaries",
                "apportionment": "2020 Census Apportionment Results, Table 1",
            },
        },
        "states": sorted(states, key=lambda s: s["usps"]),
    }

    OUT.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    mb = OUT.stat().st_size / 1e6
    print(f"{len(states)} states, {bundle['meta']['seats_total']} seats")
    print(f"outline vertices {before:,} -> {after:,} ({after/before:.1%}) "
          f"at {args.tolerance:.0f} m")
    print(f"wrote {OUT.relative_to(ROOT)}  {mb:.2f} MB")
    if mb > 3:
        print("  NOTE: over 3 MB; raise --tolerance before publishing")


if __name__ == "__main__":
    main()
