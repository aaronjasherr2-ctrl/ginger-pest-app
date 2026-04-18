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
logo_html = "🌱" 
if os.path.exists("agusipan_logo.png"):
    with open("agusipan_logo.png", "rb") as f:
        logo_encoded = base64.b64encode(f.read()).decode()
        logo_html = f'<img src="data:image/png;base64,{logo_encoded}" width="90">'

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
    st.error(f"❌ Connection Error: {e}")

# ============================================================
# SPEED-OPTIMIZED FUNCTIONS
# ============================================================

@st.cache_data(ttl=3600) # Cache results for 1 hour to prevent redundant loading
def fast_analysis(lat, lon, sel_month):
    roi = ee.Geometry.Point([lon, lat])
    zone_1km = roi.buffer(1000)
    
    # 1. Faster Terrain Analysis (30m scale is fine for static DEM)
    dem = ee.Image('USGS/SRTMGL1_003').clip(zone_1km)
    slope = ee.Terrain.slope(dem)
    slope_val = slope.reduceRegion(ee.Reducer.mean(), zone_1km, 100).get('slope').getInfo() or 0
    
    # 2. Optimized Climate & Vulnerability Trend
    # We fetch a monthly climatology instead of daily filtering to save time
    rain_col = ee.ImageCollection("UCSB-CHG/CHIRPS/PENTAD").filterDate('2000-01-01', '2025-12-31')
    
    trend = []
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    
    # Pre-calculate climate for selected month for metrics
    sel_rain = rain_col.filter(ee.Filter.calendarRange(sel_month, sel_month, 'month')).mean()
    sel_rain_val = sel_rain.reduceRegion(ee.Reducer.mean(), zone_1km, 200).get('precipitation').getInfo() or 0

    # Quick loop using larger scale (200m) for the graph
    for m in range(1, 13):
        m_rain = rain_col.filter(ee.Filter.calendarRange(m, m, 'month')).mean()
        m_rain_val = m_rain.reduceRegion(ee.Reducer.mean(), zone_1km, 250).get('precipitation').getInfo() or 0
        # Formula: (SlopeNorm * 0.4) + (RainNorm * 0.6)
        v_score = (slope_val / 45 * 0.4) + (m_rain_val / 10 * 0.6) # Pentad data scale
        trend.append(min(v_score, 1.0))

    # 3. Raster for Map (Current Selection)
    rain_map = rain_col.filter(ee.Filter.calendarRange(sel_month, sel_month, 'month')).mean().clip(zone_1km)
    vuln_raster = slope.divide(45).multiply(0.4).add(rain_map.divide(10).multiply(0.6)).rename('vulnerability')
    
    # 4. LST and Humidity (Historical Mean)
    lst_col = ee.ImageCollection("MODIS/061/MOD11A1").filter(ee.Filter.calendarRange(sel_month, sel_month, 'month')).select('LST_Day_1km')
    lst_val = lst_col.mean().multiply(0.02).subtract(273.15).reduceRegion(ee.Reducer.mean(), roi, 1000).get('LST_Day_1km').getInfo() or 0
    
    return {
        "score": trend[sel_month-1],
        "trend": trend,
        "vuln_img": vuln_raster,
        "lst": lst_val,
        "hum": (sel_rain_val * 2.5), # Proxy for humidity based on rainfall intensity
        "risk": "HIGH" if trend[sel_month-1] > 0.55 else "MODERATE" if trend[sel_month-1] > 0.35 else "LOW"
    }

# ============================================================
# SIDEBAR / INPUTS
# ============================================================
with st.sidebar:
    st.header("📍 Location Control")
    if st.button("🛰️ Use Device GPS", use_container_width=True):
        loc = get_geolocation()
        if loc:
            st.session_state.lat, st.session_state.lon = loc['coords']['latitude'], loc['coords']['longitude']
            st.rerun()

    with st.expander("⌨️ Manual Coordinate Entry"):
        mlat = st.number_input("Latitude", value=st.session_state.lat, format="%.6f")
        mlon = st.number_input("Longitude", value=st.session_state.lon, format="%.6f")
        if st.button("Apply Coordinates"):
            st.session_state.lat, st.session_state.lon = mlat, mlon
            st.rerun()

    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = st.selectbox("📅 Pattern Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    
    test_btn = st.button("🔍 TEST VULNERABILITY", type="primary", use_container_width=True)

# ============================================================
# EXECUTION
# ============================================================
if test_btn:
    with st.spinner("🚀 Speed-optimizing 25-year analysis..."):
        try:
            results = fast_analysis(st.session_state.lat, st.session_state.lon, sel_month)
            results["month"] = month_names[sel_month-1]
            st.session_state.results = results
        except Exception as e:
            st.error(f"Analysis Error: {e}")

# ============================================================
# MAIN DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Vulnerability Index", f"{res['score']:.2f}")
    m2.metric("Long-term LST", f"{res['lst']:.1f}°C")
    m3.metric("Humidity Index", f"{res['hum']:.1f}")
    m4.metric("Risk Level", res['risk'])

    st.write(f"### 📈 Annual Pattern (2000-2025 Average)")
    df = pd.DataFrame(res['trend'], index=month_names, columns=['Risk Score'])
    st.line_chart(df, color="#1B4332")

    st.markdown("---")
    st.subheader("🎯 1km Radius Vulnerability Raster")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
    map_id = res['vuln_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
    folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='GEE', name="Vulnerability").add_to(m)
    
    legend_html = '''
     <div style="position: fixed; bottom: 50px; left: 50px; width: 140px; height: 110px; 
     background-color: white; border:2px solid #1B4332; z-index:9999; font-size:14px;
     padding: 10px; border-radius: 8px; box-shadow: 2px 2px 5px rgba(0,0,0,0.5);">
     <b style="color: black;">Risk Level</b><br>
     <i style="background:#cc3232;width:12px;height:12px;display:inline-block"></i> <span style="color: black;">High</span><br>
     <i style="background:#e7b416;width:12px;height:12px;display:inline-block"></i> <span style="color: black;">Moderate</span><br>
     <i style="background:#2dc937;width:12px;height:12px;display:inline-block"></i> <span style="color: black;">Low</span>
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.Marker([st.session_state.lat, st.session_state.lon]).add_to(m)
    st_folium(m, width="100%", height=500)

    st.markdown("---")
    st.subheader("Recommendations")
    rec1, rec2 = st.columns(2)
    with rec1:
        st.markdown(f"### Immediate Recommendation ({res['risk']})")
        if res['risk'] == "HIGH":
            st.error("1. Deepen drainage canals to 45cm. \n2. Apply Copper Oxychloride drench. \n3. Isolate infected farm blocks.")
        elif res['risk'] == "MODERATE":
            st.warning("1. Apply Trichoderma to soil. \n2. Increase Potash fertilizer. \n3. Check stem bases twice weekly.")
        else:
            st.success("1. Maintain 10cm rice straw mulch. \n2. Add vermicompost. \n3. Ensure 25cm plant spacing.")

    with rec2:
        st.markdown("### tip")
        with st.expander("🩺 Disease Information"):
            st.write("**Soft Rot:** Yellow leaf tips; mushy rhizomes.")
            st.write("**Bacterial Wilt:** Sudden green wilting; milky ooze.")
        with st.expander("🧪 Field Best Practices"):
            st.write("- Never plant ginger after Tomato or Peppers.")
            st.write("- Treat rhizomes with fungicide before planting.")
            st.write(f"- Historical LST: {res['lst']:.1f}°C.")
