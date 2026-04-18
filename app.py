import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import datetime
import os
import base64

# 1. HELPER: LOGO HANDLING
def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

# 2. UI CONFIG & DESIGN
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System", page_icon="🌱")

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
    .header-text p {{ margin: 0; font-size: 13px; color: #95d5b2; text-transform: uppercase; }}
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

# 3. EARTH ENGINE INITIALIZATION (The fix for your specific error)
def initialize_ee():
    if "ee_initialized" not in st.session_state:
        try:
            if "gcp_service_account" in st.secrets:
                # Get the project ID specifically from your secrets
                p_id = st.secrets["gcp_service_account"]["project_id"]
                creds = ee.ServiceAccountCredentials(
                    st.secrets["gcp_service_account"]["client_email"],
                    key_data=st.secrets["gcp_service_account"]["private_key"]
                )
                # Initialize with BOTH credentials AND project ID
                ee.Initialize(creds, project=p_id)
                st.session_state.ee_initialized = True
            else:
                ee.Initialize()
        except Exception as e:
            st.error(f"🚨 Connection Error: {e}")
            st.stop()

initialize_ee()

# 4. SIDEBAR SETTINGS
with st.sidebar:
    st.header("📍 Farm Settings")
    loc = get_geolocation()
    # Coordinates for Badiangan, Iloilo if GPS fails
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.7324, format="%.4f")
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.5480, format="%.4f")
    
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    selected_month = st.selectbox("Month", range(1,13), format_func=lambda x: month_names[x-1])
    run_btn = st.button("🚀 Run Analysis", use_container_width=True)

# 5. ANALYSIS LOGIC
@st.cache_data(show_spinner=False)
def run_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    results = []
    for m in range(1, 13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        lst = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean().multiply(0.02).subtract(273.15).clip(buffer)
        
        # Vulnerability score calculation
        vuln = slope.divide(30).multiply(0.2).add(rain.divide(500).multiply(0.4)).add(lst.divide(35).multiply(0.4)).clip(buffer)
        
        stats = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
        r_stats = rain.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
        t_stats = lst.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()

        results.append({
            "score": stats.get('slope', 0.5),
            "rain": r_stats.get('precipitation', 0),
            "temp": t_stats.get('LST_Day_1km', 28),
            "img": vuln
        })
    return results

# 6. DASHBOARD DISPLAY
if run_btn or "data" in st.session_state:
    if "data" not in st.session_state:
        with st.spinner("Accessing Satellite Data..."):
            st.session_state.data = run_analysis(lat, lon)

    active = st.session_state.data[selected_month-1]
    
    # METRICS
    m1, m2, m3 = st.columns(3)
    m1.metric("🌧️ Rainfall", f"{active['rain']:.1f} mm")
    m2.metric("🌡️ Temperature", f"{active['temp']:.1f} °C")
    
    score = active['score']
    risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"
    risk_color = "#ff4b4b" if risk == "HIGH" else "#ffa500" if risk == "MODERATE" else "#00c853"
    m3.markdown(f"**⚠️ Risk Level** <br> <h2 style='color:{risk_color}; margin:0;'>{risk}</h2>", unsafe_allow_html=True)

    # MAP SECTION
    st.subheader(f"🗺️ Vulnerability Raster Map - {month_names[selected_month-1]}")
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB dark_matter')
    
    try:
        vis = {'min': 0, 'max': 0.8, 'palette': ['00FF00', 'FFFF00', 'FF0000']}
        map_id = active['img'].getMapId(vis)
        
        folium.TileLayer(
            tiles=map_id['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            overlay=True,
            name='Vulnerability',
            opacity=0.7
        ).add_to(m)
        
        # Legend
        legend_html = '''
        <div style="position: fixed; bottom: 50px; left: 50px; width: 120px; height: 90px; 
        background-color: rgba(0,0,0,0.8); z-index:9999; font-size:12px; color:white;
        padding: 10px; border-radius: 5px; border: 1px solid grey;">
        <b>Risk Level</b><br>
        <i style="background: red; width: 10px; height: 10px; display: inline-block;"></i> High<br>
        <i style="background: yellow; width: 10px; height: 10px; display: inline-block;"></i> Moderate<br>
        <i style="background: green; width: 10px; height: 10px; display: inline-block;"></i> Low
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        st_folium(m, width="100%", height=500)
    except Exception as e:
        st.error(f"Map Rendering Error: {e}")
        st.info("The Earth Engine API is enabled, but the app needs the Project ID to create the map.")
