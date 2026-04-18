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
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
if "lat" not in st.session_state: st.session_state.lat = 10.9300
if "lon" not in st.session_state: st.session_state.lon = 122.5200
if "results" not in st.session_state: st.session_state.results = None 

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
# ANALYSIS ENGINE
# ============================================================
def normalize_img(img, region):
    img = ee.Image(img).unmask(0)
    band = img.bandNames().get(0)
    stats = img.reduceRegion(reducer=ee.Reducer.minMax(), geometry=region, scale=100)
    mn = ee.Number(stats.get(ee.String(band).cat('_min')))
    mx = ee.Number(stats.get(ee.String(band).cat('_max')))
    return img.subtract(mn).divide(mx.subtract(mn).max(0.0001))

def get_rainfall_series(roi):
    # Fetching 2023 monthly rainfall data for the graph
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31')
    months = range(1, 13)
    monthly_data = []
    for m in months:
        m_sum = rain_col.filter(ee.Filter.calendarRange(m, m, 'month')).sum()
        stats = m_sum.reduceRegion(ee.Reducer.mean(), roi, 100).getInfo()
        monthly_data.append(stats.get('precipitation', 0))
    return monthly_data

# ============================================================
# MAIN UI
# ============================================================
st.title("🌱 Agusipan Ginger Warning System")

col_a, col_b = st.columns([1, 2])
with col_a:
    st.subheader("📍 Location Settings")
    loc = get_geolocation()
    if loc:
        st.session_state.lat = loc['coords']['latitude']
        st.session_state.lon = loc['coords']['longitude']
    
    st.write(f"**Lat:** {st.session_state.lat:.4f} | **Lon:** {st.session_state.lon:.4f}")
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = st.selectbox("📅 Analysis Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    
    run_btn = st.button("🚀 Run Risk Analysis", type="primary", use_container_width=True)

if run_btn:
    with st.spinner("⏳ Crunching Satellite Data..."):
        roi = ee.Geometry.Point([st.session_state.lon, st.session_state.lat])
        zone_1km = roi.buffer(1000)
        zone_5km = roi.buffer(5000)
        
        # Rainfall & Terrain
        rain_img = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate('2023-01-01', '2023-12-31').sum().clip(zone_5km)
        slope = ee.Terrain.slope(ee.Image('USGS/SRTMGL1_003')).clip(zone_5km)
        
        # Monthly Calc
        m_start = ee.Date.fromYMD(2023, sel_month, 1)
        m_rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(m_start, m_start.advance(1, 'month')).sum()
        
        # Scoring
        vuln = normalize_img(slope, zone_5km).multiply(0.4).add(normalize_img(m_rain, zone_5km).multiply(0.6))
        score = vuln.reduceRegion(ee.Reducer.mean(), zone_1km, 100).getInfo().get('slope', 0.5)
        
        risk_level = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"
        
        st.session_state.results = {
            "score": score, "risk": risk_level, "rain_series": get_rainfall_series(roi),
            "v_img": vuln, "r_img": rain_img, "zone_1km": zone_1km, "month": month_names[sel_month-1]
        }

# ============================================================
# RESULTS DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # 1. Dashboard Metrics & Graph
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("Risk Score", f"{res['score']:.2f}", delta=res['risk'], delta_color="inverse" if res['risk']=="HIGH" else "normal")
        st.info(f"**Status:** {res['risk']} risk detected for {res['month']}.")
        
    with c2:
        st.write("### 📈 2023 Rainfall Trend (mm)")
        chart_data = pd.DataFrame(res['rain_series'], index=month_names, columns=['Rainfall'])
        st.line_chart(chart_data)

    # 2. Dual Map System
    st.markdown("---")
    m_col1, m_col2 = st.columns(2)
    
    with m_col1:
        st.subheader("🗺️ Regional Vulnerability (5km)")
        m1 = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=13)
        v_id = res['v_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']})
        folium.TileLayer(tiles=v_id['tile_fetcher'].url_format, attr='GEE', name='Risk').add_to(m1)
        st_folium(m1, width="100%", height=400, key="map_reg")

    with m_col2:
        st.subheader("🎯 Local 1km Risk Zone")
        m2 = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        # Highlight the 1km Zone
        folium.GeoJson(res['zone_1km'].getInfo(), style_function=lambda x: {'color': '#1B4332', 'fillColor': '#1B4332', 'fillOpacity': 0.1}).add_to(m2)
        folium.Marker([st.session_state.lat, st.session_state.lon], popup="Your Farm").add_to(m2)
        st_folium(m2, width="100%", height=400, key="map_local")

    # 3. Dynamic Manual aligned with Result Analysis
    st.markdown("---")
    st.subheader(f"📋 Tailored Farming Manual for {res['risk']} Risk Environment")
    
    man_col1, man_col2 = st.columns(2)
    with man_col1:
        if res['risk'] == "HIGH":
            st.error("### 🚨 Urgent Action Plan")
            st.write("- **Drainage:** Evacuate standing water. Create 30cm deep trenches.")
            st.write("- **Disease Control:** Spray Copper-based fungicides immediately.")
            st.write("- **Access:** Restrict movement in the 1km zone to prevent soil-borne pathogen spread.")
        elif res['risk'] == "MODERATE":
            st.warning("### ⚠️ Preventative Measures")
            st.write("- **Soil:** Apply Lime/Dolomite to stabilize pH during heavy rains.")
            st.write("- **Pruning:** Remove yellowing leaves to improve airflow.")
            st.write("- **Nutrition:** Increase Potash (K) to strengthen rhizome skin.")
        else:
            st.success("### ✅ Optimization Strategy")
            st.write("- **Mulching:** Use rice straw to keep soil cool and moist.")
            st.write("- **Planning:** Ideal time for organic fertilization and weeding.")
            st.write("- **Storage:** Ensure seed rhizomes are kept in a dry, ventilated area.")

    with man_col2:
        st.info("### 🔍 Technical Observation")
        st.write(f"The analysis for **{res['month']}** suggests a vulnerability score of **{res['score']:.2f}**.")
        st.write("This is calculated based on the 1km buffer slope and historical rainfall intensity.")
        st.caption("Data source: CHIRPS Daily Rainfall & SRTM Digital Elevation Model.")
