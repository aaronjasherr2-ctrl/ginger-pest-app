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
# RESEARCH-BASED ANALYSIS FUNCTIONS
# ============================================================

@st.cache_data(ttl=3600)
def analyze_high_precision(lat, lon, sel_month):
    roi = ee.Geometry.Point([lon, lat])
    zone_500m = roi.buffer(500)
    
    # 1. Vegetation Health & Moisture (Sentinel-2 10m)
    # Research: Low NDVI + High NDWI = High Risk of Waterborne Pathogens
    s2_col = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
        .filterBounds(zone_500m) \
        .filter(ee.Filter.calendarRange(sel_month, sel_month, 'month')) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
        .median()

    ndvi = s2_col.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndwi = s2_col.normalizedDifference(['B3', 'B8']).rename('NDWI')
    
    # 2. Topography (Drainage Risk)
    dem = ee.Image('USGS/SRTMGL1_003').clip(zone_500m)
    slope = ee.Terrain.slope(dem)
    
    # 3. LST (Temperature Suitability)
    lst_col = ee.ImageCollection("MODIS/061/MOD11A1") \
        .filter(ee.Filter.calendarRange(sel_month, sel_month, 'month')) \
        .select('LST_Day_1km')
    lst_img = lst_col.mean().multiply(0.02).subtract(273.15)
    lst_val = lst_img.reduceRegion(ee.Reducer.mean(), zone_500m, 30).get('LST_Day_1km').getInfo() or 0
    
    # 4. Risk Algorithm: Based on Pest Susceptibility Research
    # Risk = (Moisture Weight) + (Slope Weight) + (Temp Weight)
    # We invert NDVI (1-NDVI) because lower vegetation health = higher pest risk
    risk_raster = ndwi.multiply(0.4) \
        .add(slope.divide(45).multiply(-0.2)) \
        .add(ee.Image(1).subtract(ndvi).multiply(0.4)) \
        .rename('risk_score')

    score_val = risk_raster.reduceRegion(ee.Reducer.mean(), zone_500m, 10).get('risk_score').getInfo() or 0
    
    # Generate monthly trend based on Precipitation and LST patterns
    rain_col = ee.ImageCollection("UCSB-CHG/CHIRPS/PENTAD")
    trend = []
    for m in range(1, 13):
        m_rain = rain_col.filter(ee.Filter.calendarRange(m, m, 'month')).mean()
        m_rain_val = m_rain.reduceRegion(ee.Reducer.mean(), zone_500m, 30).get('precipitation').getInfo() or 0
        # Research indicates Rain > 200mm increases pest pressure significantly
        m_score = (m_rain_val / 400 * 0.7) + (0.3 if 24 < lst_val < 30 else 0.1)
        trend.append(min(m_score, 1.0))

    return {
        "score": score_val,
        "trend": trend,
        "vuln_img": risk_raster,
        "lst": lst_val,
        "hum": (score_val * 100), # Proxy for soil saturation %
        "risk": "HIGH" if score_val > 0.6 else "MODERATE" if score_val > 0.3 else "LOW",
        "zone": zone_500m
    }

# ============================================================
# SIDEBAR / INPUTS
# ============================================================
with st.sidebar:
    st.header("📍 Location Setup")
    
    loc = get_geolocation()
    if loc:
        st.session_state.lat = loc['coords']['latitude']
        st.session_state.lon = loc['coords']['longitude']
        st.success(f"Location Captured")
    else:
        st.info("Waiting for GPS...")

    st.markdown("---")
    
    with st.expander("⌨️ Manual Entry"):
        mlat = st.number_input("Latitude", value=st.session_state.lat, format="%.8f")
        mlon = st.number_input("Longitude", value=st.session_state.lon, format="%.8f")
        if st.button("Set Manual Coordinates", use_container_width=True):
            st.session_state.lat = mlat
            st.session_state.lon = mlon

    st.markdown("---")
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = st.selectbox("📅 Analysis Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    test_btn = st.button("🔍 ANALYZE RISK", type="primary", use_container_width=True)

# ============================================================
# EXECUTION
# ============================================================
if test_btn:
    with st.spinner("Calculating Research-Based Risk Indices..."):
        try:
            results = analyze_high_precision(st.session_state.lat, st.session_state.lon, sel_month)
            results["month"] = month_names[sel_month-1]
            st.session_state.results = results
        except Exception as e:
            st.error(f"Analysis Error: {e}")

# ============================================================
# MAIN DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    st.info(f"Methodology: S-2 NDVI/NDWI Fusion & SRTM Topography | Lat: {st.session_state.lat:.5f}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Risk Index", f"{res['score']:.3f}")
    m2.metric("Avg LST", f"{res['lst']:.1f}°C")
    m3.metric("Saturation Index", f"{res['hum']:.1f}%")
    m4.metric("Status", res['risk'])

    st.write(f"### 📈 Research-Based Annual Pest Pressure")
    df = pd.DataFrame(res['trend'], index=month_names, columns=['Risk Score'])
    st.line_chart(df, color="#1B4332")

    st.markdown("---")
    st.subheader("🎯 SPATIAL RISK MAP (SENTINEL-2 10M)")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=17) 
    
    map_id = res['vuln_img'].getMapId({'min': 0, 'max': 0.7, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
    folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='GEE', name="Pest Risk").add_to(m)
    
    folium.GeoJson(res['zone'].getInfo(), style_function=lambda x: {'color': '#1B4332', 'fillOpacity': 0.05, 'weight': 1}).add_to(m)

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
        st.markdown(f"### Immediate Action Plan ({res['risk']})")
        if res['risk'] == "HIGH":
            st.error("1. Immediate Field Drainage: Ensure no standing water. \n2. Biocontrol: Drench with Bacillus subtilis. \n3. Quarantine: Stop movement of tools between blocks.")
        elif res['risk'] == "MODERATE":
            st.warning("1. Monitor: Check for early yellowing of lower leaves. \n2. Nutrition: Apply Potassium-heavy fertilizer to strengthen cell walls. \n3. Sanitation: Clean all tools with bleach solution.")
        else:
            st.success("1. Preventative: Maintain mulch cover. \n2. Monitoring: Standard weekly scouting. \n3. Soil: Continue regular organic matter incorporation.")

    with rec2:
        st.markdown("### Research Context")
        with st.expander("🩺 Biological Indicators"):
            st.write("Current analysis uses Sentinel-2 Multi-spectral data. Low NDVI values in high-moisture zones are strong indicators of root-zone stress often caused by fungal/bacterial pathogens.")
        with st.expander("🧪 Soil & Climate Connection"):
            st.write(f"- Critical Temperature Range: 25-30°C.")
            st.write(f"- Saturation Risk: {res['hum']:.1f}%. High saturation limits oxygen and promotes bacterial wilt.")
