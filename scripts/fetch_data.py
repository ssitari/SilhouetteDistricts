#!/usr/bin/env python3
"""
Download and cache the source data for the silhouette-districts map.

Three sources, all US Census, all public domain:

  1. cb_2020_us_state_500k  - state boundaries, cartographic (shoreline-clipped).
     TIGER's own state files carry water out to the 3-mile limit and slice up the
     Great Lakes, which would corrupt both the silhouette we scale and the anchor
     we scale it about. The cartographic file is already clipped to shoreline.

  2. tl_2020_XX_tabblock20  - 2020 census blocks, per state. This layer is the
     reason we can skip the Census API entirely: TIGER2020PL blocks carry POP20
     (the PL 94-171 count) and INTPTLAT/INTPTLON (the Census internal point)
     as attributes, so geometry and population arrive together, unkeyed.

  3. apportionment-2020-table01.xlsx - seats per state from the 2020 census.
     Never hardcode these; the whole map is a function of them.

Everything lands in data/raw/ and is reused on later runs. Pass --refresh to
re-download. Blocks are ~10-90 MB per state, so fetch only what you need:

    python scripts/fetch_data.py --states 16 17 26
"""

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

STATE_BOUNDARIES = "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_state_500k.zip"
APPORTIONMENT = (
    "https://www2.census.gov/programs-surveys/decennial/2020/data/"
    "apportionment/apportionment-2020-table01.xlsx"
)
TIGER_PL = "https://www2.census.gov/geo/tiger/TIGER2020PL/STATE"

# Populated from the live TIGER directory listing so the folder names
# (16_IDAHO, 11_DISTRICT_OF_COLUMBIA, ...) are never guessed.
_state_dirs: dict[str, str] = {}


def state_dirs() -> dict[str, str]:
    """FIPS -> TIGER2020PL state folder name, read from the directory index."""
    if not _state_dirs:
        r = requests.get(f"{TIGER_PL}/", timeout=60)
        r.raise_for_status()
        for href in re.findall(r'href="(\d\d_[A-Z_]+)/"', r.text):
            _state_dirs[href[:2]] = href
        if not _state_dirs:
            sys.exit("Could not parse the TIGER2020PL state index; layout may have changed.")
    return _state_dirs


def download(url: str, dest: Path, refresh: bool = False) -> Path:
    """Fetch url to dest unless already cached. Streams; these files are large."""
    if dest.exists() and not refresh:
        print(f"  cached  {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetch   {dest.name} ...", end="", flush=True)
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        tmp.replace(dest)
    print(f" {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def fetch_state_boundaries(refresh: bool = False) -> Path:
    return download(STATE_BOUNDARIES, RAW / "cb_2020_us_state_500k.zip", refresh)


def fetch_blocks(fips: str, refresh: bool = False) -> Path:
    folder = state_dirs()[fips]
    url = f"{TIGER_PL}/{folder}/{fips}/tl_2020_{fips}_tabblock20.zip"
    return download(url, RAW / f"tl_2020_{fips}_tabblock20.zip", refresh)


def fetch_apportionment(refresh: bool = False) -> Path:
    return download(APPORTIONMENT, RAW / "apportionment-2020-table01.xlsx", refresh)


def load_seats(refresh: bool = False) -> pd.DataFrame:
    """
    Seats per state from the official apportionment table.

    The sheet has decorative title rows above the header and footnotes below, so
    locate the header row by content rather than by a fixed skiprows count.
    """
    path = fetch_apportionment(refresh)
    raw = pd.read_excel(path, header=None, dtype=object)

    header_row = None
    for i in range(min(12, len(raw))):
        cells = [str(c).strip().upper() for c in raw.iloc[i].tolist()]
        if any(c.startswith("STATE") for c in cells) and any("REPRESENTATIVE" in c for c in cells):
            header_row = i
            break
    if header_row is None:
        sys.exit(f"Could not find the header row in {path.name}; inspect it by hand.")

    df = pd.read_excel(path, header=header_row)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    state_col = next(c for c in df.columns if c.upper().startswith("STATE"))
    seat_col = next(c for c in df.columns if "REPRESENTATIVE" in c.upper())
    pop_col = next((c for c in df.columns if "APPORTIONMENT POPULATION" in c.upper()), None)

    keep = [state_col, seat_col] + ([pop_col] if pop_col else [])
    df = df[keep].rename(columns={state_col: "state", seat_col: "seats"})
    if pop_col:
        df = df.rename(columns={pop_col: "apportionment_pop"})

    df["state"] = df["state"].astype(str).str.strip()
    df["seats"] = pd.to_numeric(df["seats"], errors="coerce")
    df = df[df["seats"].notna() & (df["state"].str.len() > 1)]
    # The sheet ends with a "TOTAL APPORTIONMENT POPULATION" row carrying 435.
    df = df[~df["state"].str.upper().str.startswith("TOTAL")]
    df["seats"] = df["seats"].astype(int)
    df = df.reset_index(drop=True)

    # The map is a function of these numbers, so fail loudly if the parse drifts.
    if len(df) != 50 or df["seats"].sum() != 435:
        sys.exit(
            f"Apportionment parse looks wrong: {len(df)} states, "
            f"{df['seats'].sum()} seats (expected 50 and 435)."
        )
    return df


def inspect(fips: str = "16") -> None:
    """Print the schemas we depend on, so a layout change fails loudly and early."""
    print("\n--- state boundaries ---")
    states = gpd.read_file(fetch_state_boundaries())
    print("crs:", states.crs)
    print("cols:", list(states.columns))
    print(f"rows: {len(states)}")

    print(f"\n--- blocks, FIPS {fips} ---")
    blocks = gpd.read_file(fetch_blocks(fips), columns=None, max_features=5)
    print("crs:", blocks.crs)
    print("cols:", list(blocks.columns))

    with zipfile.ZipFile(fetch_blocks(fips)) as zf:
        dbf = next(n for n in zf.namelist() if n.endswith(".dbf"))
        print(f"dbf: {dbf} ({zf.getinfo(dbf).file_size / 1e6:.1f} MB uncompressed)")

    print("\n--- apportionment ---")
    seats = load_seats()
    print(seats.head(8).to_string(index=False))
    print(f"rows: {len(seats)}   total seats: {seats['seats'].sum()}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", nargs="*", default=[], help="two-digit state FIPS codes")
    ap.add_argument("--refresh", action="store_true", help="re-download cached files")
    ap.add_argument("--inspect", action="store_true", help="print source schemas and exit")
    args = ap.parse_args()

    if args.inspect:
        inspect(args.states[0] if args.states else "16")
        return

    print("state boundaries:")
    fetch_state_boundaries(args.refresh)
    print("apportionment:")
    fetch_apportionment(args.refresh)
    if args.states:
        print("blocks:")
        for fips in args.states:
            fetch_blocks(fips, args.refresh)


if __name__ == "__main__":
    main()
