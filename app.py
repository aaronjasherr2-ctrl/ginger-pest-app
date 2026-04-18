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
# 🛠️ HELPER: IMAGE ENCODER (Ensures Logo Displays)
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

# Load and Encode Logo
logo_base64 = get_base64_of_bin_file("agusipan_logo.png")
logo_tag = f'<img src="data:image/png;base64,{logo_base64}" width="70">' if logo_base64 else "🌱"

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    
    .main {{ 
        background-color: #081c15; 
        color: #D8F3DC; 
        font-family: 'Inter', sans-serif; 
    }}
    
    /* GLASSMORPHIC HEADER */
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
    .header-text h1 {{ margin: 0; font-size: 26px; color: #ffffff; letter-spacing: -0.5px; }}
    .header-text p {{ margin: 0; font-size: 13px; color: #95d5b2; text-transform: uppercase; letter-spacing: 1px; }}

    /* METRIC CARDS */
    div[data-testid="stMetric"] {{
        background: rgba(255,255,255,0.05);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid rgba(255,255,255,0.1);
        transition: 0.3s;
    }}
    div[data-testid="stMetric"]:hover {{
        background: rgba(255,255,255,0.1);
        border: 1px solid #40916c;
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
# 🛰️ EARTH ENGINE INITIALIZATION (Robust Service Account)
# ----------------------------------------------------------
def initialize_ee():
    if "ee_initialized" in st.session_state:
        return
    try:
        if "gcp_service_account" in st.secrets:
            # Load credentials from Streamlit Secrets
            creds = ee.ServiceAccountCredentials(
                st.secrets["gcp_service_account"]["client_email"],
                key_data=st.secrets["gcp_service_account"]["private_key"]
            )
            # Must provide the Project ID for getMapId to work
            ee.Initialize(creds, project=st.secrets["gcp_service_account"]["project_id"])
            st.session_state.ee_initialized = True
        else:
            # Local fallback
            ee.Initialize()
    except Exception as e:
        st.error(f"🚨 Earth Engine Connection Failed: {e}")
        st.info("Ensure the Earth Engine API is enabled in your Google Cloud Console.")
        st.stop()

initialize_ee()

# ----------------------------------------------------------
# ⚙️ SIDEBAR SETTINGS
# ----------------------------------------------------------
with st.sidebar:
    st.header("📍 Farm Settings")
    loc = get_geolocation()
    
    # Coordinates
    lat = st.number_input("Latitude", value=loc['coords']['latitude'] if loc else 10.7323, format="%.4f")
    lon = st.number_input("Longitude", value=loc['coords']['longitude'] if loc else 122.5481, format="%.4f")
    
    # Month Selection
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    selected_month = st.selectbox("Analysis Month", range(1,13), format_func=lambda x: month_names[x-1])
    
    st.markdown("---")
    run_btn = st.button("🚀 Run Analysis", use_container_width=True)

# ----------------------------------------------------------
# 📊 ANALYSIS CORE (CHIRPS & MODIS)
# ----------------------------------------------------------
@st.cache_data(show_spinner=False)
def run_full_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    
    # Terrain Data
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    monthly_data = []
    for m in range(1, 13):
        start = ee.Date.fromYMD(2023, m, 1)
        end = start.advance(1, 'month')

        # Satellite Collections
        rain_img = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        temp_img = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean().multiply(0.02).subtract(273.15).clip(buffer)
        
        # Simple Vulnerability Model (0-1 Scale)
        # Weighting Slope (20%), Rainfall (40%), Temperature (40%)
        vuln = slope.divide(30).multiply(0.2) \
            .add(rain_img.divide(500).multiply(0.4)) \
            .add(temp_img.divide(35).multiply(0.4)).clip(buffer)
        
        # Reduce to Mean Numbers
        stats = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
        r_stats = rain_img.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
        t_stats = temp_img.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()

        monthly_data.append({
            "score": stats.get('slope', 0.5), # GEE often uses band name for the key
            "rain": r_stats.get('precipitation', 0),
            "temp": t_stats.get('LST_Day_1km', 28),
            "img": vuln
        })
    return monthly_data

# ----------------------------------------------------------
# 🖥️ MAIN DASHBOARD DISPLAY
# ----------------------------------------------------------
if run_btn or "data" in st.session_state:
    if "data" not in st.session_state:
        with st.spinner("Accessing Satellite Constellations..."):
            st.session_state.data = run_full_analysis(lat, lon)

    # Get data for selected month
    active = st.session_state.data[selected_month-1]
    
    # Top Row: Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("🌧️ Rainfall", f"{active['rain']:.1f} mm")
    m2.metric("🌡️ Temperature", f"{active['temp']:.1f} °C")
    
    # Calculate Risk Label
    score = active['score']
    if score > 0.6: 
        risk_color, risk_text = "#ff4b4b", "HIGH"
    elif score > 0.35: 
        risk_color, risk_text = "#ffa500", "MODERATE"
    else: 
        risk_color, risk_text = "#00c853", "LOW"
    
    m3.markdown(f"**⚠️ Risk Level** <br> <h2 style='color:{risk_color}; margin:0;'>{risk_text}</h2>", unsafe_allow_html=True)

    st.markdown("---")

    # Middle Row: Map
    st.subheader(f"🗺️ Vulnerability Raster Map ({month_names[selected_month-1]})")
    
    # Create Folium Map
    m = folium.Map(location=[lat, lon], zoom_start=15, tiles='CartoDB dark_matter')
    
    try:
        # Generate the GEE Raster Layer
        vis_params = {'min': 0, 'max': 0.8, 'palette': ['00FF00', 'FFFF00', 'FF0000']}
        map_id = active['img'].getMapId(vis_params)
        
        folium.TileLayer(
            tiles=map_id['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            overlay=True,
            name='Vulnerability Heatmap',
            opacity=0.7
        ).add_to(m)
        
        # Add 1km Buffer Circle for context
        folium.Circle(
            location=[lat, lon],
            radius=1000,
            color='white',
            weight=1,
            fill=False,
            dash_array='5, 5'
        ).add_to(m)

        # Map Legend HTML
        legend_html = f'''
             <div style="position: fixed; bottom: 50px; left: 50px; width: 150px; height: 100px; 
             background-color: rgba(8,28,21,0.9); z-index:9999; font-size:12px;
             border:1px solid rgba(255,255,255,0.2); border-radius:10px; padding: 10px; color: white;">
             <b>Risk Intensity</b><br>
             <i style="background: #FF0000; width:10px; height:10px; display:inline-block;"></i> High Risk<br>
             <i style="background: #FFFF00; width:10px; height:10px; display:inline-block;"></i> Moderate<br>
             <i style="background: #00FF00; width:10px; height:10px; display:inline-block;"></i> Low Risk
             </div>
             '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        # Display Map
        st_folium(m, width="100%", height=500, key="farm_map")

    except Exception as e:
        st.error(f"Map Rendering Error: {e}")
        st.info("This is usually caused by the GEE API not being enabled for this project ID.")

    # Bottom Row: Action Plan
    st.markdown("### 📋 Recommended Action Plan")
    if risk_text == "HIGH":
        st.error("🚨 **Immediate intervention required.** Check for signs of rhizome rot. Apply approved fungicides and ensure secondary drainage channels are clear.")
    elif risk_text == "MODERATE":
        st.warning("⚠️ **Preventive mode.** Apply organic mulch to regulate soil temperature. Monitor fields twice weekly for pest emergence.")
    else:
        st.success("✅ **Standard maintenance.** Current environmental conditions are optimal for ginger growth. Continue normal fertilization schedule.")

else:
    st.info("👈 Set your farm coordinates in the sidebar and click 'Run Analysis' to begin.")
