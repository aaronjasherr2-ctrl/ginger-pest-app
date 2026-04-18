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
logo_html = f'<img src="data:image/png;base64,{logo_b64}" width="85" style="vertical-align: middle;">' if logo_b64 else "🌱"

st.markdown(f"""
<div style="display:flex; align-items:center; gap:25px; background:linear-gradient(135deg, #1B4332 0%, #2D6A4F 100%); padding:25px; border-radius:15px; color:white; margin-bottom:25px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
    {logo_html}
    <div>
        <h1 style="margin:0; font-size:36px; letter-spacing:1px; display:inline-block; vertical-align:middle;">Ginger Warning System</h1>
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
# GEOLOCATION
# ============================================================
loc = get_geolocation()
if loc:
    curr_lat, curr_lon = loc['coords']['latitude'], loc['coords']['longitude']
    if abs(st.session_state.lat - curr_lat) > 0.0001:
        st.session_state.lat, st.session_state.lon = curr_lat, curr_lon

st.info(f"📍 **Monitoring Site:** Lat {st.session_state.lat:.4f}, Lon {st.session_state.lon:.4f}")

# ============================================================
# ANALYSIS ENGINE (FIXED RASTER LOGIC)
# ============================================================
def perform_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    zone = roi.buffer(1000) # 1km Zone
    
    # 1. Rainfall
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31').sum().clip(zone)
    
    # 2. LST (Temperature)
    lst_col = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(zone).filterDate('2023-01-01', '2023-12-31').sort('CLOUD_COVER')
    lst_img = ee.Image(lst_col.first()).select('ST_B10')
    lst_c = lst_img.multiply(0.00341802).add(149).subtract(273.15).clip(zone)
    
    # 3. Pest Risk Index
    # Combination of High Moisture and High Temperature
    pest_risk = rain.divide(3000).multiply(0.5).add(lst_c.divide(35).multiply(0.5)).rename('pest_index').clip(zone)

    # Get Stats
    stats = {
        "rain": rain.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('precipitation'),
        "lst": lst_c.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('ST_B10'),
        "pest": pest_risk.reduceRegion(ee.Reducer.mean(), zone, 30).getInfo().get('pest_index')
    }
    
    return pest_risk, stats

if st.button("🚀 Analyze 1km Zone", type="primary", use_container_width=True):
    with st.spinner("Processing satellite data for 1km radius..."):
        try:
            p_map, s_data = perform_analysis(st.session_state.lat, st.session_state.lon)
            st.session_state.results = {"stats": s_data, "map": p_map}
        except Exception as e:
            st.error(f"Analysis Error: {e}")

# ============================================================
# DASHBOARD DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results['stats']
    p_map = st.session_state.results['map']
    
    # METRICS
    m1, m2, m3 = st.columns(3)
    m1.metric("Pest Risk Index", f"{res['pest']:.2f}")
    m2.metric("Average Rainfall", f"{res['rain']:.0f} mm")
    m3.metric("Avg LST (Temp)", f"{res['lst']:.1f} °C")

    st.markdown("---")

    # MAP & GRAPH
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.write("🗺️ **1km Radius Risk Level Map**")
        m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        
        # FIXED: Raster Visualization
        map_id = p_map.getMapId({'min': 0.3, 'max': 0.7, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
        tile_url = map_id['tile_fetcher'].url_format
        
        folium.TileLayer(
            tiles=tile_url,
            attr='Google Earth Engine',
            name='Risk Raster',
            overlay=True,
            control=True,
            opacity=0.7
        ).add_to(m)

        # Legend
        legend_html = '''
             <div style="position: fixed; bottom: 50px; left: 50px; width: 180px; height: auto; 
             background-color: white; border:2px solid #1B4332; z-index:9999; font-size:13px;
             padding: 10px; border-radius: 5px; color: black; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
             <b>Risk Level</b><br>
             <i style="background: #cc3232; width: 12px; height: 12px; float: left; margin-right: 8px;"></i> High Risk<br>
             <i style="background: #e7b416; width: 12px; height: 12px; float: left; margin-right: 8px;"></i> Moderate Risk<br>
             <i style="background: #2dc937; width: 12px; height: 12px; float: left; margin-right: 8px;"></i> Low Risk<br>
             </div>'''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        # Folium display
        st_folium(m, width="100%", height=500, key="v_map")

    with col_right:
        st.write("📊 **Factor Breakdown**")
        df = pd.DataFrame({
            "Indicator": ["Pest Risk", "Moisture", "Temp Stress"],
            "Value": [res['pest'], res['rain']/3500, res['lst']/45]
        })
        fig = px.bar(df, x="Indicator", y="Value", color="Indicator", range_y=[0,1],
                     color_discrete_map={"Pest Risk":"#cc3232", "Moisture":"#2A9D8F", "Temp Stress":"#E9C46A"})
        fig.update_layout(showlegend=False, height=450)
        st.plotly_chart(fig, use_container_width=True)

    # RECOMMENDATIONS
    st.markdown("### 📋 Recommended Farm Actions")
    if res['pest'] > 0.6:
        st.error(f"**🔴 High Alert:** Critical environment for pest outbreaks. Deepen drainage canals to 30cm. Apply organic bio-fungicides.")
    elif res['pest'] > 0.4:
        st.warning(f"**🟡 Moderate Caution:** Conditions are shifting. Inspect the stem base of your ginger plants twice a week.")
    else:
        st.success(f"**🟢 Low Risk:** Environmental conditions are safe. Maintain regular weeding and mulching.")
