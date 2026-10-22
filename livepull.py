"""
Live pull: fetch businesses around ANY school straight from Overture Maps (public S3 bucket),
for schools outside the bundled demo data. Returns the same columns prepare_data.py produces,
plus a `miles` column, so the rest of the app doesn't care where the data came from.

It can be slow the first time (tens of seconds): it reads only the part of the dataset inside
the search box, but that still comes over the internet.
"""
import json
import math
import os
import urllib.request

import duckdb

FALLBACK_RELEASE = "2026-09-23.1"
S3_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
EARTH_RADIUS_MILES = 3958.8
# A 60-mile area has far fewer repeats of a chain's name than all of NC+SC, so the cutoffs are lower
# than prepare_data.py's (15 / 5). Brands with a Wikidata id count as national either way.
NATIONAL_MIN_LOCATIONS = 10
REGIONAL_MIN_LOCATIONS = 4

_schema_cache = {}


def latest_release():
    try:
        with urllib.request.urlopen("https://stac.overturemaps.org/catalog.json", timeout=15) as r:
            return json.load(r)["latest"]
    except Exception:
        return FALLBACK_RELEASE


def pull(lat, lon, radius_miles=60.0, source=None):
    """`source` is only for tests: a SQL table expression, e.g. read_parquet('local_file.parquet')."""
    source = source or os.environ.get("SPONSOR_LIVE_SOURCE_TEST")
    con = duckdb.connect()
    if source is None:
        if os.name == "posix":  # hosted Linux: the home folder may be read-only, so use /tmp
            con.execute("SET home_directory='/tmp'")
            con.execute("SET extension_directory='/tmp/duckdb_extensions'")
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        release = latest_release()
        source = f"read_parquet('{S3_TEMPLATE.format(release=release)}', hive_partitioning=1)"

    if source not in _schema_cache:
        _schema_cache[source] = {r[0]: str(r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
    types = _schema_cache[source]
    has = lambda c: c in types

    cat = "taxonomy.primary" if has("taxonomy") else ("categories.primary" if has("categories") else "NULL")
    name = "names.primary" if has("names") else "NULL"
    phone = "phones[1]" if has("phones") else "NULL"
    website = "websites[1]" if has("websites") else "NULL"
    email = "emails[1]" if has("emails") else "NULL"
    conf = "confidence" if has("confidence") else "NULL"
    status = "operating_status" if has("operating_status") else "NULL"
    wikidata = "(brand.wikidata IS NOT NULL)" if has("brand") and "wikidata" in types["brand"].lower() else "false"
    brand_name = "brand.names.primary" if has("brand") and "names" in types["brand"].lower() else "NULL"
    if has("addresses"):
        street, city, state, zipc = ("addresses[1].freeform", "addresses[1].locality",
                                     "addresses[1].region", "addresses[1].postcode")
    else:
        street = city = state = zipc = "NULL"

    dlat = radius_miles / 69.0
    dlon = dlat / math.cos(math.radians(lat))
    con.execute(f"""
        CREATE TABLE raw AS
        SELECT id, {name} AS name, {cat} AS category,
               (bbox.ymin + bbox.ymax) / 2 AS lat, (bbox.xmin + bbox.xmax) / 2 AS lon,
               {phone} AS phone, {website} AS website, {email} AS email,
               {conf} AS confidence, {status} AS operating_status,
               {wikidata} AS has_wikidata, {brand_name} AS brand_name,
               {street} AS street, {city} AS city, {state} AS state, {zipc} AS zip
        FROM {source}
        WHERE bbox.xmin BETWEEN {lon - dlon} AND {lon + dlon} AND bbox.ymin BETWEEN {lat - dlat} AND {lat + dlat}
    """)
    df = con.execute(rf"""
        WITH base AS (
            SELECT r.*,
                   trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(r.name,'')),
                        '\s*(#|store|location|unit|no\.?)\s*\d+\s*$', ''),
                        '[^a-z0-9 ]', '', 'g'), '^the ', '')) AS norm_name
            FROM raw r
        ), counted AS (
            SELECT *, CASE WHEN norm_name = '' THEN 1 ELSE count(*) OVER (PARTITION BY norm_name) END AS name_count
            FROM base
        )
        SELECT * FROM (
        SELECT id, name, norm_name, category, lat, lon, phone, website, email, confidence, operating_status,
               street, city, state, zip, brand_name, name_count,
               CASE WHEN has_wikidata OR name_count >= {NATIONAL_MIN_LOCATIONS} THEN 'national'
                    WHEN name_count >= {REGIONAL_MIN_LOCATIONS} THEN 'regional' ELSE 'local' END AS chain_tier,
               has_wikidata,
               (operating_status IS NULL OR operating_status = 'open') AS is_open,
               (phone IS NOT NULL AND phone <> '') AS has_phone,
               (website IS NOT NULL AND website <> '') AS has_website,
               (email IS NOT NULL AND email <> '') AS has_email,
               {EARTH_RADIUS_MILES} * 2 * asin(sqrt(
                   pow(sin(radians(lat - {lat}) / 2), 2)
                   + cos(radians({lat})) * cos(radians(lat)) * pow(sin(radians(lon - {lon}) / 2), 2))) AS miles
        FROM counted
        ) WHERE miles <= {radius_miles}
    """).df()
    return df