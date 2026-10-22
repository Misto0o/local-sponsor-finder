"""
Step 0: validate Overture Maps places data around a school.

Measures, within a radius of the school:
  - total places (and how many are marked closed / low confidence)
  - phone, website, email coverage
  - category breakdown, with contact coverage per category
  - brand/chain share and data-source mix

It does NOT score, rank, or build a UI. Read-only: it only reads Overture data
and writes a small report next to this file.

Usage (from the sponsor-finder folder):
    pip install -r requirements.txt
    python validate_overture.py

Useful flags:
    --lat 35.9 --lon -80.0     skip geocoding and use these coordinates
    --radius-miles 60
    --release 2026-09-23.1     pin a specific Overture release
    --parquet places.parquet   read a local file instead of S3 (offline / testing)
    --min-confidence 0.5       report a second "higher confidence" view
"""

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb

SCHOOL_NAME = "Kearns Academy"
SCHOOL_ADDRESS = "1710 McGuinn Drive, High Point, NC 27265"
FALLBACK_RELEASE = "2026-09-23.1"  # seen in a third-party listing; verify with --release
S3_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
MILES_PER_DEGREE_LAT = 69.0
EARTH_RADIUS_MILES = 3958.8


def geocode_census(address: str):
    """Free US Census geocoder. Returns (lat, lon) or raises."""
    params = urllib.parse.urlencode(
        {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    )
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.load(resp)
    matches = data["result"]["addressMatches"]
    if not matches:
        raise RuntimeError("Census geocoder returned no match for that address")
    coords = matches[0]["coordinates"]
    return coords["y"], coords["x"], matches[0].get("matchedAddress", "")


def latest_release():
    """Try Overture's STAC catalog for the newest release; fall back to a pinned one."""
    try:
        with urllib.request.urlopen("https://stac.overturemaps.org/catalog.json", timeout=15) as r:
            return json.load(r)["latest"]
    except Exception:
        return FALLBACK_RELEASE


def pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--radius-miles", type=float, default=60.0)
    ap.add_argument("--release")
    ap.add_argument("--parquet", help="local parquet path instead of S3")
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--top", type=int, default=30, help="top N categories to print")
    ap.add_argument("--outdir", default=str(Path(__file__).parent / "reports"))
    args = ap.parse_args()

    # 1. Where is the school?
    if args.lat is not None and args.lon is not None:
        lat, lon, matched = args.lat, args.lon, "(manual coordinates)"
    else:
        try:
            lat, lon, matched = geocode_census(SCHOOL_ADDRESS)
        except Exception as e:
            sys.exit(f"Geocoding failed ({e}). Re-run with --lat and --lon.")
    print(f"School: {SCHOOL_NAME}\nMatched address: {matched}\nCoordinates: {lat:.5f}, {lon:.5f}")
    print("Sanity check these coordinates on a map before trusting the numbers.\n")

    # 2. Connect and point at the data
    con = duckdb.connect()
    if args.parquet:
        source = f"read_parquet('{args.parquet}')"
        release = f"local file {args.parquet}"
    else:
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        release = args.release or latest_release()
        source = f"read_parquet('{S3_TEMPLATE.format(release=release)}', hive_partitioning=1)"
    print(f"Overture release: {release}\n")

    # 3. Inspect the schema so we don't assume column names (Overture renames things between releases)
    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
    print(f"Columns found: {sorted(cols)}\n")

    def has(c):
        return c in cols

    if has("taxonomy"):
        cat_expr, cat_note = "taxonomy.primary", "taxonomy.primary"
    elif has("categories"):
        cat_expr, cat_note = "categories.primary", "categories.primary"
    else:
        cat_expr, cat_note = "NULL", "none found"
    phone_n = "coalesce(len(phones),0)" if has("phones") else "0"
    web_n = "coalesce(len(websites),0)" if has("websites") else "0"
    email_n = "coalesce(len(emails),0)" if has("emails") else "0"
    conf = "confidence" if has("confidence") else "NULL"
    closed = "(operating_status IS NOT NULL AND operating_status <> 'open')" if has("operating_status") else "false"
    brand = "(brand IS NOT NULL)" if has("brand") else "false"
    name = "names.primary" if has("names") else "NULL"

    # 4. Bounding box prefilter (lets DuckDB skip most of the file), then exact distance
    dlat = args.radius_miles / MILES_PER_DEGREE_LAT
    dlon = dlat / math.cos(math.radians(lat))
    con.execute(
        f"""
        CREATE TABLE nearby AS
        SELECT
            id,
            {name} AS name,
            {cat_expr} AS category,
            {phone_n} AS n_phone,
            {web_n} AS n_web,
            {email_n} AS n_email,
            {conf} AS confidence,
            {closed} AS is_closed,
            {brand} AS is_brand,
            {EARTH_RADIUS_MILES} * 2 * asin(sqrt(
                pow(sin(radians(((bbox.ymin + bbox.ymax)/2) - {lat}) / 2), 2)
                + cos(radians({lat})) * cos(radians((bbox.ymin + bbox.ymax)/2))
                * pow(sin(radians(((bbox.xmin + bbox.xmax)/2) - {lon}) / 2), 2)
            )) AS miles
        FROM {source}
        WHERE bbox.xmin BETWEEN {lon - dlon} AND {lon + dlon}
          AND bbox.ymin BETWEEN {lat - dlat} AND {lat + dlat}
        """
    )
    con.execute(f"DELETE FROM nearby WHERE miles > {args.radius_miles}")

    def summary(where="true"):
        r = con.execute(
            f"""
            SELECT count(*),
                   count(*) FILTER (WHERE n_phone > 0),
                   count(*) FILTER (WHERE n_web > 0),
                   count(*) FILTER (WHERE n_email > 0),
                   count(*) FILTER (WHERE n_phone > 0 AND n_web > 0),
                   count(*) FILTER (WHERE n_phone > 0 OR n_web > 0),
                   count(*) FILTER (WHERE is_brand)
            FROM nearby WHERE {where}
            """
        ).fetchone()
        total = r[0]
        return {
            "total": total,
            "phone": r[1], "phone_pct": pct(r[1], total),
            "website": r[2], "website_pct": pct(r[2], total),
            "email": r[3], "email_pct": pct(r[3], total),
            "phone_and_website": r[4], "phone_and_website_pct": pct(r[4], total),
            "phone_or_website": r[5], "phone_or_website_pct": pct(r[5], total),
            "brand_tagged": r[6], "brand_tagged_pct": pct(r[6], total),
        }

    report = {
        "school": SCHOOL_NAME,
        "matched_address": matched,
        "lat": lat, "lon": lon,
        "radius_miles": args.radius_miles,
        "release": release,
        "category_field_used": cat_note,
    }
    report["all_places"] = summary()
    report["not_closed"] = summary("NOT is_closed")
    report["closed_or_not_open"] = con.execute("SELECT count(*) FROM nearby WHERE is_closed").fetchone()[0]
    if has("confidence"):
        report[f"not_closed_conf_ge_{args.min_confidence}"] = summary(
            f"NOT is_closed AND confidence >= {args.min_confidence}"
        )
        report["confidence_buckets"] = {
            f"{lo}-{hi}": con.execute(
                f"SELECT count(*) FROM nearby WHERE confidence >= {lo} AND confidence < {hi}"
            ).fetchone()[0]
            for lo, hi in [(0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
        }
    report["null_category"] = con.execute("SELECT count(*) FROM nearby WHERE category IS NULL").fetchone()[0]

    # 5. Category breakdown (open places only), with contact coverage per category
    cat_rows = con.execute(
        f"""
        SELECT coalesce(category, '(none)') AS category,
               count(*) AS n,
               round(100.0 * count(*) FILTER (WHERE n_phone > 0) / count(*), 1) AS phone_pct,
               round(100.0 * count(*) FILTER (WHERE n_web > 0) / count(*), 1) AS web_pct,
               round(100.0 * count(*) FILTER (WHERE is_brand) / count(*), 1) AS brand_pct
        FROM nearby WHERE NOT is_closed
        GROUP BY 1 ORDER BY n DESC
        """
    ).fetchall()
    report["distinct_categories"] = len(cat_rows)
    report["top_categories"] = [
        {"category": r[0], "count": r[1], "phone_pct": r[2], "website_pct": r[3], "brand_pct": r[4]}
        for r in cat_rows[: args.top]
    ]

    # 6. Source mix (who provided the data) if the column exists
    if has("sources"):
        try:
            src = con.execute(
                f"""
                SELECT s.dataset AS dataset, count(*) AS n
                FROM (SELECT unnest(sources) AS s FROM {source}
                      WHERE bbox.xmin BETWEEN {lon - dlon} AND {lon + dlon}
                        AND bbox.ymin BETWEEN {lat - dlat} AND {lat + dlat})
                GROUP BY 1 ORDER BY n DESC
                """
            ).fetchall()
            report["sources_in_bbox"] = {r[0]: r[1] for r in src}
        except Exception as e:
            report["sources_in_bbox"] = f"could not compute: {e}"

    # 7. Print + save
    def show(label, s):
        print(f"{label}: {s['total']:,} places")
        print(f"  phone {s['phone']:,} ({s['phone_pct']}%) | website {s['website']:,} ({s['website_pct']}%) "
              f"| email {s['email']:,} ({s['email_pct']}%)")
        print(f"  phone+website {s['phone_and_website_pct']}% | phone OR website {s['phone_or_website_pct']}% "
              f"| brand-tagged {s['brand_tagged_pct']}%\n")

    show(f"All places within {args.radius_miles:g} miles", report["all_places"])
    show("Excluding closed / not-open", report["not_closed"])
    key = f"not_closed_conf_ge_{args.min_confidence}"
    if key in report:
        show(f"Open and confidence >= {args.min_confidence}", report[key])
    print(f"Marked closed / not open: {report['closed_or_not_open']:,}")
    print(f"Places with no category: {report['null_category']:,}")
    print(f"Distinct categories: {report['distinct_categories']}\n")
    print(f"Top {args.top} categories (open places):")
    print(f"{'category':45} {'count':>8} {'phone%':>7} {'web%':>6} {'brand%':>7}")
    for r in report["top_categories"]:
        print(f"{r['category'][:45]:45} {r['count']:>8,} {r['phone_pct']:>7} {r['website_pct']:>6} {r['brand_pct']:>7}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    con.execute(
        f"COPY (SELECT coalesce(category,'(none)') AS category, count(*) AS n, "
        f"count(*) FILTER (WHERE n_phone>0) AS with_phone, count(*) FILTER (WHERE n_web>0) AS with_website "
        f"FROM nearby WHERE NOT is_closed GROUP BY 1 ORDER BY n DESC) "
        f"TO '{(outdir / 'categories.csv').as_posix()}' (HEADER, DELIMITER ',')"
    )
    print(f"\nSaved: {outdir / 'validation_report.json'} and {outdir / 'categories.csv'}")


if __name__ == "__main__":
    main()