import streamlit as st
import ee
import folium
import base64
import os
from streamlit_folium import st_folium

# ----------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

# ----------------------------------------------------------
# LOGO FUNCTION
# ----------------------------------------------------------
def get_logo_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo = get_logo_base64("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo}" width="80">' if logo else "🌱"

# ----------------------------------------------------------
# HEADER
# ----------------------------------------------------------
st.markdown(f"""
<div style="display:flex; align-items:center; gap:15px;
background:#1B4332; padding:15px; border-radius:15px;">
{logo_html}
<div>
<h2 style="margin:0; color:white;">Ginger Pest Warning System</h2>
<p style="margin:0; color:#D8F3DC;">Agusipan 4H CLUB MONITORING DASHBOARD</p>
</div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# INIT EARTH ENGINE
# ----------------------------------------------------------
# FIX 1: Replace escaped newlines in private_key from Streamlit secrets.
# Streamlit sometimes stores "\n" as a literal string "\\n" which
# breaks the PEM key format that Google's auth library expects.
try:
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        # Normalize the private key — replace escaped newlines if present
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ee.ServiceAccountCredentials(
            info["client_email"],
            key_data=info["private_key"]
        )
        ee.Initialize(creds, project=info["project_id"])
    else:
        ee.Initialize()
except Exception as e:
    st.error(f"Earth Engine Init Error: {e}")
    st.stop()

# ----------------------------------------------------------
# USER INPUT (MAIN AREA)
# ----------------------------------------------------------
st.subheader("📍 Farm Location")

col1, col2, col3 = st.columns(3)

lat = col1.number_input("Latitude", value=10.73, format="%.4f")
lon = col2.number_input("Longitude", value=122.54, format="%.4f")

month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
month = col3.selectbox("Month", range(1, 13),
                       format_func=lambda x: month_names[x - 1])

run = st.button("🚀 Run Analysis")

# ----------------------------------------------------------
# BUILD IMAGE (FIXED)
# ----------------------------------------------------------
def build_vulnerability(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    start = ee.Date.fromYMD(2023, month, 1)
    end = start.advance(1, 'month')

    # FIX 2: Removed ee.Algorithms.If — it evaluates both branches on the
    # server and fails when the constant fallback has no matching bands.
    # Instead, merge a zero-filled constant image so the collection is
    # never empty before calling .sum().
    fallback = ee.Image.constant(0).rename('precipitation')
    rain_col = (
        ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
        .filterDate(start, end)
        .select('precipitation')
        .merge(ee.ImageCollection([fallback]))   # guarantees non-empty
    )
    rain = rain_col.sum().rename('precipitation')

    vuln = (
        slope.divide(30).multiply(0.3)
        .add(rain.divide(500).multiply(0.7))
        .rename("vuln")
        .clip(buffer)
    )

    return vuln, buffer

# ----------------------------------------------------------
# RUN ANALYSIS
# ----------------------------------------------------------
if run:

    with st.spinner("Processing analysis..."):

        try:
            vuln_img, buffer = build_vulnerability(lat, lon, month)

            score_dict = vuln_img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=buffer,
                scale=100
            ).getInfo()

            # FIX 3: Explicit None guard — .get() can still return None
            # if the band exists but the reducer produced no valid pixels.
            raw_score = score_dict.get("vuln")
            score = float(raw_score) if raw_score is not None else 0.5

        except Exception as e:
            st.error("Analysis failed.")
            st.write(e)
            st.stop()

    # ------------------------------------------------------
    # METRICS
    # ------------------------------------------------------
    risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"

    c1, c2 = st.columns(2)
    c1.metric("📊 Vulnerability Score", f"{score:.2f}")
    c2.metric("⚠ Risk Level", risk)

    # ------------------------------------------------------
    # MAP
    # ------------------------------------------------------
    st.subheader("🗺️ Vulnerability Heatmap")

    try:
        m = folium.Map(location=[lat, lon], zoom_start=15)

        vis = {
            'min': 0,
            'max': 0.8,
            'palette': ['green', 'yellow', 'red']
        }

        map_id_dict = vuln_img.getMapId(vis)

        # FIX 4: Safely retrieve the tile URL — the attribute name changed
        # across earthengine-api versions. Try url_format first, then
        # fall back to formatTileUrl for older installs.
        tile_fetcher = map_id_dict.get('tile_fetcher')
        if tile_fetcher is not None and hasattr(tile_fetcher, 'url_format'):
            tile_url = tile_fetcher.url_format
        elif tile_fetcher is not None and hasattr(tile_fetcher, 'formatTileUrl'):
            tile_url = tile_fetcher.formatTileUrl(0, 0, 0).rsplit('/', 3)[0] + '/{z}/{x}/{y}'
        else:
            # Last resort: reconstruct from mapid + token
            tile_url = (
                "https://earthengine.googleapis.com/map/"
                f"{map_id_dict['mapid']}/{{z}}/{{x}}/{{y}}?token={map_id_dict['token']}"
            )

        folium.TileLayer(
            tiles=tile_url,
            attr='Google Earth Engine',
            overlay=True,
            name='Vulnerability'
        ).add_to(m)

        folium.Circle([lat, lon], radius=1000,
                      color='blue', fill=False).add_to(m)

        folium.LayerControl().add_to(m)

        # LEGEND
        legend = """
        <div style="position: fixed; bottom: 50px; left: 50px;
        background: rgba(0,0,0,0.7); padding:10px;
        border-radius:8px; color:white; z-index:1000;">
        <b>Risk Level</b><br>
        🟢 Low<br>
        🟡 Moderate<br>
        🔴 High
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend))

        st_folium(m, width=1200, height=500)

    except Exception as e:
        st.error("Map failed to render.")
        st.write(e)

    # ------------------------------------------------------
    # ACTION PLAN
    # ------------------------------------------------------
    st.subheader("📌 Recommendation")

    if risk == "LOW":
        st.success("Conditions are favorable. Maintain standard practices.")
    elif risk == "MODERATE":
        st.warning("Monitor crops and improve drainage.")
    else:
        st.error("High pest/disease risk. Immediate intervention required.")
