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
            return base64.get_logo_base64(f.read()).decode() # Fixed pathing logic
    return None

# Simplified logo handler for reliability
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

def get_climate_metrics(roi):
    try:
        # LST: MODIS Terra Daily Land Surface Temperature
        lst_col = ee.ImageCollection("MODIS/061/MOD11A1").filterDate('2023-01-01', '2023-12-31').select('LST_Day_1km')
        lst_img = lst_col.mean().multiply(0.02).subtract(273.15)
        lst_val = lst_img.reduceRegion(ee.Reducer.mean(), roi, 1000).get('LST_Day_1km').getInfo()
        
        # Humidity: GLDAS Specific Humidity (kg/kg)
        hum_col = ee.ImageCollection("NASA/GLDAS/V021/NOAH/G025/T3H").filterDate('2023-01-01', '2023-06-01').select('SpecificHum_f_inst')
        hum_img = hum_col.mean()
        hum_val = hum_img.reduceRegion(ee.Reducer.mean(), roi, 1000).get('SpecificHum_f_inst').getInfo()
        
        return (lst_val or 0), (hum_val or 0) * 1000
    except:
        return 0, 0

def get_vulnerability_raster(roi_buffer, month_idx):
    dem = ee.Image('USGS/SRTMGL1_003').clip(roi_buffer)
    slope = ee.Terrain.slope(dem)
    # Filter CHIRPS Rainfall
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')\
             .filter(ee.Filter.calendarRange(month_idx, month_idx, 'month'))\
             .filterDate('2020-01-01', '2024-01-01').mean().clip(roi_buffer)

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
    sel_month = st.selectbox("📅 Select Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    
    test_btn = st.button("🔍 TEST VULNERABILITY", type="primary", use_container_width=True)

# ============================================================
# EXECUTION
# ============================================================
if test_btn:
    with st.spinner("Analyzing parameters..."):
        try:
            roi = ee.Geometry.Point([st.session_state.lon, st.session_state.lat])
            zone_1km = roi.buffer(1000)
            
            vuln_img = get_vulnerability_raster(zone_1km, sel_month)
            score = vuln_img.reduceRegion(ee.Reducer.mean(), zone_1km, 30).get('vulnerability').getInfo()
            
            lst_val, hum_val = get_climate_metrics(roi)
            
            trend = []
            for m in range(1, 13):
                m_img = get_vulnerability_raster(zone_1km, m)
                m_score = m_img.reduceRegion(ee.Reducer.mean(), zone_1km, 30).get('vulnerability').getInfo()
                trend.append(m_score or 0)

            st.session_state.results = {
                "score": score or 0,
                "trend": trend,
                "vuln_img": vuln_img,
                "lst": lst_val,
                "hum": hum_val,
                "risk": "HIGH" if (score or 0) > 0.55 else "MODERATE" if (score or 0) > 0.35 else "LOW",
                "month": month_names[sel_month-1]
            }
        except Exception as e:
            st.error(f"Analysis Error: {e}")

# ============================================================
# MAIN DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # 1. Metrics Dashboard
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Vulnerability", f"{res['score']:.2f}")
    m2.metric("LST (Temp)", f"{res['lst']:.1f}°C")
    m3.metric("Humidity Index", f"{res['hum']:.1f}")
    m4.metric("Risk Level", res['risk'])

    st.write("### 📈 Annual Vulnerability Trend")
    df = pd.DataFrame(res['trend'], index=month_names, columns=['Risk Score'])
    st.line_chart(df, color="#1B4332")

    # 2. Raster Map (1km Zone)
    st.markdown("---")
    st.subheader("🎯 1km Radius Vulnerability Raster")
    
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
    map_id = res['vuln_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['#2dc937', '#e7b416', '#cc3232']})
    folium.TileLayer(tiles=map_id['tile_fetcher'].url_format, attr='GEE', name="Vulnerability").add_to(m)
    
    # Legend with Black High-Contrast Text
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

    # 3. Recommendations & Tips
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
        with st.expander("🩺 Disease Identification Guide"):
            st.write("**Soft Rot:** Mushy rhizomes, yellow leaf tips.")
            st.write("**Bacterial Wilt:** Green leaves wilting suddenly with milky ooze.")
        with st.expander("🧪 Best Field Practices"):
            st.write("- Avoid following Tomatoes/Peppers.")
            st.write("- Treat rhizomes with fungicide before planting.")
            st.write(f"- Note: Current Avg LST is {res['lst']:.1f}°C.")
