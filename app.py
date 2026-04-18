import streamlit as st
import ee
import folium
import pandas as pd
import plotly.express as px
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os
import base64

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Ginger Warning System")

# Initialize Session States
if "lat" not in st.session_state: st.session_state.lat = 10.9300
if "lon" not in st.session_state: st.session_state.lon = 122.5200
if "results" not in st.session_state: st.session_state.results = None

# ============================================================
# BRANDING & LOGO
# ============================================================
def get_base64_logo(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_base64_logo("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo_b64}" width="85" style="vertical-align: middle; border-radius: 8px;">' if logo_b64 else "🌱"

# Header Section
st.markdown(f"""
<div style="display:flex; align-items:center; gap:25px; background:linear-gradient(135deg, #1B4332 0%, #2D6A4F 100%); padding:25px; border-radius:15px; color:white; margin-bottom:25px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
    {logo_html}
    <div>
        <h1 style="margin:0; font-size:36px; letter-spacing:1px;">Ginger Warning System</h1>
        <p style="margin:8px 0 0 0; font-size:18px; opacity:0.9; font-weight: 500;">Monitoring System designed by Agusipan 4H Club</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# EARTH ENGINE INITIALIZATION
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
    st.error(f"⚠️ Earth Engine Connection Failed: {e}")

# ============================================================
# GEOLOCATION & CONTROLS
# ============================================================
loc = get_geolocation()
if loc:
    curr_lat = loc['coords']['latitude']
    curr_lon = loc['coords']['longitude']
    if abs(st.session_state.lat - curr_lat) > 0.0001:
        st.session_state.lat, st.session_state.lon = curr_lat, curr_lon

st.subheader("📍 Farm Location")
c1, c2 = st.columns([2, 1])
with c1:
    st.success(f"✅ **Tracking Area:** {st.session_state.lat:.4f}, {st.session_state.lon:.4f}")
with c2:
    with st.expander("⌨️ Edit Coordinates Manually"):
        st.session_state.lat = st.number_input("Latitude", value=st.session_state.lat, format="%.4f")
        st.session_state.lon = st.number_input("Longitude", value=st.session_state.lon, format="%.4f")

# ============================================================
# ANALYSIS ENGINE (LST, RAIN, PEST, LSI)
# ============================================================
def build_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    zone = roi.buffer(1000) # 1km Radius
    
    # 1. Rainfall (CHIRPS)
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31').sum().clip(zone)
    
    # 2. LST - Land Surface Temp (Landsat 8)
    lst_col = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(zone).filterDate('2023-01-01', '2023-12-31').sort('CLOUD_COVER')
    lst_img = ee.Image(lst_col.first()).select('ST_B10')
    lst_c = lst_img.multiply(0.00341802).add(149).subtract(273.15).clip(zone)
    
    # 3. Terrain
    slope = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).clip(zone)
    
    # 4. Indices
    pest_idx = rain.divide(3000).multiply(0.5).add(lst_c.divide(35).multiply(0.5)).rename('pest')
    lsi = slope.divide(45).multiply(0.6).add(rain.divide(3000).multiply(0.4)).rename('lsi')
    
    # Stats
    stats = {
        "rain": rain.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('precipitation'),
        "lst": lst_c.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('ST_B10'),
        "pest": pest_idx.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('pest'),
        "lsi": lsi.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('lsi')
    }
    return pest_idx, stats

if st.button("🚀 Run Comprehensive Analysis", type="primary", use_container_width=True):
    with st.spinner("Analyzing satellite layers..."):
        p_map, s_data = build_analysis(st.session_state.lat, st.session_state.lon)
        st.session_state.results = {"stats": s_data, "map": p_map}

# ============================================================
# RESULTS DASHBOARD
# ============================================================
if st.session_state.results:
    res = st.session_state.results['stats']
    
    # 1. KPI Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pest Risk Index", f"{res['pest']:.2f}")
    m2.metric("Average Rainfall", f"{res['rain']:.0f} mm")
    m3.metric("LST (Temp)", f"{res['lst']:.1f} °C")
    m4.metric("LSI (Landslide)", f"{res['lsi']:.2f}")

    st.markdown("---")

    # 2. Maps and Graphs
    col_m1, col_m2, col_g = st.columns([1, 1, 1])
    
    with col_m1:
        st.write("🌍 **Location Map**")
        ml = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        folium.Marker([st.session_state.lat, st.session_state.lon]).add_to(ml)
        st_folium(ml, height=350, key="locator")

    with col_m2:
        st.write("🎯 **1km Vulnerability Raster**")
        mr = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
        map_id = st.session_state.results['map'].getMapId({'min': 0.3, 'max': 0.7, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
        folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='GEE', name="Risk").add_to(mr)
        
        # High Contrast Legend
        lgd = '''<div style="position: fixed; bottom: 30px; left: 30px; width: 150px; background: white; border:2px solid #1B4332; z-index:9999; padding:10px; font-size:12px; border-radius:5px; color:black;">
        <b>Vulnerability</b><br>
        <i style="background:#cc3232;width:10px;height:10px;float:left;margin-right:5px;"></i> High Risk<br>
        <i style="background:#e7b416;width:10px;height:10px;float:left;margin-right:5px;"></i> Moderate<br>
        <i style="background:#2dc937;width:10px;height:10px;float:left;margin-right:5px;"></i> Safe</div>'''
        mr.get_root().html.add_child(folium.Element(lgd))
        st_folium(mr, height=350, key="raster")

    with col_g:
        st.write("📊 **Factor Breakdown**")
        df = pd.DataFrame({
            "Indicator": ["Pest Index", "Moisture", "Temp Stress", "LSI"],
            "Value": [res['pest'], res['rain']/3500, res['lst']/45, res['lsi']]
        })
        fig = px.bar(df, x="Indicator", y="Value", color="Indicator", range_y=[0,1],
                     color_discrete_map={"Pest Index":"#cc3232", "LSI":"#264653", "Moisture":"#2A9D8F", "Temp Stress":"#E9C46A"})
        fig.update_layout(showlegend=False, height=350, margin=dict(t=5, b=5, l=5, r=5))
        st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # SIMPLE FARM ACTION PLAN
    # ============================================================
    st.markdown("### 📋 Recommended Farm Actions")
    r1, r2, r3 = st.columns(3)
    
    with r1:
        st.markdown("**🛡️ Pest Mitigation**")
        if res['pest'] > 0.6:
            st.error("🔴 **High Alert:** Clean V-canals (30cm deep) immediately. Apply organic fungicides.")
        else:
            st.success("🟢 **Safe:** Standard weeding and airflow management sufficient.")

    with r2:
        st.markdown("**🌋 Landslide (LSI) Safety**")
        if res['lsi'] > 0.5:
            st.warning("⚠️ **Caution:** Steep/Wet conditions. Use contour barriers and avoid total clearing.")
        else:
            st.info("💡 **Stable:** Ensure mulching to prevent surface soil wash-off.")

    with r3:
        st.markdown("**🌡️ Heat & Temperature**")
        if res['lst'] > 32:
            st.warning("☀️ **Heat Stress:** Increase mulching thickness to cool rhizomes.")
        else:
            st.success("✅ **Optimal:** LST is within safe range for ginger growth.")
