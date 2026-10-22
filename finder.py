"""
Sponsor Finder engine. No UI code in here, so it can sit behind Streamlit now
and behind an API / React front end later.
"""
import json
import math
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

import livepull

from config import (BUCKET_FIT, BUCKET_LABELS, BUCKET_NOTES, BUSINESS_WORDS_PATTERN, INDIVIDUAL_CATEGORIES,
                    INDIVIDUAL_NAME_PATTERN, classify)

def _default_data_path():
    """SPONSOR_DATA wins; then the full local file; then the small demo file that ships with the repo."""
    env = os.environ.get("SPONSOR_DATA")
    if env:
        return Path(env)
    d = Path(__file__).parent / "data"
    for name in ("places.parquet", "places_demo.parquet"):
        if (d / name).exists():
            return d / name
    return d / "places.parquet"


DATA_PATH = _default_data_path()
KEARNS = (35.98153, -79.99122)
KEARNS_ADDRESS = "1710 McGuinn Drive, High Point, NC 27265"
EARTH_RADIUS_MILES = 3958.8
CHAIN_POINTS = {"local": 15, "regional": 6, "national": 0}
CHAIN_OPTIONS = {
    "Local only": ["local"],
    "Local + regional chains": ["local", "regional"],
    "Include national chains": ["local", "regional", "national"],
}


# ---------- location ----------
def geocode(address):
    """Free US Census geocoder -> (lat, lon, matched_address). Raises on failure."""
    params = urllib.parse.urlencode({"address": address, "benchmark": "Public_AR_Current", "format": "json"})
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        matches = json.load(resp)["result"]["addressMatches"]
    if not matches:
        raise RuntimeError("No match for that address")
    c = matches[0]["coordinates"]
    return c["y"], c["x"], matches[0].get("matchedAddress", address)


