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
# 🛠️ HELPER FUNCTIONS
# ----------------------------------------------------------
def get_base64_of_bin_file(bin_file):
    """Converts a local file to base64 for HTML embedding"""
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

# ----------------------------------------------------------
# 🎨 CONFIG & UI THEME
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System", page_icon="🌱")

# Load logo
logo_base64 = get_base64_of_bin_file("agusipan_logo.png")
logo_tag = f'<img src="data:image/png;base64,{logo_base64}" width="70">' if logo_base64 else "🌱"

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');
    
    .main {{ background-color: #081c15; color: #D8F3DC; font-family: 'Inter', sans-serif; }}
    
    /* HEADER CONTAINER */
    .header-container {{
        display: flex;
        align-items: center;
        background: rgba(27,67,50,0.8);
        padding: 20px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 25px;
        backdrop-filter: blur(10px);
    }}
    .header-text {{ margin-left: 20px; }}
    .header-text h1 {{ margin: 0; font-size: 26px; color: #ffffff; letter-spacing: -1px; }}
    .header-text p {{ margin: 0; font-size: 14px; color: #95d5b2; text-transform: uppercase; letter-spacing: 1px; }}

    /* METRIC STYLING */
    div[data-testid="stMetric"] {{
        background: rgba(255,255,255,0.05);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid rgba(255,255,255,0.1);
    }}

    /* MAP LEGEND */
    .map-legend {{
        position: absolute; bottom: 50px; left: 50px; z-index: 1000;
        background: rgba(8, 28, 21, 0.9); padding: 15px; border-radius: 10px;
        border: 1px solid rgba(216, 243, 220, 0.3); color: white; font-size: 12px;
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
# ⚙️ SIDEBAR & INPUTS
# ----------------------------------------------------------
with st.sidebar:
    st.header("📍 Farm Settings")
    loc = get_geolocation()
    default_lat, default_lon = 10.98, 122.50
    
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else default_lat, format="%.4f")
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else default_lon, format="%.4f")
    
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    selected_month = st.selectbox("Analysis Month", range(1,13), format_func=lambda x: month_names[x-1])
    
    run_btn = st.button("🚀 Run Analysis", use_container_width=True)

# ----------------------------------------------------------
# 🛰️ EARTH ENGINE LOGIC
# ----------------------------------------------------------
try:
    ee.Initialize()
except:
    ee.Authenticate()
    ee.Initialize()

@st.cache_data(show_spinner=False)
def get_vulnerability_data(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    
    # Terrain (Static)
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    monthly_data = []
    for m in range(1, 13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        # Climate & Bio Factors
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        lst = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean().multiply(0.02).subtract(273.15).clip(buffer)
        
        # NDVI (Sentinel-2)
        s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate(start, end).filterBounds(buffer).median()
        ndvi = s2.normalizedDifference(['B8','B4']).clip(buffer)

        # Vulnerability Model
        vuln = slope.divide(30).multiply(0.2).add(rain.divide(400).multiply(0.3)).add(lst.divide(35).multiply(0.25)).add(ndvi.multiply(-1).add(1).multiply(0.25))
        
        # Stats
        stats = vuln.reduceRegion(ee.Reducer.mean(), buffer, 30).getInfo()
        r_stats = rain.reduceRegion(ee.Reducer.mean(), buffer, 30).getInfo()
        t_stats = lst.reduceRegion(ee.Reducer.mean(), buffer, 30).getInfo()

        monthly_data.append({
            "score": stats.get('slope', 0.5),
            "rain": r_stats.get('precipitation', 0),
            "temp": t_stats.get('LST_Day_1km', 28),
            "image": vuln
        })
    return monthly_data

# ----------------------------------------------------------
# 📊 EXECUTION & DISPLAY
# ----------------------------------------------------------
if run_btn or "app_data" in st.session_state:
    if "app_data" not in st.session_state:
        with st.spinner("Analyzing Satellite Imagery..."):
            st.session_state.app_data = get_vulnerability_data(lat, lon)

    data = st.session_state.app_data[selected_month-1]
    
    # Metrics Row
    c1, c2, c3 = st.columns(3)
    c1.metric("🌧️ Rainfall", f"{data['rain']:.1f} mm")
    c2.metric("🌡️ Temperature", f"{data['temp']:.1f} °C")
    
    risk_val = data['score']
    if risk_val > 0.6: color, status = "#ff4b4b", "HIGH"
    elif risk_val > 0.4: color, status = "#ffa500", "MODERATE"
    else: color, status = "#00c853", "LOW"
    
    c3.markdown(f"**⚠️ Risk Level** <br> <h2 style='color:{color}; margin:0;'>{status}</h2>", unsafe_allow_html=True)

    # Map Section
    st.subheader("🗺️ High-Resolution Vulnerability Map")
    
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB dark_matter')
    
    vis_params = {'min': 0.2, 'max': 0.8, 'palette': ['#00c853', '#ffff00', '#ff4b4b']}
    map_id = data['image'].getMapId(vis_params)
    
    folium.TileLayer(
        tiles=map_id['tile_fetcher'].url_format,
        attr='Google Earth Engine',
        name='Vulnerability Heatmap',
        overlay=True,
        opacity=0.7
    ).add_to(m)

    # Legend Overlay
    legend_html = f'''
     <div class="map-legend">
        <b>Vulnerability Index</b><br>
        <i style="background: #ff4b4b; width:10px; height:10px; display:inline-block;"></i> High Risk<br>
        <i style="background: #ffff00; width:10px; height:10px; display:inline-block;"></i> Moderate<br>
        <i style="background: #00c853; width:10px; height:10px; display:inline-block;"></i> Low Risk
     </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    st_folium(m, width="100%", height=500)

    # Action Plan
    st.markdown("---")
    if status == "HIGH":
        st.error(f"🚨 **Urgent Action Required:** Risk is {risk_val:.2f}. Implement preventive fungicide application and clear all drainage channels.")
    elif status == "MODERATE":
        st.warning(f"⚠️ **Precautionary Phase:** Risk is {risk_val:.2f}. Increase field monitoring and apply organic mulch.")
    else:
        st.success(f"✅ **Optimal Conditions:** Risk is {risk_val:.2f}. Continue standard maintenance.")
