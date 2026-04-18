import streamlit as st
import ee
import folium
import os
import base64
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

# ----------------------------------------------------------
# LOGO
# ----------------------------------------------------------
def get_logo_base64(path):
    if os.path.exists(path):
        return base64.b64encode(open(path, "rb").read()).decode()
    return None

st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

logo = get_logo_base64("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo}" width="70">' if logo else "🌱"

st.markdown(f"""
<style>
body {{ background:#081c15; color:#D8F3DC; }}
.header {{ display:flex; align-items:center; gap:15px;
background:rgba(27,67,50,0.8); padding:15px; border-radius:15px; }}
</style>

<div class="header">
{logo_html}
<div>
<h2>Ginger Pest Warning System</h2>
<p>Agusipan 4H CLUB MONITORING DASHBOARD</p>
</div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# INIT EE
# ----------------------------------------------------------
def init_ee():
    if "ee_init" not in st.session_state:
        try:
            if "gcp_service_account" in st.secrets:
                info = st.secrets["gcp_service_account"]
                creds = ee.ServiceAccountCredentials(
                    info["client_email"],
                    key_data=info["private_key"]
                )
                ee.Initialize(creds, project=info["project_id"])
            else:
                ee.Initialize()
            st.session_state.ee_init = True
        except Exception as e:
            st.error(f"EE Init Error: {e}")
            st.stop()

init_ee()

# ----------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------
with st.sidebar:
    loc = get_geolocation()
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.73)
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.54)
    month = st.selectbox("Month", range(1,13))
    run = st.button("Run Analysis")

# ----------------------------------------------------------
# SAFE ANALYSIS (NO IMAGE IN CACHE)
# ----------------------------------------------------------
@st.cache_data
def get_data(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    out = []

    for m in range(1,13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')\
                .filterDate(start,end).sum().clip(buffer)

        vuln = slope.divide(30).multiply(0.3)\
               .add(rain.divide(500).multiply(0.7))\
               .rename("vuln")  # 🔥 FIX: ensure band exists

        try:
            score = vuln.reduceRegion(
                ee.Reducer.mean(), buffer, 100
            ).getInfo().get("vuln", 0.5)
        except:
            score = 0.5

        try:
            rain_val = rain.reduceRegion(
                ee.Reducer.mean(), buffer, 100
            ).getInfo().get("precipitation", 0)
        except:
            rain_val = 0

        out.append({"score": score, "rain": rain_val})

    return out

# ----------------------------------------------------------
# BUILD IMAGE SAFELY
# ----------------------------------------------------------
def build_image(lat, lon, m):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    start = ee.Date.fromYMD(2023, m, 1)
    end = start.advance(1, 'month')

    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')\
                .filterDate(start,end)

    # 🔥 fallback if empty
    rain = ee.Image(
        ee.Algorithms.If(
            rain_col.size().gt(0),
            rain_col.sum(),
            ee.Image.constant(0)
        )
    )

    vuln = slope.divide(30).multiply(0.3)\
           .add(rain.divide(500).multiply(0.7))\
           .rename("vuln")\
           .clip(buffer)

    return vuln

# ----------------------------------------------------------
# RUN
# ----------------------------------------------------------
if run or "data" in st.session_state:

    if "data" not in st.session_state:
        with st.spinner("Processing..."):
            st.session_state.data = get_data(lat, lon)

    d = st.session_state.data[month-1]

    st.metric("🌧 Rainfall", f"{d['rain']:.1f} mm")

    risk = "HIGH" if d['score']>0.6 else "MODERATE" if d['score']>0.35 else "LOW"
    st.metric("⚠ Risk", risk)

    # ------------------------------------------------------
    # MAP
    # ------------------------------------------------------
    mapp = folium.Map(location=[lat, lon], zoom_start=15)

    try:
        img = build_image(lat, lon, month)

        vis = {'min':0,'max':0.8,'palette':['green','yellow','red']}

        map_id = img.getMapId(vis)

        folium.TileLayer(
            tiles=map_id['tile_fetcher'].url_format,
            attr='EE',
            overlay=True
        ).add_to(mapp)

    except Exception as e:
        st.error("Map rendering failed")
        st.warning(str(e))

    st_folium(mapp, width=1200, height=500)
