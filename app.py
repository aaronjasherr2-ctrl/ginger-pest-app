import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os
import base64

# ----------------------------------------------------------
# 🛠️ LOGO DECODER
# ----------------------------------------------------------
def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

# ----------------------------------------------------------
# 🎨 UI & DESIGN
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

logo_base64 = get_base64_of_bin_file("agusipan_logo.png")
logo_tag = f'<img src="data:image/png;base64,{logo_base64}" width="70">' if logo_base64 else "🌱"

st.markdown(f"""
<style>
    .main {{ background-color: #081c15; color: #D8F3DC; font-family: 'Inter', sans-serif; }}
    .header-container {{
        display: flex; align-items: center; background: rgba(27,67,50,0.8);
        padding: 20px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 25px; backdrop-filter: blur(10px);
    }}
    .header-text {{ margin-left: 20px; }}
    .header-text h1 {{ margin: 0; font-size: 26px; color: #ffffff; }}
    .header-text p {{ margin: 0; font-size: 13px; color: #95d5b2; text-transform: uppercase; }}
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
# 🛰️ EARTH ENGINE INITIALIZATION (THE DEFINITIVE FIX)
# ----------------------------------------------------------
def initialize_ee():
    if "ee_initialized" not in st.session_state:
        try:
            if "gcp_service_account" in st.secrets:
                creds_info = st.secrets["gcp_service_account"]
                # Use ServiceAccountCredentials
                creds = ee.ServiceAccountCredentials(
                    creds_info["client_email"],
                    key_data=creds_info["private_key"]
                )
                # 1. Initialize with credentials
                ee.Initialize(creds)
                # 2. FORCE the project ID for cloud calls
                ee.data.setProject(creds_info["project_id"])
                
                st.session_state.ee_initialized = True
            else:
                ee.Initialize()
        except Exception as e:
            st.error(f"🚨 EE Init Error: {e}")
            st.stop()

initialize_ee()

# ----------------------------------------------------------
# ⚙️ SIDEBAR
# ----------------------------------------------------------
with st.sidebar:
    st.header("📍 Farm Settings")
    loc = get_geolocation()
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.7324, format="%.4f")
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.5480, format="%.4f")
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
    
    # Terrain
    slope = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).clip(buffer)

    results = []
    for m in range(1, 13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        # Climate Data
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        lst = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean().multiply(0.02).subtract(273.15).clip(buffer)
        
        # Risk Model
        vuln = slope.divide(30).multiply(0.2).add(rain.divide(500).multiply(0.4)).add(lst.divide(35).multiply(0.4)).clip(buffer)
        
        # Stats
        s_val = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('slope', 0.5)
        r_val = rain.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('precipitation', 0)
        t_val = lst.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('LST_Day_1km', 28)

        results.append({"score": s_val, "rain": r_val, "temp": t_val, "img": vuln})
    return results

# ----------------------------------------------------------
# 🖥️ DASHBOARD DISPLAY
# ----------------------------------------------------------
if run_btn or "data" in st.session_state:
    if "data" not in st.session_state:
        with st.spinner("Processing..."):
            st.session_state.data = run_analysis(lat, lon)

    active = st.session_state.data[selected_month-1]
    
    # METRICS
    m1, m2, m3 = st.columns(3)
    m1.metric("🌧️ Rainfall", f"{active['rain']:.1f} mm")
    m2.metric("🌡️ Temperature", f"{active['temp']:.1f} °C")
    
    risk = "HIGH" if active['score'] > 0.6 else "MODERATE" if active['score'] > 0.35 else "LOW"
    m3.metric("⚠️ Risk Level", risk)

    # MAP WITH RASTER
    st.subheader(f"🗺️ Vulnerability Raster Map ({month_names[selected_month-1]})")
    
    # Use a try/except specifically for the map to prevent total app crash
    try:
        m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB dark_matter')
        
        vis = {'min': 0, 'max': 0.8, 'palette': ['00FF00', 'FFFF00', 'FF0000']}
        # The key fix: getting the map ID from the clipped image
        map_id = active['img'].getMapId(vis)
        
        folium.TileLayer(
            tiles=map_id['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            overlay=True,
            name='Vulnerability',
            opacity=0.7
        ).add_to(m)
        
        # CUSTOM LEGEND
        legend_html = '''
        <div style="position: fixed; bottom: 50px; left: 50px; width: 130px; height: 90px; 
        background: rgba(0,0,0,0.7); color: white; padding: 10px; border-radius: 5px; 
        z-index:9999; font-size: 12px; border: 1px solid white;">
        <b>Legend</b><br>
        <i style="background:red; width:10px; height:10px; display:inline-block;"></i> High Risk<br>
        <i style="background:yellow; width:10px; height:10px; display:inline-block;"></i> Moderate<br>
        <i style="background:green; width:10px; height:10px; display:inline-block;"></i> Low Risk
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        st_folium(m, width="100%", height=500)
    except Exception as e:
        st.error(f"Map Rendering Error: {e}")
