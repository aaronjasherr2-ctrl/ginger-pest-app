import streamlit as st
import ee
import folium
import base64
import os
import pandas as pd
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Pest Warning System")

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
if "lat" not in st.session_state: st.session_state.lat = 10.9300
if "lon" not in st.session_state: st.session_state.lon = 122.5200
if "results" not in st.session_state: st.session_state.results = None 

# ============================================================
# LOGO & HEADER
# ============================================================
def get_logo_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo = get_logo_base64("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo}" width="90">' if logo else "🌱"

st.markdown(f"""
<div style="display:flex; align-items:center; gap:20px; background:#1B4332; padding:20px; border-radius:15px; margin-bottom:25px;">
    {logo_html}
    <div>
        <h1 style="margin:0; color:white; font-size: 2.5rem;">Pest Warning System</h1>
        <p style="margin:0; color:#D8F3DC; font-size: 1.2rem; font-weight: bold; letter-spacing: 1.5px;">MONITORING SYSTEM DESIGNED BY AGUSIPAN 4H CLUB</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# EARTH ENGINE & ANALYSIS ENGINE
# ============================================================
try:
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=info["private_key"])
        ee.Initialize(creds, project=info["project_id"])
    else:
        ee.Initialize()
except Exception as e:
    st.error(f"❌ Connection Error: {e}")

def get_vulnerability_raster(roi_buffer, month_idx):
    dem = ee.Image('USGS/SRTMGL1_003').clip(roi_buffer)
    slope = ee.Terrain.slope(dem)
    
    # Historical Rain for the selected month
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')\
             .filter(ee.Filter.calendarRange(month_idx, month_idx, 'month'))\
             .filterDate('2020-01-01', '2024-01-01').mean().clip(roi_buffer)

    # Normalize and combine (60% Rain, 40% Slope)
    slope_norm = slope.divide(45)
    rain_norm = rain.divide(500)
    vuln = slope_norm.multiply(0.4).add(rain_norm.multiply(0.6)).rename('vulnerability')
    return vuln

# ============================================================
# SIDEBAR / INPUTS
# ============================================================
with st.sidebar:
    st.header("📍 Location Control")
    if st.button("🛰️ Use Device GPS", use_container_width=True):
        loc = get_geolocation()
        if loc:
            st.session_state.lat = loc['coords']['latitude']
            st.session_state.lon = loc['coords']['longitude']
            st.success("GPS Updated!")

    with st.expander("⌨️ Manual Coordinate Entry"):
        mlat = st.number_input("Latitude", value=st.session_state.lat, format="%.6f")
        mlon = st.number_input("Longitude", value=st.session_state.lon, format="%.6f")
        if st.button("Apply Coordinates"):
            st.session_state.lat, st.session_state.lon = mlat, mlon
            st.rerun()

    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = st.selectbox("📅 Select Month for Pattern Analysis", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    
    test_btn = st.button("🔍 TEST VULNERABILITY", type="primary", use_container_width=True)

# ============================================================
# EXECUTION
# ============================================================
if test_btn:
    with st.spinner("Analyzing localized environmental risks..."):
        roi = ee.Geometry.Point([st.session_state.lon, st.session_state.lat])
        zone_1km = roi.buffer(1000)
        
        vuln_img = get_vulnerability_raster(zone_1km, sel_month)
        stats = vuln_img.reduceRegion(ee.Reducer.mean(), zone_1km, 30).getInfo()
        score = stats.get('vulnerability', 0)
        
        # Monthly trend for graph
        trend = []
        for m in range(1, 13):
            m_img = get_vulnerability_raster(zone_1km, m)
            m_score = m_img.reduceRegion(ee.Reducer.mean(), zone_1km, 30).getInfo().get('vulnerability', 0)
            trend.append(m_score)

        st.session_state.results = {
            "score": score,
            "trend": trend,
            "vuln_img": vuln_img,
            "zone_1km": zone_1km,
            "risk": "HIGH" if score > 0.55 else "MODERATE" if score > 0.35 else "LOW",
            "month": month_names[sel_month-1]
        }

# ============================================================
# MAIN DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # 1. Dashboard Summary
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric(label="Current Vulnerability Score", value=f"{res['score']:.2f}")
        st.subheader(f"Status: {res['risk']}")
        st.write(f"Analyzed Pattern for: **{res['month']}**")
        
    with col2:
        st.write("### 📈 Annual Vulnerability Trend")
        df = pd.DataFrame(res['trend'], index=month_names, columns=['Risk Score'])
        st.line_chart(df, color="#1B4332")

    # 2. Raster Map (1km Zone)
    st.markdown("---")
    st.subheader("🎯 1km Radius Vulnerability Raster")
    
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
    
    # Add Raster Layer
    map_id = res['vuln_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
    folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='Google Earth Engine', name="Vulnerability").add_to(m)
    
    # Add Legend
    legend_html = '''
     <div style="position: fixed; bottom: 50px; left: 50px; width: 150px; height: 110px; 
     background-color: white; border:2px solid grey; z-index:9999; font-size:14px;
     padding: 10px; border-radius: 5px;">
     <b>Risk Level</b><br>
     <i style="background:#cc3232;width:12px;height:12px;display:inline-block"></i> High<br>
     <i style="background:#e7b416;width:12px;height:12px;display:inline-block"></i> Moderate<br>
     <i style="background:#2dc937;width:12px;height:12px;display:inline-block"></i> Low
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    folium.Marker([st.session_state.lat, st.session_state.lon], popup="Target Farm").add_to(m)
    st_folium(m, width="100%", height=500)

    # 3. Recommendations
    st.markdown("---")
    st.subheader("📋 Manual Recommendations & Field Guide")
    rec1, rec2 = st.columns(2)
    
    with rec1:
        st.markdown(f"### 🛡️ Immediate Manual Recommendation ({res['risk']})")
        if res['risk'] == "HIGH":
            st.error("""
            **ACTION REQUIRED:**
            1. **Drainage Management:** Deepen lateral canals to 30-45cm. Ensure no stagnant water exists for more than 12 hours.
            2. **Soil Sterilization:** If bacterial wilt is suspected, drench the 1km boundary soil with Copper Oxychloride.
            3. **Isolation:** Prevent movement of farm tools from the High-Risk zone to other areas.
            """)
        elif res['risk'] == "MODERATE":
            st.warning("""
            **PREVENTATIVE MEASURES:**
            1. **Bio-Control:** Apply *Trichoderma* as a soil drench to prevent Rhizome Rot.
            2. **Nutrient Boost:** Apply Potash-rich fertilizer to strengthen the plant's cell walls.
            3. **Observation:** Check for "water-soaked" spots at the base of the pseudostem twice weekly.
            """)
        else:
            st.success("""
            **MAINTENANCE MODE:**
            1. **Mulching:** Apply rice straw or dried leaves to stabilize soil temperature.
            2. **Organic Matter:** Mix vermicompost into the soil during hilling-up.
            3. **Spacing:** Maintain 25cm distance for optimal airflow.
            """)

    with rec2:
        st.markdown("### 🌿 Comprehensive Manual Guide")
        with st.expander("🩺 Disease ID (Manual Check)"):
            st.write("**Soft Rot:** Yellowing starts at leaf tips; rhizomes become mushy.")
            st.write("**Bacterial Wilt:** Sudden wilting while leaves are still green; milky ooze in stem.")
        with st.expander("🧪 Best Practices"):
            st.write("- **Crop Rotation:** Do not plant after Solanaceous crops (Tomato/Pepper).")
            st.write("- **Seed Treatment:** Treat rhizomes with Mancozeb before planting.")
