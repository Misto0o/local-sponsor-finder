"""
Stage 1: build the local dataset the Sponsor Finder will run on, and print the lead funnel.

What it does (and nothing more - no scoring, no UI):
  1. Reads Overture places for an NC+SC bounding box (from S3, or a local parquet for testing).
  2. Keeps a slim set of columns and derives: bucket / exclude_reason (config.py),
     chain_tier (national / regional / local), and contact flags.
  3. Writes data/places.parquet.
  4. Writes reports/category_review.csv (every category -> bucket, so you can sanity check it).
  5. Prints the funnel around Kearns: all places -> usable call-list candidates.

Usage:
    python prepare_data.py
    python prepare_data.py --from-parquet some_test_file.parquet     (testing without S3)
    python prepare_data.py --min-confidence 0.8 --radius-miles 60
"""

import argparse
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

import duckdb

from config import classify

# xmin, ymin, xmax, ymax - covers NC and SC with a little margin
DEFAULT_BBOX = (-84.4, 31.9, -75.3, 36.7)
KEARNS = (35.98153, -79.99122)
FALLBACK_RELEASE = "2026-09-23.1"
S3_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
EARTH_RADIUS_MILES = 3958.8

# Chain heuristic: brand has a wikidata id, or the same normalized name shows up this many times
NATIONAL_MIN_LOCATIONS = 15
REGIONAL_MIN_LOCATIONS = 5


