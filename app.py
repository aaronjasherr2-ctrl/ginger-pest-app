import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import datetime
import os
import base64

# ----------------------------------------------------------
# 🛠️ HELPER: IMAGE ENCODER (Fixes Missing Logo)
# ----------------------------------------------------------
def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

# ----------------------------------------------------------
# 🎨 UI CONFIG & MODERN THEME
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System", page_icon="🌱")

# Encode logo for HTML
logo_base64 = get_base64_of_bin_file("agusipan_logo.png")
logo_tag = f'<img src="data:image/png;base64,{logo_base64}" width="70">' if logo_base64 else "🌱"

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    .main {{ background-color: #081c15; color: #D8F3DC; font-family: 'Inter', sans-serif; }}
    .header-container {{
        display: flex; align-items: center; background: rgba(27,67,50,0.8);
        padding: 20px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 25px; backdrop-filter: blur(10px);
    }}
    .header-text {{ margin-left: 20px; }}
    .header-text h1 {{ margin: 0; font-size: 26px; color: #ffffff; }}
    .header-text p {{ margin: 0; font-size: 14px; color: #95d5b2; text-transform: uppercase; }}
    div[data-testid="stMetric"] {{
        background: rgba(255,255,255,0.05); padding: 20px; border-radius: 15px;
        border: 1px solid rgba(255,255,255,0.1);
    }}
</style>

<div class="header-container">
    {logo_tag}
    <div class="header-text">
        <h1>Ginger Pest Warning System</h1>
        <p>Agusipan 4H CLUB MONITORING DASHBOARD</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# 🛰️ EARTH ENGINE INITIALIZATION (Fixes Analysis Crash)
# ----------------------------------------------------------
def initialize_ee():
    try:
        if "gcp_service_account" in st.secrets:
            creds = ee.ServiceAccountCredentials(
                st.secrets["gcp_service_account"]["client_email"],
                key_data=st.secrets["gcp_service_account"]["private_key"]
            )
            ee.Initialize(creds)
        else:
            ee.Initialize()
    except Exception as e:
        st.error(f"Authentication Failed: {e}")
        st.stop()

initialize_ee()

# ----------------------------------------------------------
# ⚙️ SIDEBAR
# ----------------------------------------------------------
with st.sidebar:
    st.header("📍 Farm Settings")
    loc = get_geolocation()
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.98, format="%.4f")
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.50, format="%.4f")
    
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    selected_month = st.selectbox("Month", range(1,13), format_func=lambda x: month_names[x-1])
    run_btn = st.button("🚀 Run Analysis", use_container_width=True)

# ----------------------------------------------------------
# 📊 ANALYSIS LOGIC
# ----------------------------------------------------------
@st.cache_data(show_spinner=False)
def run_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    
    # Static Terrain
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    results = []
    for m in range(1, 13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        # Data Collections
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        lst = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean().multiply(0.02).subtract(273.15).clip(buffer)
        
        # Calculate Vulnerability
        # Note: slope is renamed to 'mean' by the reducer usually
        vuln = slope.divide(30).multiply(0.2).add(rain.divide(500).multiply(0.3)).add(lst.divide(35).multiply(0.5)).clip(buffer)
        
        # Get Mean Values
        s_val = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('slope', 0.5)
        r_val = rain.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('precipitation', 0)
        t_val = lst.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('LST_Day_1km', 28)

        results.append({"score": s_val, "rain": r_val, "temp": t_val, "img": vuln})
    return results

# ----------------------------------------------------------
# 🖥️ DISPLAY
# ----------------------------------------------------------
if run_btn or "data" in st.session_state:
    if "data" not in st.session_state:
        with st.spinner("Fetching Satellite Data..."):
            st.session_state.data = run_analysis(lat, lon)

    active_data = st.session_state.data[selected_month-1]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("🌧️ Rainfall", f"{active_data['rain']:.1f} mm")
    c2.metric("🌡️ Temperature", f"{active_data['temp']:.1f} °C")
    
    risk = "HIGH" if active_data['score'] > 0.6 else "MODERATE" if active_data['score'] > 0.35 else "LOW"
    c3.metric("⚠️ Risk Level", risk)

    # MAP
    st.subheader("🗺️ Vulnerability Raster Map (1km Radius)")
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB dark_matter')
    
    vis = {'min': 0, 'max': 1, 'palette': ['00FF00', 'FFFF00', 'FF0000']}
    map_id = active_data['img'].getMapId(vis)
    
    folium.TileLayer(
        tiles=map_id['tile_fetcher'].url_format,
        attr='Google Earth Engine',
        overlay=True,
        name='Vulnerability'
    ).add_to(m)
    
    st_folium(m, width="100%", height=500)
