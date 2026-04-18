import streamlit as st
import ee
import folium
import base64
import os
import pandas as pd
import plotly.express as px
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Agusipan Ginger Warning System")

# Initialize Session States
if "lat" not in st.session_state: st.session_state.lat = 10.9300
if "lon" not in st.session_state: st.session_state.lon = 122.5200
if "results" not in st.session_state: st.session_state.results = None 

# ============================================================
# STYLING & HEADER
# ============================================================
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

st.markdown(f"""
<div style="display:flex; align-items:center; gap:15px; background:#1B4332; padding:20px; border-radius:15px; margin-bottom:25px; color:white;">
    <div style="font-size:40px;">🌱</div>
    <div>
        <h1 style="margin:0; font-size:28px;">Agusipan Ginger Warning System</h1>
        <p style="margin:0; opacity:0.8;">Integrated Pest Risk & Rainfall Intelligence</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# EARTH ENGINE INIT
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
    st.error(f"Cloud Connection Failed: {e}")

# ============================================================
# LOCATION ENGINE
# ============================================================
col_loc_left, col_loc_right = st.columns([2, 1])

with col_loc_left:
    st.subheader("📍 Farm Location")
    # Automatic GPS Detection
    loc = get_geolocation()
    if loc:
        st.session_state.lat, st.session_state.lon = loc['coords']['latitude'], loc['coords']['longitude']
    
    st.info(f"**Target Area:** Lat {st.session_state.lat:.4f}, Lon {st.session_state.lon:.4f}")

with col_loc_right:
    with st.expander("🛠️ Change Coordinates"):
        new_lat = st.number_input("Latitude", value=st.session_state.lat, format="%.4f")
        new_lon = st.number_input("Longitude", value=st.session_state.lon, format="%.4f")
        if st.button("Apply New Location"):
            st.session_state.lat, st.session_state.lon = new_lat, new_lon
            st.rerun()

# ============================================================
# ANALYSIS CALCULATIONS
# ============================================================
def run_gee_analysis(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000) # 1km Radius Zone
    
    # Data Sources
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31').sum()
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)
    
    # Normalization (0 to 1)
    s_stats = slope.reduceRegion(ee.Reducer.minMax(), buffer, 30).getInfo()
    slope_norm = slope.divide(ee.Number(s_stats.get('slope_max')).max(1))
    
    # Calculate Final Score
    vuln = slope_norm.multiply(0.5).add(0.3).rename('score').clip(buffer)
    
    # Extract Values for Graph
    avg_slope = slope.reduceRegion(ee.Reducer.mean(), buffer, 30).getInfo().get('slope')
    total_rain = rain.reduceRegion(ee.Reducer.mean(), buffer, 30).getInfo().get('precipitation')
    
    return vuln, buffer, avg_slope, total_rain

# ============================================================
# MAIN INTERFACE
# ============================================================
month_list = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
target_month = st.selectbox("📅 Select Month for Pest Analysis", range(1, 13), index=5, format_func=lambda x: month_list[x-1])

if st.button("🚀 Start Farm Analysis", type="primary", use_container_width=True):
    with st.spinner("Analyzing satellite layers..."):
        v_img, v_buf, s_val, r_val = run_gee_analysis(st.session_state.lat, st.session_state.lon, target_month)
        
        score_val = v_img.reduceRegion(ee.Reducer.mean(), v_buf, 30).getInfo().get('score')
        risk_lvl = "HIGH" if score_val > 0.6 else "MEDIUM" if score_val > 0.35 else "LOW"
        
        st.session_state.results = {
            "score": score_val, "risk": risk_lvl, "slope": s_val, "rain": r_val,
            "v_img": v_img, "month": month_list[target_month-1]
        }

# ============================================================
# DASHBOARD DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # ROW 1: METRICS
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Risk Score", f"{res['score']:.2f}")
    m2.metric("Risk Level", res['risk'])
    m3.metric("Avg Slope", f"{res['slope']:.1f}°")
    m4.metric("Annual Rain", f"{res['rain']:.0f}mm")

    st.markdown("---")

    # ROW 2: DUAL MAPS & GRAPH
    col_map1, col_map2, col_graph = st.columns([1, 1, 1])
    
    with col_map1:
        st.write("🌍 **Location Locator**")
        m_loc = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        folium.Marker([st.session_state.lat, st.session_state.lon], tooltip="Your Farm").add_to(m_loc)
        st_folium(m_loc, height=300, width=None, key="loc_map")

    with col_map2:
        st.write("🎯 **1km Risk Zone**")
        m_risk = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
        # Add GEE Layer
        map_id = res['v_img'].getMapId({'min': 0, 'max': 1, 'palette': ['green', 'yellow', 'red']})
        folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='GEE', overlay=True, name="Risk Raster").add_to(m_risk)
        
        # Legend
        legend_html = f'''
             <div style="position: fixed; bottom: 20px; left: 20px; width: 120px; background: white; 
             padding: 10px; border: 2px solid #1B4332; z-index:999; font-size:12px; border-radius:5px;">
             <b>Risk Legend</b><br>
             <i style="background: red; width:10px; height:10px; float:left; margin-right:5px;"></i> High<br>
             <i style="background: yellow; width:10px; height:10px; float:left; margin-right:5px;"></i> Mid<br>
             <i style="background: green; width:10px; height:10px; float:left; margin-right:5px;"></i> Safe
             </div>'''
        m_risk.get_root().html.add_child(folium.Element(legend_html))
        st_folium(m_risk, height=300, width=None, key="risk_map")

    with col_graph:
        st.write("📊 **Analysis Breakdown**")
        chart_data = pd.DataFrame({
            "Factor": ["Slope Strength", "Rainfall Intensity", "Final Score"],
            "Value": [res['slope']/45, res['rain']/4000, res['score']] # Normalized for visual
        })
        fig = px.bar(chart_data, x="Factor", y="Value", color="Factor", range_y=[0,1],
                     color_discrete_map={"Slope Strength":"#2A9D8F", "Rainfall Intensity":"#264653", "Final Score":"#E76F51"})
        fig.update_layout(showlegend=False, height=300, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # SIMPLE RECOMMENDATIONS
    # ============================================================
    st.markdown("### 📋 Farm Action Plan")
    
    rec_col_left, rec_col_right = st.columns(2)
    
    with rec_col_left:
        st.info(f"**Analysis for {res['month']}**")
        if res['risk'] == "HIGH":
            st.error(f"### 🚨 High Risk Action Needed")
            st.markdown("""
            * **Immediate Drainage:** Clean all outlet canals to prevent root rot.
            * **Pest Check:** Scout twice a week for Bacterial Wilt (yellowing stems).
            * **Treatment:** Apply organic fungicide (*Trichoderma*) immediately.
            """)
        elif res['risk'] == "MEDIUM":
            st.warning(f"### ⚠️ Moderate Caution")
            st.markdown("""
            * **Soil Hilling:** Add soil to the base of ginger to keep rhizomes dry.
            * **Weeding:** Keep rows clean to improve airflow.
            * **Monitor:** Check plants after heavy rain.
            """)
        else:
            st.success(f"### ✅ Low Risk (Safe)")
            st.markdown("""
            * **Maintain Mulch:** Add rice straw to keep soil temperature steady.
            * **Fertilize:** Apply organic compost to boost plant immunity.
            """)

    with rec_col_right:
        st.markdown("**General Ginger Guide**")
        with st.expander("🌱 Planting Tips"):
            st.write("Ensure rhizomes are treated with fungicide before planting. Use 25-30cm spacing.")
        with st.expander("🩺 Disease Signs"):
            st.write("Look for 'milky ooze' in cut stems. This is a sign of fatal Bacterial Wilt.")
        with st.expander("🌦️ Weather Prep"):
            st.write("In high-slope areas, use contour planting to prevent soil erosion.")