def _miles_between(a_lat, a_lon, b_lat, b_lon):
    p = math.radians
    h = math.sin(p(b_lat - a_lat) / 2) ** 2 + math.cos(p(a_lat)) * math.cos(p(b_lat)) * math.sin(p(b_lon - a_lon) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def _local_covers(path, lat, lon, radius_miles):
    """Does the local file contain the whole search circle? If unsure, trust it (the old behavior)."""
    try:
        side = path.with_name(path.stem + ".coverage.json")
        if side.exists():  # the small demo file lists the circles it was cut from
            circles = json.loads(side.read_text())["circles"]
            return any(_miles_between(lat, lon, c["lat"], c["lon"]) + radius_miles <= c["radius_miles"] for c in circles)
        mn_la, mx_la, mn_lo, mx_lo = duckdb.connect().execute(
            f"SELECT min(lat), max(lat), min(lon), max(lon) FROM read_parquet('{path.as_posix()}')").fetchone()
        dlat = radius_miles / 69.0
        dlon = dlat / math.cos(math.radians(lat))
        return lat - dlat >= mn_la and lat + dlat <= mx_la and lon - dlon >= mn_lo and lon + dlon <= mx_lo
    except Exception:
        return True


def load_nearby(lat, lon, radius_miles, data_path=None):
    """All places (including excluded ones) within the radius, with a `miles` column.
    Uses the local data file when it covers this school; otherwise pulls live from Overture Maps."""
    path = Path(data_path or DATA_PATH)
    if path.exists() and _local_covers(path, lat, lon, radius_miles):
        dlat = radius_miles / 69.0
        dlon = dlat / math.cos(math.radians(lat))
        q = f"""
            SELECT * FROM (
                SELECT *, {EARTH_RADIUS_MILES} * 2 * asin(sqrt(
                    pow(sin(radians(lat - {lat}) / 2), 2)
                    + cos(radians({lat})) * cos(radians(lat)) * pow(sin(radians(lon - {lon}) / 2), 2))) AS miles
                FROM read_parquet('{path.as_posix()}')
                WHERE lat BETWEEN {lat - dlat} AND {lat + dlat} AND lon BETWEEN {lon - dlon} AND {lon + dlon}
            ) WHERE miles <= {radius_miles}
        """
        df = duckdb.connect().execute(q).df()
    else:
        try:
            df = livepull.pull(lat, lon, radius_miles)
        except Exception as e:
            raise FileNotFoundError(
                f"Couldn't pull live data from Overture Maps for this address ({e}). "
                "Try again in a minute, or use the Kearns Academy demo.")
    # Re-apply config.py rules at load time, so editing config.py takes effect without re-running prepare_data.py
    cmap = {c: classify(c) for c in df.category.dropna().unique()}
    cmap[None] = classify(None)
    pairs = df.category.map(lambda c: cmap[c if isinstance(c, str) else None])
    df["bucket"] = pairs.map(lambda p: p[0])
    df["exclude_reason"] = pairs.map(lambda p: p[1])
    df["individual"] = looks_individual(df)
    return df


def config_version():
    """Changes whenever config.py is saved; used as a cache key so the app reloads after edits."""
    return (Path(__file__).parent / "config.py").stat().st_mtime


def looks_individual(df):
    name = df.name.fillna("")
    credential = name.str.contains(INDIVIDUAL_NAME_PATTERN, case=False, regex=True)
    solo_cat = df.category.isin(INDIVIDUAL_CATEGORIES) & ~name.str.contains(BUSINESS_WORDS_PATTERN, case=False, regex=True)
    return credential | solo_cat


# ---------- warm intros (businesses the school already knows) ----------
def norm_name(n):
    s = str(n or "").lower()
    s = re.sub(r"\s*(#|store|location|unit|no\.?)\s*\d+\s*$", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"^the ", "", s).strip()


def match_warm(df, warm):
    """warm: DataFrame with a `name` column. Returns (boolean mask over df, list of unmatched warm rows)."""
    mask = pd.Series(False, index=df.index)
    unmatched = []
    for _, row in warm.dropna(subset=["name"]).iterrows():
        w = norm_name(row["name"])
        if not w:
            continue
        hit = df.norm_name.str.contains(rf"(?:^|\s){re.escape(w)}(?:\s|$)", regex=True, na=False)  # whole-word match
        if hit.any():
            mask |= hit
        else:
            unmatched.append(row)
    return mask, unmatched


# ---------- filtering, scoring ----------
def filter_places(df, *, min_conf=0.7, buckets=None, chain_tiers=("local", "regional"),
                  need_phone=True, need_website=False, text="", hide_individuals=True):
    m = df.is_open & df.exclude_reason.isna() & (df.confidence.fillna(0) >= min_conf)
    m &= df.chain_tier.isin(list(chain_tiers))
    if buckets is not None:
        m &= df.bucket.isin(list(buckets))
    if hide_individuals:
        m &= ~df.individual
    if need_phone:
        m &= df.has_phone
    if need_website:
        m &= df.has_website
    if text:
        m &= df.name.fillna("").str.contains(re.escape(text), case=False)
    return df[m].copy()


def funnel(df, **filters):
    """Counts at each step, for the on-screen funnel."""
    f = dict(filters)
    steps = [("In radius", len(df))]
    open_conf = df[df.is_open & (df.confidence.fillna(0) >= f.get("min_conf", 0.7))]
    steps.append(("Open & confident", len(open_conf)))
    plausible = open_conf[open_conf.exclude_reason.isna()]
    steps.append(("Sponsor-plausible", len(plausible)))
    steps.append(("Call-list pool", len(filter_places(df, **f))))
    return steps


def fmt_phone(p):
    d = re.sub(r"\D", "", str(p or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (str(p) if p else "")


def _why(r):
    parts = []
    if r.get("warm"):
        parts.append("the school already knows them")
    parts.append({"local": "locally owned", "regional": "small regional chain", "national": "big national brand"}.get(r.chain_tier, ""))
    note = BUCKET_NOTES.get(r.bucket)
    parts.append(f"{BUCKET_LABELS.get(r.bucket, r.bucket)}" + (f" ({note})" if note else ""))
    contact = [x for x, ok in (("phone", r.has_phone), ("website", r.has_website), ("email", r.has_email)) if ok]
    parts.append("has " + ", ".join(contact) if contact else "no contact info")
    if pd.notna(r.get("miles")):
        parts.append(f"{r.miles:.0f} mi away")
    if r.get("individual"):
        parts.append("looks like a solo practitioner (lower fit)")
    if pd.notna(r.confidence):
        parts.append(f"{r.confidence:.0%} sure it's a real business")
    return "; ".join(p for p in parts if p)


def score_places(df, warm_mask=None, why_top=2000):
    df = df.copy()
    df["warm"] = warm_mask.reindex(df.index, fill_value=False) if warm_mask is not None else False
    # Max 95 (+25 if the school already knows them, capped at 100):
    #   contact 30 + category fit 25 + local independence 15 + closeness 15 + data confidence 10
    s = (df.has_phone.astype(int) * 15 + df.has_website.astype(int) * 10 + df.has_email.astype(int) * 5
         + df.bucket.map(BUCKET_FIT).fillna(8)
         + df.chain_tier.map(CHAIN_POINTS).fillna(0)
         + (1 - (df.miles / 60).clip(0, 1)) * 15
         + df.confidence.fillna(0) * 10
         - df.individual.astype(int) * 25
         + df.warm.astype(int) * 25)
    df["score"] = s.clip(upper=100).round().astype(int)
    df["_s"] = s  # unrounded, so close calls don't all tie
    df = df.sort_values(["_s", "miles"], ascending=[False, True]).drop(columns="_s")
    # Building the explanation text is slow, so only do it for rows someone will actually see or export
    df["why"] = ""
    head = df.head(why_top)
    df.loc[head.index, "why"] = head.apply(_why, axis=1)
    return df


def add_school_provided(scored, unmatched):
    """Warm names we couldn't find in the data still go on the list - the school knows them."""
    rows = []
    for r in unmatched:
        phone = r.get("phone") if hasattr(r, "get") else None
        site = r.get("website") if hasattr(r, "get") else None
        rows.append({"name": r["name"], "phone": phone if pd.notna(phone) else None,
                     "website": site if pd.notna(site) else None, "bucket": "school_provided",
                     "chain_tier": "local", "miles": 0.0, "score": 100, "confidence": None,
                     "has_phone": bool(pd.notna(phone)), "has_website": bool(pd.notna(site)), "has_email": False,
                     "warm": True, "why": "provided by the school (not found in the open data)"})
    return pd.concat([pd.DataFrame(rows), scored], ignore_index=True) if rows else scored


# ---------- export ----------
def _domain(u):
    try:
        return urllib.parse.urlparse(u).netloc.removeprefix("www.") if u else ""
    except Exception:
        return ""


def to_hubspot_csv(df):
    out = pd.DataFrame({
        "Company name": df.name, "Phone Number": df.phone.map(fmt_phone),
        "Company Domain Name": df.website.map(_domain), "Website URL": df.website,
        "Street Address": df.get("street"), "City": df.get("city"), "State/Region": df.get("state"),
        "Postal Code": df.get("zip"), "Lead score": df.score,
        "Sponsor category": df.bucket.map(lambda b: BUCKET_LABELS.get(b, b)),
        "Distance (miles)": df.miles.round(1), "Why": df.why,
        "Data source": "Overture Maps Foundation (CDLA-Permissive-2.0)",
    })
    return out.to_csv(index=False).encode("utf-8")