"""
Make a small data file for the online demo (data/places_demo.parquet).

The full NC+SC file is ~175 MB, which is too big for GitHub (100 MB limit per file).
The demo only needs places within a radius of the schools you plan to show, so this
keeps just those and compresses them.

Usage (from the sponsor-finder folder, after prepare_data.py has run):
    python make_demo_data.py
    python make_demo_data.py --center 35.98153 -79.99122 --center 34.1954 -79.7626
    python make_demo_data.py --src E:\\sponsor-finder\\data\\places.parquet

Default centers: Kearns Academy (High Point, NC) and Florence, SC (downtown, approximate).
"""
import argparse
import json
from pathlib import Path

import duckdb

EARTH_RADIUS_MILES = 3958.8
DEFAULT_CENTERS = [(35.98153, -79.99122), (34.1954, -79.7626)]


def near(clat, clon, miles):
    return (f"{EARTH_RADIUS_MILES} * 2 * asin(sqrt(pow(sin(radians(lat - {clat}) / 2), 2) + "
            f"cos(radians({clat})) * cos(radians(lat)) * pow(sin(radians(lon - {clon}) / 2), 2))) <= {miles}")


def main():
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(here / "data" / "places.parquet"))
    ap.add_argument("--out", default=str(here / "data" / "places_demo.parquet"))
    ap.add_argument("--center", nargs=2, type=float, action="append", metavar=("LAT", "LON"))
    ap.add_argument("--radius-miles", type=float, default=72.0,
                    help="60-mile searches within (this - 60) miles of a center load instantly from this file")
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    if not src.exists():
        raise SystemExit(f"{src} not found. Run prepare_data.py first (or pass --src).")
    centers = [tuple(c) for c in args.center] if args.center else DEFAULT_CENTERS
    where = " OR ".join(near(la, lo, args.radius_miles) for la, lo in centers)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    total = con.execute(f"SELECT count(*) FROM read_parquet('{src.as_posix()}')").fetchone()[0]
    con.execute(f"""
        COPY (SELECT * FROM read_parquet('{src.as_posix()}') WHERE {where} ORDER BY lat, lon)
        TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
    """)
    kept = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    mb = out.stat().st_size / 1e6
    side = out.with_name(out.stem + ".coverage.json")
    side.write_text(json.dumps({"circles": [{"lat": la, "lon": lo, "radius_miles": args.radius_miles} for la, lo in centers]}, indent=2))
    print(f"Wrote {side.name} (tells the app which schools this file fully covers)")
    print(f"Kept {kept:,} of {total:,} places around {len(centers)} center(s) -> {out} ({mb:.1f} MB)")
    if mb > 90:
        print("WARNING: over 90 MB. GitHub rejects files over 100 MB. Use fewer centers or a smaller --radius-miles.")
    elif mb > 50:
        print("Note: GitHub warns above 50 MB but accepts up to 100 MB.")
    else:
        print("Size is fine for GitHub.")


if __name__ == "__main__":
    main()