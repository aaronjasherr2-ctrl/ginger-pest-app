import streamlit as st
import ee
import folium
import os
import base64
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

# ----------------------------------------------------------
# 🛠️ LOGO DECODER
# ----------------------------------------------------------
def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    return None

# ----------------------------------------------------------
# 🎨 UI
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

logo_base64 = get_base64_of_bin_file("agusipan_logo.png")
logo_tag = f'<img src="data:image/png;base64,{logo_base64}" width="70">' if logo_base64 else "🌱"

st.markdown(f"""
<style>
.main {{ background-color: #081c15; color: #D8F3DC; }}
.header-container {{
    display:flex; align-items:center;
    background:rgba(27,67,50,0.8);
    padding:20px; border-radius:20px;
}}
.header-text {{ margin-left:20px; }}
</style>

<div class="header-container">
{logo_tag}
<div class="header-text">
<h2>Ginger Pest Warning System</h2>
<p>Agusipan 4H CLUB MONITORING DASHBOARD</p>
</div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# 🌍 INIT EE
# ----------------------------------------------------------
def init_ee():
    if "ee_init" not in st.session_state:
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

init_ee()

# ----------------------------------------------------------
# 📍 SIDEBAR
# ----------------------------------------------------------
with st.sidebar:
    loc = get_geolocation()
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.73)
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.54)

    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    m = st.selectbox("Month", range(1,13), format_func=lambda x: months[x-1])

    run = st.button("Run Analysis")

# ----------------------------------------------------------
# 📊 CACHE SAFE DATA ONLY
# ----------------------------------------------------------
@st.cache_data
def get_data(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    results = []

    for i in range(1,13):
        start = ee.Date.fromYMD(2023, i, 1)
        end = start.advance(1, 'month')

        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start,end).sum()

        vuln = slope.divide(30).multiply(0.3)\
                .add(rain.divide(500).multiply(0.7))

        score = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
        rain_val = rain.reduceRegion(ee.Reducer.mean(), buffer,100).getInfo()

        results.append({
            "score": score.get('slope',0.5),
            "rain": rain_val.get('precipitation',0)
        })

    return results

# ----------------------------------------------------------
# 🧠 REBUILD IMAGE (NOT CACHED)
# ----------------------------------------------------------
def build_vuln_image(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    start = ee.Date.fromYMD(2023, month, 1)
    end = start.advance(1, 'month')

    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start,end).sum()

    vuln = slope.divide(30).multiply(0.3)\
            .add(rain.divide(500).multiply(0.7))\
            .clip(buffer)

    return vuln

# ----------------------------------------------------------
# 🚀 RUN
# ----------------------------------------------------------
if run or "data" in st.session_state:

    if "data" not in st.session_state:
        st.session_state.data = get_data(lat, lon)

    data = st.session_state.data[m-1]

    st.metric("🌧 Rainfall", f"{data['rain']:.1f} mm")

    score = data['score']
    risk = "HIGH" if score>0.6 else "MODERATE" if score>0.35 else "LOW"
    st.metric("⚠ Risk", risk)

    # ------------------------------------------------------
    # 🗺️ MAP
    # ------------------------------------------------------
    vuln_img = build_vuln_image(lat, lon, m)

    mapp = folium.Map(location=[lat, lon], zoom_start=15)

    vis = {'min':0,'max':0.8,'palette':['green','yellow','red']}

    map_id = vuln_img.getMapId(vis)

    folium.TileLayer(
        tiles=map_id['tile_fetcher'].url_format,
        attr='EE',
        overlay=True
    ).add_to(mapp)

    st_folium(mapp, width=1200, height=500)
