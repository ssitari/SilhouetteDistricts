#!/usr/bin/env python3
"""
Pre-fetch the PL 94-171 file for all 50 states.

Network-bound and ~1.5 GB, so it is worth running on its own while other work
continues. Everything is cached in data/raw/ and skipped on later runs, and each
file is written to a .part temp first so an interrupted run cannot leave a
truncated zip that later parses as a short state.
"""

import sys
import traceback

import geopandas as gpd

import fetch_data
import pl94


def main() -> None:
    states = gpd.read_file(fetch_data.fetch_state_boundaries())
    seats = fetch_data.load_seats()
    apportioned = set(seats["state"].str.casefold())

    targets = [
        (r["NAME"], r["STUSPS"])
        for _, r in states.iterrows()
        if r["NAME"].casefold() in apportioned
    ]
    targets.sort()
    print(f"{len(targets)} apportioned states (DC and territories excluded)\n")

    failed = []
    for i, (name, usps) in enumerate(targets, 1):
        print(f"[{i:2d}/{len(targets)}] {name}")
        try:
            pl94.fetch_pl(name, usps)
        except Exception:
            traceback.print_exc()
            failed.append(name)

    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        sys.exit(1)
    print("\nall PL files cached")


if __name__ == "__main__":
    main()
