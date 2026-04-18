import streamlit as st
import ee
import folium
import pandas as pd
import plotly.express as px
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Ginger Pest Warning")

# Session State
if "lat" not in st.session_state: st.session_state.lat = 10.9300
if "lon" not in st.session_state: st.session_state.lon = 122.5200
if "results" not in st.session_state: st.session_state.results = None

# Header
st.markdown(f"""
<div style="background:#1B4332; padding:20px; border-radius:15px; color:white; margin-bottom:20px;">
    <h1 style="margin:0;">🌱 Agusipan Ginger Warning System</h1>
    <p style="margin:0; opacity:0.8;">Precision Monitoring: 1km Farm Analysis Zone</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# EARTH ENGINE & LOCATION
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
    st.error(f"Earth Engine Error: {e}")

# Auto-Detect Location
loc = get_geolocation()
if loc:
    st.session_state.lat = loc['coords']['latitude']
    st.session_state.lon = loc['coords']['longitude']

col_a, col_b = st.columns([2,1])
with col_a:
    st.info(f"📍 **Monitoring Farm at:** Lat {st.session_state.lat:.4f}, Lon {st.session_state.lon:.4f}")
with col_b:
    with st.expander("Change Location Manually"):
        st.session_state.lat = st.number_input("Lat", value=st.session_state.lat, format="%.4f")
        st.session_state.lon = st.number_input("Lon", value=st.session_state.lon, format="%.4f")

# ============================================================
# ANALYSIS (1KM RADIUS)
# ============================================================
def perform_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    zone_1km = roi.buffer(1000)
    
    # Terrain & Rainfall Data
    slope = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).clip(zone_1km)
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31').sum().clip(zone_1km)
    
    # Risk Logic (Slope + Rain Weighting)
    risk_img = slope.divide(45).multiply(0.4).add(rain.divide(3500).multiply(0.6)).rename('risk')
    
    # Data for Stats
    s_val = slope.reduceRegion(ee.Reducer.mean(), zone_1km, 30).getInfo().get('slope')
    r_val = rain.reduceRegion(ee.Reducer.mean(), zone_1km, 30).getInfo().get('precipitation')
    score = risk_img.reduceRegion(ee.Reducer.mean(), zone_1km, 30).getInfo().get('risk')
    
    return risk_img, s_val, r_val, score

if st.button("🚀 Analyze 1km Zone", use_container_width=True, type="primary"):
    with st.spinner("Calculating risk factors..."):
        r_img, s_v, r_v, sc = perform_analysis(st.session_state.lat, st.session_state.lon)
        st.session_state.results = {"score": sc, "slope": s_v, "rain": r_v, "img": r_img}

# ============================================================
# RESULTS DASHBOARD
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    risk_cat = "HIGH" if res['score'] > 0.6 else "MEDIUM" if res['score'] > 0.35 else "LOW"
    
    # Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Pest Risk Level", risk_cat)
    m2.metric("Avg Slope", f"{res['slope']:.1f}°")
    m3.metric("Annual Rain", f"{res['rain']:.0f} mm")

    st.markdown("---")

    # Dual Maps & Graph
    map_col1, map_col2, graph_col = st.columns([1, 1, 1])

    with map_col1:
        st.write("🗺️ **Locator Map**")
        m1 = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        folium.Marker([st.session_state.lat, st.session_state.lon]).add_to(m1)
        st_folium(m1, height=300, width=None, key="locator")

    with map_col2:
        st.write("🎯 **1km Risk Zone**")
        m2 = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
        v_id = res['img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
        folium.TileLayer(tiles=v_id['tile_fetcher'].url_format, attr='GEE', name="Risk Zone").add_to(m2)
        st_folium(m2, height=300, width=None, key="risk_zone")

    with graph_col:
        st.write("📊 **Risk Breakdown**")
        df = pd.DataFrame({
            "Source": ["Slope", "Rainfall", "Total Risk"],
            "Intensity": [res['slope']/45, res['rain']/3500, res['score']]
        })
        fig = px.bar(df, x="Source", y="Intensity", color="Source", range_y=[0,1],
                     color_discrete_map={"Slope":"#2A9D8F", "Rainfall":"#264653", "Total Risk":"#E76F51"})
        st.plotly_chart(fig, use_container_width=True)

    # Simplified Recommendations
    st.markdown("### 📋 Farm Action Plan")
    rec_box = st.container()
    
    if risk_cat == "HIGH":
        st.error("🚨 **High Alert:** Immediate action required for crop safety.")
        st.markdown("""
        * **Manual Task:** Dig deep 'V' canals around rows to shed water.
        * **Treatment:** Apply organic fungicide/biocontrol to roots.
        * **Monitoring:** Check for wilting leaves every morning.
        """)
    elif risk_cat == "MEDIUM":
        st.warning("⚠️ **Warning:** Weather conditions are risky.")
        st.markdown("""
        * **Manual Task:** Apply mulch to stabilize soil moisture.
        * **Treatment:** Ensure proper organic fertilization to build plant strength.
        * **Monitoring:** Inspect the base of stems twice a week.
        """)
    else:
        st.success("✅ **Safe:** Maintain current farming practices.")
        st.markdown("""
        * **Manual Task:** Keep rows clean of weeds for better airflow.
        * **Monitoring:** Regular weekly scouting for general pests.
        """)
