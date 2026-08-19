#!/usr/bin/env python3
"""
Recompute district area, density and piece count from real ring geometry.

The solver derived each district's area by subtraction:

    area_k = A(copy_k clipped)  -  A(copy_(k-1) clipped)

which is only correct when the inner copy nests inside the outer one. Under a
homothety that holds if the lobe is star-shaped about its anchor -- and the
whole reason this project uses the FARTHEST ray crossing is that many states are
not. Where copy_(k-1) escapes copy_k, the subtraction removes area that was
never in the outer district, understating it by up to 9% (Michigan).

Building the ring by difference and measuring it is exact, so that is what runs
here. Nothing else about the solve changes: the breakpoints, and therefore the
populations, are untouched. Only the derived areas and the densities computed
from them move, plus a new per-district piece count.

Cheap to run -- this is the boolean pass only, not the ray-casting that
dominates a full solve.

    python scripts/fix_areas.py            # patch every state in data/derived
    python scripts/fix_areas.py IL MI      # just these
"""

import json
import sys
from pathlib import Path

from export_gis import DERIVED, districts_for

ROOT = Path(__file__).resolve().parent.parent


def patch(usps):
    path = DERIVED / f"{usps.lower()}_districts.json"
    spec = json.loads(path.read_text(encoding="utf-8"))

    areas, pieces = [], []
    for _, geom in districts_for(spec):
        areas.append(round(geom.area / 1e6, 1))
        pieces.append(len(geom.geoms) if geom.geom_type == "MultiPolygon" else 1)

    if len(areas) != spec["seats"]:
        raise SystemExit(f"{usps}: rebuilt {len(areas)} districts, expected {spec['seats']}")

    before = sum(spec["district_area_km2"])
    spec["district_area_km2"] = areas
    spec["district_density"] = [
        round(p / a, 1) if a > 0 else 0.0
        for p, a in zip(spec["district_pop"], areas)
    ]
    spec["district_pieces"] = pieces
    spec["qa"]["max_district_pieces"] = max(pieces)
    spec["qa"]["contiguous_districts"] = int(sum(1 for p in pieces if p == 1))

    path.write_text(json.dumps(spec), encoding="utf-8")
    shift = (sum(areas) - before) / before if before else 0.0
    return {"usps": usps, "seats": spec["seats"], "area_shift": shift,
            "max_pieces": max(pieces), "contiguous": spec["qa"]["contiguous_districts"]}


def main():
    targets = [s.upper() for s in sys.argv[1:]] or sorted(
        f.name[:2].upper() for f in DERIVED.glob("*_districts.json"))

    rows = [patch(u) for u in targets]
    rows.sort(key=lambda r: r["max_pieces"], reverse=True)

    total = sum(r["seats"] for r in rows)
    contig = sum(r["contiguous"] for r in rows)
    print(f"patched {len(rows)} states, {total} districts")
    print(f"single-piece (genuinely contiguous) districts: {contig}/{total} "
          f"({contig/total:.1%})")
    print(f"\nworst area understatement corrected: "
          f"{max(r['area_shift'] for r in rows):+.2%}")
    print("\nmost fragmented states:")
    print(f"{'st':>3} {'seats':>6} {'max pieces':>11} {'contiguous':>11} {'area shift':>11}")
    for r in rows[:12]:
        print(f"{r['usps']:>3} {r['seats']:>6} {r['max_pieces']:>11} "
              f"{r['contiguous']:>11} {r['area_shift']:>+10.2%}")


if __name__ == "__main__":
    main()
