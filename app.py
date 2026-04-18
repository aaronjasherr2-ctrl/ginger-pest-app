import streamlit as st
import ee
import folium
import base64
import os
import requests
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation # New component for browser GPS

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Agusipan Ginger Warning System")

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
if "lat"        not in st.session_state: st.session_state.lat        = 10.9300
if "lon"        not in st.session_state: st.session_state.lon        = 122.5200
if "loc_label"  not in st.session_state: st.session_state.loc_label  = "Default (Agusipan)"
if "results"    not in st.session_state: st.session_state.results    = None 

# ============================================================
# LOGO & HEADER
# ============================================================
def get_logo_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo = get_logo_base64("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo}" width="80">' if logo else "🌱"

st.markdown(f"""
<div style="display:flex; align-items:center; gap:15px; background:#1B4332; padding:15px; border-radius:15px; margin-bottom:20px;">
{logo_html}
<div>
<h2 style="margin:0; color:white;">Agusipan Ginger Warning System</h2>
<p style="margin:0; color:#D8F3DC;">INTEGRATED PEST & RAINFALL MONITORING</p>
</div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# EARTH ENGINE INIT
# ============================================================
EE_AVAILABLE = False
try:
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ee.ServiceAccountCredentials(info["client_email"], key_data=info["private_key"])
        ee.Initialize(creds, project=info["project_id"])
    else:
        ee.Initialize()
    EE_AVAILABLE = True
except Exception as e:
    st.error(f"❌ Connection Error: {e}")

# ============================================================
# GEOLOCATION LOGIC
# ============================================================
st.subheader("📍 Farm Location")

# 1. Automatic Browser GPS (Highest Priority)
loc = get_geolocation()
if loc:
    curr_lat = loc['coords']['latitude']
    curr_lon = loc['coords']['longitude']
    # Update state only if it significantly changes to prevent infinite loops
    if round(st.session_state.lat, 4) != round(curr_lat, 4):
        st.session_state.lat = curr_lat
        st.session_state.lon = curr_lon
        st.session_state.loc_label = "Device GPS Location"

# 2. UI Display & Optional Manual Overrides
c1, c2 = st.columns([2, 1])
with c1:
    st.success(f"✅ **Currently Tracking:** {st.session_state.loc_label}")
    st.caption(f"Coordinates: {st.session_state.lat:.4f}, {st.session_state.lon:.4f}")

with c2:
    with st.expander("⌨️ Edit Coordinates Manually"):
        mlat = st.number_input("Latitude", value=st.session_state.lat, format="%.4f")
        mlon = st.number_input("Longitude", value=st.session_state.lon, format="%.4f")
        if st.button("Update Manually"):
            st.session_state.lat = mlat
            st.session_state.lon = mlon
            st.session_state.loc_label = "Manual Input"
            st.rerun()

# ============================================================
# CORE ANALYSIS ENGINE
# ============================================================
def normalize_img(img, buffer):
    img = ee.Image(img).unmask(0)
    band = img.bandNames().get(0)
    stats = img.reduceRegion(reducer=ee.Reducer.minMax(), geometry=buffer, scale=100, maxPixels=1e9)
    mn = ee.Number(stats.get(ee.String(band).cat('_min')))
    mx = ee.Number(stats.get(ee.String(band).cat('_max')))
    rng = mx.subtract(mn).max(0.0001)
    return img.subtract(mn).divide(rng)

def build_analysis(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(2000)
    year = 2023 

    # Rainfall
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(f'{year}-01-01', f'{year}-12-31')
    annual_rain = rain_col.sum().clip(buffer).rename('annual_rain')

    # Vulnerability (Slope + Monthly Rain)
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, 'month')
    m_rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().unmask(0)

    slope_n = normalize_img(slope, buffer)
    rain_n = normalize_img(m_rain, buffer)
    vuln = slope_n.multiply(0.4).add(rain_n.multiply(0.6)).rename('vuln').clip(buffer)
    
    return vuln, annual_rain, buffer

# ============================================================
# RUN BUTTON & RESULTS
# ============================================================
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
sel_month = st.selectbox("Select Planting/Analysis Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])

if st.button("🚀 Run Risk Analysis", type="primary"):
    with st.spinner("⏳ Analyzing Satellite Data..."):
        try:
            v_img, r_img, buffer = build_analysis(st.session_state.lat, st.session_state.lon, sel_month)
            v_stats = v_img.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
            r_stats = r_img.reduceRegion(ee.Reducer.mean(), buffer.centroid(), 100).getInfo()
            
            score = float(v_stats.get('vuln') or 0.5)
            rain_val = float(r_stats.get('annual_rain') or 0.0)
            risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"
            
            st.session_state.results = {
                "score": score, "risk": risk, "avg_rain": rain_val,
                "month_name": month_names[sel_month-1], "v_img": v_img, "r_img": r_img
            }
        except Exception as e:
            st.error(f"Analysis failed: {e}")

if st.session_state.results:
    res = st.session_state.results
    
    # 1. METRICS
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Risk Score", f"{res['score']:.2f}")
    m2.metric("⚠️ Risk Level", res['risk'])
    m3.metric("📅 Analysis Month", res['month_name'])
    m4.metric("🌧️ Annual Rain", f"{res['avg_rain']:.0f} mm")

    # 2. RISK LEVEL MAP
    st.subheader("🗺️ Risk Level Map")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
    
    v_id = res['v_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']})
    folium.TileLayer(tiles=v_id['tile_fetcher'].url_format, attr='GEE', name='Risk Level', overlay=True).add_to(m)

    r_id = res['r_img'].getMapId({'min': 1500, 'max': 3500, 'palette': ['#f7fbff', '#084594']})
    folium.TileLayer(tiles=r_id['tile_fetcher'].url_format, attr='GEE', name='Rainfall Map', overlay=True, show=False).add_to(m)

    folium.LayerControl().add_to(m)

    legend_html = '''
     <div style="position: fixed; bottom: 50px; left: 50px; width: 190px; height: 180px; 
     background-color: white; border:2px solid grey; z-index:9999; font-size:12px;
     padding: 10px; border-radius: 5px;">
     <b>Map Legend</b><br>
     <div style="margin-top: 5px;"><b>Risk Vulnerability:</b></div>
     <i style="background: #cc3232; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> High Risk<br>
     <i style="background: #e7b416; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Moderate Risk<br>
     <i style="background: #2dc937; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Low Risk<br>
     <hr style="margin: 5px 0;">
     <div style="margin-top: 5px;"><b>Annual Rainfall:</b></div>
     <i style="background: #084594; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Heavy Rain<br>
     <i style="background: #f7fbff; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Low Rain
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    st_folium(m, width="100%", height=500, key="main_map")

    # 3. MANUAL RECOMMENDATIONS
    st.markdown("---")
    st.subheader("📋 Comprehensive Ginger Farming Manual")
    
    rec_col1, rec_col2 = st.columns(2)
    with rec_col1:
        st.markdown(f"### 🛡️ Targeted Mitigation for {res['risk']} Risk")
        if res['risk'] == "HIGH":
            st.error("🚨 **CRITICAL:** Immediate drainage 'V-canals' required. Apply *Trichoderma* inoculants and monitor for 'milky ooze' in stems (Bacterial Wilt indicator).")
        elif res['risk'] == "MODERATE":
            st.warning("⚠️ **CAUTION:** Bi-weekly scouting for water-soaked lesions. Apply potash-rich fertilizer to strengthen rhizome cell walls.")
        else:
            st.success("✅ **SAFE:** Maintain rice straw mulch (5cm) to prevent soil splash and stabilize moisture.")

    with rec_col2:
        st.markdown("### 🌿 Advanced Agricultural Practices")
        with st.expander("🩺 Pest & Disease Identification"):
            st.write("- **Soft Rot:** Mushy rhizomes with foul odor. Caused by waterlogging.")
            st.write("- **Shoot Borer:** Holes in stems with sawdust-like frass.")
        with st.expander("🧪 Soil & Nutrient Optimization"):
            st.write("- **pH:** Ginger needs 5.5-6.5. Use dolomite if soil is too acidic.")
            st.write("- **Rotation:** Avoid planting after Tomatoes or Eggplants.")
