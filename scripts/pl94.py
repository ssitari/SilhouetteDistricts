#!/usr/bin/env python3
"""
Read 2020 P.L. 94-171 block population and internal points.

Why this source and not the obvious ones:

  - The Census API (api.census.gov/data/2020/dec/pl) now requires a registered
    key, which a public repo should not have to carry to be reproducible.
  - TIGER's tabblock20 layer has the block geometry but no population; the
    POP20 field people expect is not there. Confirmed by inspection.
  - There is no 2020 block gazetteer file. Only tracts and coarser.

The PL 94-171 geographic header solves all three at once. It is keyless, it is
the authoritative redistricting product, and every record carries POP100 and the
Census internal point together, so we never join anything. One ~10 MB zip per
state covers every summary level; we keep SUMLEV 750 (blocks).

We deliberately do not download block *polygons*. The ring breakpoints are found
by sorting blocks along a single radial coordinate, so a point per block is all
the geometry the method can use.

Field positions are 0-based indices into the pipe-delimited header record. They
are checked at load time against the state-level record, whose POP100 must equal
the sum of its blocks -- if the Census ever reorders the layout, that assertion
fires instead of silently producing a wrong map.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PL_BASE = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
           "01-Redistricting_File--PL_94-171")

SUMLEV = 2
LOGRECNO = 7
# County and VTD, so a block can be joined to its voting district by GEOID.
# VTDs are built FROM blocks by the Census redistricting programme, so this join
# is exact -- no areal interpolation, no slivers, no precinct-name matching.
STATEFP = 12
COUNTYFP = 14
VTD = 77
VTDI = 78
GEOCODE = 9
AREALAND = 84
AREAWATR = 85
POP100 = 90
INTPTLAT = 92
INTPTLON = 93

SUMLEV_STATE = "040"
SUMLEV_BLOCK = "750"


_pl_dirs: dict[str, str] = {}


def pl_dirs() -> dict[str, str]:
    """
    Normalized state name -> PL folder name, read from the live directory index.

    Guessing that 'New Hampshire' becomes 'New_Hampshire' happens to be right,
    but the index is authoritative and costs one request.
    """
    if not _pl_dirs:
        import re
        r = requests.get(f"{PL_BASE}/", timeout=90)
        r.raise_for_status()
        for href in re.findall(r'href="([A-Za-z_]+)/"', r.text):
            _pl_dirs[href.replace("_", " ").casefold()] = href
    return _pl_dirs


def fetch_pl(state_name: str, usps: str, refresh: bool = False) -> Path:
    """Download <usps>2020.pl.zip for a state given its plain name, e.g. 'New Hampshire'."""
    dest = RAW / f"{usps.lower()}2020.pl.zip"
    if dest.exists() and not refresh:
        return dest
    folder = pl_dirs().get(state_name.replace("_", " ").casefold())
    if folder is None:
        raise KeyError(f"{state_name}: no PL 94-171 folder in the Census index")
    url = f"{PL_BASE}/{folder}/{usps.lower()}2020.pl.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetch   {dest.name} ...", end="", flush=True)
    with requests.get(url, stream=True, timeout=900) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
        tmp.replace(dest)
    print(f" {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def load_blocks(path: Path, with_vap: bool = False) -> pd.DataFrame:
    """
    Return one row per 2020 census block: geoid, pop, lat, lon, land/water area,
    plus the block's VTD (voting district) id.

    with_vap also reads segment 2 for the 18-and-over population. VAP is the
    better weight when splitting precinct votes among blocks -- weighting by
    total population over-credits places with more children, which is
    systematically the suburbs.

    Reads the geoheader line by line rather than through pandas: the file is
    ~40 MB of 97-column records of which we want six columns and one summary
    level, and streaming it costs less than parsing the whole thing.
    """
    with zipfile.ZipFile(path) as zf:
        geo_name = next(n for n in zf.namelist() if "geo2020.pl" in n.lower())
        state_pop = None
        rows = []
        with zf.open(geo_name) as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1"):
                f = line.rstrip("\n").split("|")
                level = f[SUMLEV]
                if level == SUMLEV_STATE:
                    state_pop = int(f[POP100])
                elif level == SUMLEV_BLOCK:
                    rows.append((
                        f[GEOCODE],
                        int(f[POP100]),
                        float(f[INTPTLAT]),
                        float(f[INTPTLON]),
                        int(f[AREALAND]),
                        int(f[AREAWATR]),
                        f[STATEFP] + f[COUNTYFP] + f[VTD],
                        f[VTDI],
                        int(f[LOGRECNO]),
                    ))

    df = pd.DataFrame(rows, columns=["geoid", "pop", "lat", "lon", "aland", "awater",
                                     "vtd", "vtdi", "logrecno"])

    if with_vap:
        # Segment 2 holds P3 (race, 18+); field 5 is P0030001, the voting-age
        # total. Keyed by LOGRECNO, the same key the geoheader carries.
        vap = {}
        with zipfile.ZipFile(path) as zf:
            seg2 = next(n for n in zf.namelist() if n.lower().endswith("000022020.pl"))
            with zf.open(seg2) as fh:
                for line in io.TextIOWrapper(fh, encoding="latin-1"):
                    g = line.rstrip().split("|")
                    vap[int(g[4])] = int(g[5])
        df["vap"] = df["logrecno"].map(vap)
        if df["vap"].isna().any():
            raise ValueError(f"{path.name}: {int(df['vap'].isna().sum())} blocks without VAP")
        if (df["vap"] > df["pop"]).any():
            raise ValueError(f"{path.name}: VAP exceeds total population somewhere")

    if state_pop is None:
        raise ValueError(f"{path.name}: no SUMLEV {SUMLEV_STATE} record found")
    if df.empty:
        raise ValueError(f"{path.name}: no SUMLEV {SUMLEV_BLOCK} records found")
    if df["pop"].sum() != state_pop:
        raise ValueError(
            f"{path.name}: blocks sum to {df['pop'].sum():,} but the state record "
            f"says {state_pop:,}. The PL layout has probably changed."
        )
    if not df["lat"].between(-90, 90).all() or not df["lon"].between(-180, 180).all():
        raise ValueError(f"{path.name}: internal points out of range; check field indices")

    df.attrs["state_pop"] = state_pop
    return df


if __name__ == "__main__":
    df = load_blocks(RAW / "id2020.pl.zip")
    occupied = df[df["pop"] > 0]
    print(f"blocks:          {len(df):,}")
    print(f"  with people:   {len(occupied):,} ({len(occupied)/len(df):.1%})")
    print(f"population:      {df['pop'].sum():,}  (state record agrees)")
    print(f"largest block:   {df['pop'].max():,} people")
    print(f"median occupied: {occupied['pop'].median():.0f} people")
    print(df.head().to_string(index=False))
