#!/usr/bin/env python3
"""
Build the Illinois payload: five maps and 85 districts' worth of vote shares.

The other four bundles answer "what shape are the districts". This one answers
"where does a real electorate land inside them", which needs three things
joined: the district geometry under each model, the enacted 118th-Congress map
as a fifth column for scale, and the allocated 2020 presidential vote from
scripts/allocate_votes.py.

Geometry all ends up in EPSG:5070, the CRS Illinois is solved in, so the five
panels share one bbox and can be compared shape for shape. The enacted map
arrives in WGS84 from the Census cartographic file and is projected to match.

This is not a prediction. Nobody ran in these districts. It is a partisan
index: the same ballots, counted inside different lines.
"""

import csv
import json
from datetime import date
from pathlib import Path

import geopandas as gpd
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parent.parent
VOTES = ROOT / "data" / "derived_votes"
OUT = ROOT / "data" / "illinois.json"

USPS, FIPS, CRS = "IL", "17", "EPSG:5070"
SIMPLIFY_M = 300.0   # one panel is ~200 px wide, so ~2.5 km/px; 300 m is invisible

# Where each model's Illinois geometry comes from. The four experiments have
# GeoJSON exports; the enacted map is a Census cartographic file.
SOURCES = {
    "outward":  ("gis", "il_districts.geojson", "district"),
    "inward":   ("gis_inward", "il_inward.geojson", "district"),
    "meridian": ("gis_meridian", "il_meridian.geojson", "district"),
    "parallel": ("gis_parallel", "il_parallel.geojson", "district"),
}
LABELS = {
    "outward": "Outward", "inward": "Inward", "meridian": "Meridian",
    "parallel": "Parallel", "enacted": "Enacted (118th)",
}


def rings_of(geom):
    """Flat ring list, exteriors and holes alike -- read by fill-rule: evenodd."""
    g = mapping(geom)
    coords = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = []
    for poly in coords:
        for ring in poly:
            pts = [[round(x, 1), round(y, 1)] for x, y in ring]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                out.append(pts)
    return out


def load_model(model):
    if model == "enacted":
        zf = ROOT / "data" / "raw" / "cb_2023_us_cd118_500k.zip"
        gdf = gpd.read_file(f"zip://{zf}")
        gdf = gdf[gdf["STATEFP"] == FIPS].copy()
        # CDs are labelled by district number; sort numerically, not as strings.
        gdf["district"] = gdf["CD118FP"].astype(int)
        gdf = gdf.sort_values("district")
    else:
        sub, name, key = SOURCES[model]
        gdf = gpd.read_file(ROOT / "data" / sub / name)
        gdf["district"] = gdf[key].astype(int)
        gdf = gdf.sort_values("district")

    gdf = gdf.to_crs(CRS)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    return gdf


def main():
    alloc = list(csv.DictReader((VOTES / "il_allocation.csv").open(encoding="utf-8")))
    summary = {r["model"]: r for r in
               csv.DictReader((VOTES / "il_summary.csv").open(encoding="utf-8"))}

    by_model = {}
    for r in alloc:
        by_model.setdefault(r["model"], {})[int(r["district"])] = r

    panels, bbox = [], None
    for model in ("outward", "inward", "meridian", "parallel", "enacted"):
        gdf = load_model(model)
        votes = by_model.get(model)
        if votes is None:
            raise SystemExit(f"{model}: no rows in il_allocation.csv")
        if len(gdf) != len(votes):
            raise SystemExit(f"{model}: {len(gdf)} shapes but {len(votes)} vote rows")

        b = gdf.total_bounds
        bbox = list(b) if bbox is None else [
            min(bbox[0], b[0]), min(bbox[1], b[1]),
            max(bbox[2], b[2]), max(bbox[3], b[3])]

        districts = []
        for _, row in gdf.iterrows():
            k = int(row["district"])
            v = votes[k]
            districts.append({
                "k": k,
                "dem": round(float(v["dem_two_party"]), 5),
                "population": int(float(v["population"])),
                "dem_votes": round(float(v["dem"])),
                "rep_votes": round(float(v["rep"])),
                "rings": rings_of(row.geometry),
            })

        s = summary[model]
        panels.append({
            "key": model,
            "label": LABELS[model],
            "seats": int(s["seats"]),
            "dem_seats": int(s["dem_seats"]),
            "spread": round(float(s["spread"]), 4),
            "stdev": round(float(s["stdev"]), 4),
            "split_vtd_pop_pct": round(float(s["split_vtd_pop_pct"]), 2),
            "districts": sorted(districts, key=lambda d: d["k"]),
        })

    bundle = {
        "meta": {
            "generated": date.today().isoformat(),
            "state": "Illinois",
            "usps": USPS,
            "crs": CRS,
            "seats": panels[0]["seats"],
            "simplify_tolerance_m": SIMPLIFY_M,
            # One box for all five panels, so they are drawn at one scale and
            # differences between them are differences in the districting.
            "bbox": [round(float(v), 1) for v in bbox],
            "sources": {
                "votes": "VEST 2020 Illinois precinct boundaries and returns",
                "enacted": "US Census cb_2023_us_cd118_500k",
            },
        },
        "panels": panels,
    }
    OUT.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    kb = OUT.stat().st_size / 1e3
    print(f"wrote {OUT.relative_to(ROOT)}  {kb:.0f} KB")
    for p in panels:
        rings = sum(len(d["rings"]) for d in p["districts"])
        lo = min(d["dem"] for d in p["districts"])
        hi = max(d["dem"] for d in p["districts"])
        print(f"  {p['label']:16} {p['seats']:2} seats  {p['dem_seats']:2}D  "
              f"dem share {lo:.3f}-{hi:.3f}  {rings:3} rings")


if __name__ == "__main__":
    main()
