import streamlit as st
import ee
import folium
import pandas as pd
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import base64
import os

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Pest Warning System")

# ============================================================
# SESSION STATE & EE INIT
# ============================================================
if "results" not in st.session_state: st.session_state.results = None

try:
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=info["private_key"])
        ee.Initialize(creds, project=info["project_id"])
    else:
        ee.Initialize()
except Exception as e:
    st.error(f"Connection Error: {e}")

# ============================================================
# HEADER WITH LOGO
# ============================================================
def get_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_base64("agusipan_logo.png")

# Custom CSS for the Header
st.markdown(f"""
    <div style="display: flex; align-items: center; background-color: #1B4332; padding: 20px; border-radius: 15px; margin-bottom: 25px;">
        <div style="flex: 0 0 100px;">
            <img src="data:image/png;base64,{logo_b64 if logo_b64 else ''}" style="width: 80px; height: 80px; object-fit: contain;">
        </div>
        <div style="flex: 1; margin-left: 20px;">
            <h1 style="color: white; margin: 0; padding: 0; font-family: sans-serif;">Pest Warning System</h1>
            <h4 style="color: #D8F3DC; margin: 0; padding: 0; font-weight: 300;">Monitoring system designed by AGUSIPAN 4H CLUB</h4>
        </div>
    </div>
""", unsafe_allow_html=True)

# ============================================================
# ANALYSIS LOGIC
# ============================================================
def get_vulnerability_trend(roi):
    """Calculates historical vulnerability (Slope + Monthly Rain) for the full year"""
    months = range(1, 13)
    scores = []
    
    # Static Parameter: Slope
    dem = ee.Image('USGS/SRTMGL1_003')
    slope = ee.Terrain.slope(dem).clip(roi.buffer(1000))
    slope_val = slope.reduceRegion(ee.Reducer.mean(), roi, 30).getInfo().get('slope', 0)
    
    # Dynamic Parameter: Historical Rainfall
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31')
    
    for m in months:
        m_rain = rain_col.filter(ee.Filter.calendarRange(m, m, 'month')).sum()
        rain_val = m_rain.reduceRegion(ee.Reducer.mean(), roi, 100).getInfo().get('precipitation', 0)
        
        # Simplified Vulnerability Logic: (Slope * 0.4) + (Normalized Rain * 0.6)
        # Assuming 500mm is a 'max' rainfall month for normalization
        v_score = (slope_val * 0.02) + ((rain_val / 500) * 0.6)
        scores.append(min(v_score, 1.0))
        
    return scores

# ============================================================
# INPUTS & EXECUTION
# ============================================================
col_input, col_spacer = st.columns([1, 2])
with col_input:
    st.subheader("📍 Farm Location")
    loc = get_geolocation()
    lat = loc['coords']['latitude'] if loc else 10.9300
    lon = loc['coords']['longitude'] if loc else 122.5200
    st.caption(f"Coordinates: {lat:.4f}, {lon:.4f}")
    
    run_btn = st.button("Analyze Parameters", type="primary", use_container_width=True)

if run_btn:
    with st.spinner("Calculating Historical Patterns..."):
        roi = ee.Geometry.Point([lon, lat])
        trend_data = get_vulnerability_trend(roi)
        
        st.session_state.results = {
            "trend": trend_data,
            "current_score": trend_data[4], # Defaulting to May (index 4)
            "lat": lat, "lon": lon,
            "roi": roi
        }

# ============================================================
# RESULTS DASHBOARD
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    
    # Row 1: Metrics & Graph
    r1_c1, r1_c2 = st.columns([1, 2])
    
    with r1_c1:
        risk_level = "HIGH" if res['current_score'] > 0.6 else "MODERATE" if res['current_score'] > 0.35 else "LOW"
        st.metric("Vulnerability Index", f"{res['current_score']:.2f}")
        st.subheader(f"Status: {risk_level}")
        
        # Aligned Manual Recommendation
        if risk_level == "HIGH":
            st.error("**Urgent Alert:** Implement immediate trenching and apply bio-fungicides.")
        elif risk_level == "MODERATE":
            st.warning("**Caution:** Increase scouting to twice weekly. Check for water-soaking.")
        else:
            st.success("**Stable:** Maintain standard mulching and organic fertilization.")

    with r1_c2:
        st.write("### 📈 Monthly Vulnerability Pattern (Historical)")
        df = pd.DataFrame(res['trend'], index=month_names, columns=['Vulnerability Score'])
        st.line_chart(df, color="#1B4332")

    # Row 2: Maps
    st.markdown("---")
    r2_c1, r2_c2 = st.columns(2)
    
    with r2_c1:
        st.subheader("🗺️ Regional Risk (5km)")
        m_reg = folium.Map(location=[res['lat'], res['lon']], zoom_start=13)
        folium.Marker([res['lat'], res['lon']]).add_to(m_reg)
        st_folium(m_reg, width="100%", height=350, key="map_reg")

    with r2_c2:
        st.subheader("🎯 1km Risk Buffer Zone")
        m_loc = folium.Map(location=[res['lat'], res['lon']], zoom_start=15)
        # Create 1km Buffer
        buffer_zone = res['roi'].buffer(1000).getInfo()
        folium.GeoJson(buffer_zone, style_function=lambda x: {
            'color': '#cc3232' if res['current_score'] > 0.6 else '#1B4332',
            'fillOpacity': 0.2
        }).add_to(m_loc)
        folium.Marker([res['lat'], res['lon']]).add_to(m_loc)
        st_folium(m_loc, width="100%", height=350, key="map_loc")