def latest_release():
    try:
        with urllib.request.urlopen("https://stac.overturemaps.org/catalog.json", timeout=15) as r:
            return json.load(r)["latest"]
    except Exception:
        return FALLBACK_RELEASE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-parquet", help="local parquet instead of S3 (testing)")
    ap.add_argument("--release")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                    default=DEFAULT_BBOX)
    ap.add_argument("--center-lat", type=float, default=KEARNS[0])
    ap.add_argument("--center-lon", type=float, default=KEARNS[1])
    ap.add_argument("--radius-miles", type=float, default=60.0)
    ap.add_argument("--min-confidence", type=float, default=0.7)
    ap.add_argument("--datadir", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--reportdir", default=str(Path(__file__).parent / "reports"))
    args = ap.parse_args()

    datadir, reportdir = Path(args.datadir), Path(args.reportdir)
    datadir.mkdir(parents=True, exist_ok=True)
    reportdir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    if args.from_parquet:
        source = f"read_parquet('{args.from_parquet}')"
        release = f"local file {args.from_parquet}"
    else:
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        release = args.release or latest_release()
        source = f"read_parquet('{S3_TEMPLATE.format(release=release)}', hive_partitioning=1)"
    print(f"Overture release: {release}")

    # --- schema-aware column expressions (Overture changes names between releases) -------------
    types = {r[0]: str(r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
    has = lambda c: c in types

    cat = "taxonomy.primary" if has("taxonomy") else ("categories.primary" if has("categories") else "NULL")
    name = "names.primary" if has("names") else "NULL"
    phone = "phones[1]" if has("phones") else "NULL"
    website = "websites[1]" if has("websites") else "NULL"
    email = "emails[1]" if has("emails") else "NULL"
    conf = "confidence" if has("confidence") else "NULL"
    status = "operating_status" if has("operating_status") else "NULL"
    brand_wikidata = "(brand.wikidata IS NOT NULL)" if has("brand") and "wikidata" in types["brand"].lower() else "false"
    brand_name = "brand.names.primary" if has("brand") and "names" in types["brand"].lower() else "NULL"
    if has("addresses"):
        a_street, a_city, a_state, a_zip = ("addresses[1].freeform", "addresses[1].locality",
                                            "addresses[1].region", "addresses[1].postcode")
    else:
        a_street = a_city = a_state = a_zip = "NULL"
    print(f"Category field: {cat} | brand wikidata available: {brand_wikidata != 'false'}")

    xmin, ymin, xmax, ymax = args.bbox
    print(f"Reading bbox lon {xmin}..{xmax}, lat {ymin}..{ymax} (this can take a few minutes from S3)...")
    con.execute(f"""
        CREATE TABLE raw AS
        SELECT id,
               {name} AS name,
               {cat} AS category,
               (bbox.ymin + bbox.ymax) / 2 AS lat,
               (bbox.xmin + bbox.xmax) / 2 AS lon,
               {phone} AS phone,
               {website} AS website,
               {email} AS email,
               {conf} AS confidence,
               {status} AS operating_status,
               {brand_wikidata} AS has_wikidata,
               {brand_name} AS brand_name,
               {a_street} AS street, {a_city} AS city, {a_state} AS state, {a_zip} AS zip
        FROM {source}
        WHERE bbox.xmin BETWEEN {xmin} AND {xmax} AND bbox.ymin BETWEEN {ymin} AND {ymax}
    """)
    n_raw = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    print(f"Places read: {n_raw:,}")

    # --- category classification ---------------------------------------------------------------
    con.execute("CREATE TABLE catmap(category VARCHAR, bucket VARCHAR, exclude_reason VARCHAR)")
    cats = [r[0] for r in con.execute("SELECT DISTINCT category FROM raw").fetchall()]
    con.executemany("INSERT INTO catmap VALUES (?,?,?)", [(c, *classify(c)) for c in cats])

    # --- derived columns -----------------------------------------------------------------------
    con.execute(f"""
        CREATE TABLE places AS
        WITH base AS (
            SELECT r.*,
                   coalesce(m.bucket, 'unknown') AS bucket,
                   CASE WHEN r.category IS NULL THEN 'no_category' ELSE m.exclude_reason END AS exclude_reason,
                   trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(r.name,'')),
                        '\\s*(#|store|location|unit|no\\.?)\\s*\\d+\\s*$', ''),
                        '[^a-z0-9 ]', '', 'g'), '^the ', '')) AS norm_name
            FROM raw r LEFT JOIN catmap m ON r.category IS NOT DISTINCT FROM m.category
        ), counted AS (
            SELECT *,
                   CASE WHEN norm_name = '' THEN 1
                        ELSE count(*) OVER (PARTITION BY norm_name) END AS name_count
            FROM base
        )
        SELECT id, name, norm_name, category, bucket, exclude_reason, lat, lon,
               phone, website, email, confidence, operating_status,
               street, city, state, zip, brand_name, name_count,
               CASE WHEN has_wikidata OR name_count >= {NATIONAL_MIN_LOCATIONS} THEN 'national'
                    WHEN name_count >= {REGIONAL_MIN_LOCATIONS} THEN 'regional'
                    ELSE 'local' END AS chain_tier,
               has_wikidata,
               (operating_status IS NULL OR operating_status = 'open') AS is_open,
               (phone IS NOT NULL AND phone <> '') AS has_phone,
               (website IS NOT NULL AND website <> '') AS has_website,
               (email IS NOT NULL AND email <> '') AS has_email
        FROM counted
    """)
    out = datadir / "places.parquet"
    # Write to the system temp folder first (usually the internal drive), then copy. A flaky USB
    # drive can fail mid-write (Windows error 1006), and this way the finished file is never lost.
    tmp = Path(tempfile.gettempdir()) / "sponsor_places.parquet"
    con.execute(f"COPY places TO '{tmp.as_posix()}' (FORMAT PARQUET)")
    try:
        shutil.copy(tmp, out)
        print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)\n")
    except OSError as e:
        print(f"WARNING: could not copy to {out}: {e}")
        print(f"The finished file is safe at {tmp}. Point the app at it with:")
        print(f'   $env:SPONSOR_DATA = "{tmp}"   (PowerShell) before running streamlit\n')

    # --- category review file ------------------------------------------------------------------
    con.execute(f"""
        COPY (SELECT coalesce(category,'(none)') AS category, bucket, coalesce(exclude_reason,'') AS exclude_reason,
                     count(*) AS n,
                     round(100.0*count(*) FILTER (WHERE has_phone)/count(*),1) AS phone_pct,
                     round(100.0*count(*) FILTER (WHERE has_website)/count(*),1) AS website_pct
              FROM places WHERE is_open GROUP BY ALL ORDER BY n DESC)
        TO '{(reportdir / "category_review.csv").as_posix()}' (HEADER, DELIMITER ',')
    """)

    # --- funnel around the center --------------------------------------------------------------
    con.execute(f"""
        CREATE VIEW near AS
        SELECT *, {EARTH_RADIUS_MILES} * 2 * asin(sqrt(
            pow(sin(radians(lat - {args.center_lat}) / 2), 2)
            + cos(radians({args.center_lat})) * cos(radians(lat))
            * pow(sin(radians(lon - {args.center_lon}) / 2), 2))) AS miles
        FROM places
    """)
    steps = [
        ("All places in the NC+SC extract", "true"),
        (f"Within {args.radius_miles:g} miles of the school", f"miles <= {args.radius_miles}"),
        ("... and not closed", "is_open"),
        (f"... and confidence >= {args.min_confidence}", f"coalesce(confidence,0) >= {args.min_confidence}"),
        ("... and a sponsor-plausible category", "exclude_reason IS NULL"),
        ("... and not a national chain", "chain_tier <> 'national'"),
        ("... and has a phone number", "has_phone"),
        ("... and has phone AND website", "has_phone AND has_website"),
    ]
    funnel, where, prev = [], [], None
    print(f"FUNNEL around ({args.center_lat:.4f}, {args.center_lon:.4f})")
    for label, cond in steps:
        where.append(cond)
        n = con.execute(f"SELECT count(*) FROM near WHERE {' AND '.join(where)}").fetchone()[0]
        keep = f"{100.0 * n / prev:5.1f}% of previous" if prev else ""
        print(f"  {n:>9,}  {label:48} {keep}")
        funnel.append({"step": label, "count": n})
        prev = n
    pool = " AND ".join(where[1:7])  # radius..phone, i.e. the call-list pool

    print("\nCall-list pool by bucket:")
    by_bucket = con.execute(f"SELECT bucket, count(*) n FROM near WHERE {pool} GROUP BY 1 ORDER BY n DESC").fetchall()
    for b, n in by_bucket:
        print(f"  {n:>8,}  {b}")
    print("\nCall-list pool by chain tier:")
    for t, n in con.execute(f"SELECT chain_tier, count(*) FROM near WHERE {pool} GROUP BY 1 ORDER BY 2 DESC").fetchall():
        print(f"  {n:>8,}  {t}")

    # --- things to eyeball ---------------------------------------------------------------------
    print("\nTop 'other' categories (add them to config.py if they should be a bucket):")
    for c, n in con.execute("SELECT category, count(*) n FROM places WHERE bucket='other' AND is_open "
                            "GROUP BY 1 ORDER BY n DESC LIMIT 15").fetchall():
        print(f"  {n:>6,}  {c}")
    print("\nTop 'national' names with NO wikidata (frequency-based; generic names may be misflagged):")
    for nm, n in con.execute("SELECT norm_name, max(name_count) n FROM places WHERE chain_tier='national' "
                             "AND NOT has_wikidata AND exclude_reason IS NULL GROUP BY 1 ORDER BY n DESC LIMIT 15").fetchall():
        print(f"  {n:>6,}  {nm}")
    print("\nRandom sample of the call-list pool (do these look like real, callable local businesses?):")
    for row in con.execute(f"SELECT * FROM (SELECT name, category, city, phone, round(miles,1) AS miles "
                           f"FROM near WHERE {pool} AND chain_tier='local') USING SAMPLE 12 ROWS").fetchall():
        print("  ", row)

    (reportdir / "funnel.json").write_text(json.dumps(
        {"release": release, "center": [args.center_lat, args.center_lon], "radius_miles": args.radius_miles,
         "min_confidence": args.min_confidence, "funnel": funnel,
         "pool_by_bucket": dict(by_bucket)}, indent=2))
    print(f"\nSaved reports to {reportdir}")


if __name__ == "__main__":
    main()