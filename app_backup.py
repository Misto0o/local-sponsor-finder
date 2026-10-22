"""Sponsor Finder prototype (Streamlit). Run with:  streamlit run app.py"""
import pandas as pd
import streamlit as st

import finder
from config import BUCKET_LABELS

st.set_page_config(page_title="Sponsor Finder", page_icon="🎯", layout="wide")

MAX_RADIUS = 60
EXPORT_ROWS = 2000


@st.cache_data(show_spinner="Loading nearby businesses...")
def nearby(lat, lon, cfg_version):
    # Always load the max radius once per school; the slider just filters it in memory (fast)
    return finder.load_nearby(lat, lon, MAX_RADIUS)


# ---------------- sidebar ----------------
st.sidebar.header("School")
if "loc" not in st.session_state:
    st.session_state.loc = (*finder.KEARNS, finder.KEARNS_ADDRESS)
address = st.sidebar.text_input("School address", finder.KEARNS_ADDRESS)
if st.sidebar.button("Find this school"):
    try:
        st.session_state.loc = finder.geocode(address)
    except Exception as e:
        st.sidebar.error(f"Couldn't geocode that address ({e}).")
lat, lon, matched = st.session_state.loc
st.sidebar.caption(f"Using: {matched}  \n({lat:.4f}, {lon:.4f})")

st.sidebar.header("Filters")
radius = st.sidebar.slider("Radius (miles)", 5, MAX_RADIUS, MAX_RADIUS, step=5)
min_conf = st.sidebar.slider("Min data confidence", 0.0, 1.0, 0.7, step=0.05,
                             help="Overture's confidence that the place exists. It does not guarantee the phone number is current.")
chain_label = st.sidebar.selectbox("Chains", list(finder.CHAIN_OPTIONS), index=1)
need_phone = st.sidebar.checkbox("Must have a phone number", True)
need_web = st.sidebar.checkbox("Must have a website", False)
hide_ind = st.sidebar.checkbox("Hide solo practitioners", True, help="Individual doctors/NPs listed as businesses are weak sponsor targets.")
text = st.sidebar.text_input("Search name")

st.sidebar.header("Businesses the school already knows")
st.sidebar.caption("Upload a CSV with a `name` column (optional `phone`, `website`). They jump to the top.")
st.sidebar.download_button("Download CSV template", "name,phone,website\nExample Pizza Co,,\n", "warm_list_template.csv")
warm_file = st.sidebar.file_uploader("School's list", type="csv")

# ---------------- data ----------------
try:
    df = nearby(lat, lon, finder.config_version())
    df = df[df.miles <= radius]
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

all_buckets = sorted(b for b in df[df.exclude_reason.isna()].bucket.unique())
buckets = st.sidebar.multiselect("Categories", all_buckets, default=all_buckets,
                                 format_func=lambda b: BUCKET_LABELS.get(b, b))

filters = dict(min_conf=min_conf, buckets=buckets, chain_tiers=finder.CHAIN_OPTIONS[chain_label],
               need_phone=need_phone, need_website=need_web, text=text, hide_individuals=hide_ind)
pool = finder.filter_places(df, **filters)

warm_mask, unmatched = None, []
if warm_file is not None:
    warm = pd.read_csv(warm_file)
    if "name" not in warm.columns:
        st.sidebar.error("The CSV needs a `name` column.")
    else:
        warm_mask, unmatched = finder.match_warm(df[df.is_open], warm)
        known = df[warm_mask.reindex(df.index, fill_value=False) & df.is_open]
        pool = pd.concat([pool, known[~known.id.isin(pool.id)]])  # school knows them: keep even if filtered out

scored = finder.score_places(pool, warm_mask)
scored = finder.add_school_provided(scored, unmatched)

# ---------------- main ----------------
st.title("🎯 Sponsor Finder")
st.caption("Prototype by Kearns Academy Teamship for Stay Plugged In. Ranked call lists of local businesses near a school.")

steps = finder.funnel(df, **filters)
cols = st.columns(len(steps) + (1 if warm_file is not None else 0))
for c, (label, n) in zip(cols, steps):
    c.metric(label, f"{n:,}")
if warm_file is not None:
    cols[-1].metric("School's known contacts", f"{int(scored.warm.sum()):,}")

tab_list, tab_cat, tab_limits = st.tabs(["Call list", "By category", "Limits & data"])

with tab_list:
    top_n = st.slider("Rows to show", 25, 1000, 200, step=25)
    view = scored.head(top_n).assign(
        Phone=lambda d: d.phone.map(finder.fmt_phone),
        Category=lambda d: d.bucket.map(lambda b: BUCKET_LABELS.get(b, b)),
        Miles=lambda d: d.miles.round(1),
    )[["score", "name", "Phone", "website", "Category", "city", "Miles", "chain_tier", "why"]]
    view.columns = ["Score", "Business", "Phone", "Website", "Category", "City", "Miles", "Chain", "Why it ranked here"]
    st.dataframe(view, hide_index=True, height=480,
                 column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                                "Website": st.column_config.LinkColumn()})
    st.download_button(f"⬇ Export top {EXPORT_ROWS:,} for HubSpot (CSV)", finder.to_hubspot_csv(scored.head(EXPORT_ROWS)),
                       "sponsor_call_list.csv", "text/csv")
    if unmatched:
        st.info(f"{len(unmatched)} business(es) from the school's list weren't found in the open data; they were added as school-provided rows.")
    mp = scored.dropna(subset=["lat", "lon"]).head(2000)
    if len(mp):
        st.map(mp[["lat", "lon"]], size=40)

with tab_cat:
    counts = (scored.assign(Category=scored.bucket.map(lambda b: BUCKET_LABELS.get(b, b)))
              .groupby("Category").size().sort_values(ascending=False))
    st.bar_chart(counts)

with tab_limits:
    st.markdown("""
**What this is:** a ranked starting list, not a verified lead list. Please call-check before relying on it.

- **No decision-maker names.** The open data has business phone numbers, not who to ask for. Finding the right person is still a human step.
- **Phones and emails aren't verified,** and emails are often generic inboxes.
- **The score is rules-based:** contact info, category fit (restaurants and businesses that tie into what students learn rank higher), local vs. chain, data confidence, and a boost for businesses the school already knows. The weights are a starting point and live in `config.py`.
- **Community involvement is not scored yet.** That needs a website check (planned next).
- **Chains** are detected by brand ID and by how often a name repeats across NC and SC, so a few generic names may be misflagged.

Business data © Overture Maps Foundation, licensed CDLA-Permissive-2.0.
""")