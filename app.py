import streamlit as st
import ee
import folium
import base64
import os
import requests
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

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
<p style="margin:0; color:#D8F3DC;">INTEGRATED PEST & RAINFALL MONITORING DASHBOARD</p>
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
# GEOLOCATION LOGIC (User's Current Location)
# ============================================================
st.subheader("📍 Farm Location")

# Attempt to get GPS from browser
loc = get_geolocation()
if loc:
    curr_lat = loc['coords']['latitude']
    curr_lon = loc['coords']['longitude']
    # Update only if position changes significantly to avoid infinite reruns
    if abs(st.session_state.lat - curr_lat) > 0.0001:
        st.session_state.lat = curr_lat
        st.session_state.lon = curr_lon
        st.session_state.loc_label = "Device GPS Location"

c1, c2 = st.columns([2, 1])
with c1:
    st.success(f"✅ **Currently Tracking:** {st.session_state.loc_label}")
    st.caption(f"Coordinates: {st.session_state.lat:.4f}, {st.session_state.lon:.4f}")

with c2:
    with st.expander("⌨️ Optional: Manual Coordinates"):
        mlat = st.number_input("Latitude", value=st.session_state.lat, format="%.4f")
        mlon = st.number_input("Longitude", value=st.session_state.lon, format="%.4f")
        if st.button("Update Manually"):
            st.session_state.lat = mlat
            st.session_state.lon = mlon
            st.session_state.loc_label = "Manual Input"
            st.rerun()

# ============================================================
# ANALYSIS ENGINE
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

    # Annual Rainfall
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(f'{year}-01-01', f'{year}-12-31')
    annual_rain = rain_col.sum().clip(buffer).rename('annual_rain')

    # Monthly vulnerability data
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, 'month')
    m_rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().unmask(0)

    # Risk Score calculation
    slope_n = normalize_img(slope, buffer)
    rain_n = normalize_img(m_rain, buffer)
    vuln = slope_n.multiply(0.4).add(rain_n.multiply(0.6)).rename('vuln').clip(buffer)
    
    return vuln, annual_rain, buffer

# ============================================================
# CONTROLS & EXECUTION
# ============================================================
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
sel_month = st.selectbox("📅 Analysis Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])

if st.button("🚀 Run Risk Analysis", type="primary"):
    with st.spinner("⏳ Analyzing Environmental Data..."):
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

# ============================================================
# RESULTS & MAPPING
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # 1. Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Risk Score", f"{res['score']:.2f}")
    m2.metric("⚠️ Risk Level", res['risk'])
    m3.metric("📅 Targeted Month", res['month_name'])
    m4.metric("🌧️ Annual Rain", f"{res['avg_rain']:.0f} mm")

    # 2. Risk Level Map
    st.subheader("🗺️ Risk Level Map")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
    
    # Layers
    v_id = res['v_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']})
    folium.TileLayer(tiles=v_id['tile_fetcher'].url_format, attr='GEE', name='Risk (Vulnerability)', overlay=True).add_to(m)

    r_id = res['r_img'].getMapId({'min': 1500, 'max': 3500, 'palette': ['#f7fbff', '#084594']})
    folium.TileLayer(tiles=r_id['tile_fetcher'].url_format, attr='GEE', name='Rainfall Intensity', overlay=True, show=False).add_to(m)

    folium.LayerControl().add_to(m)

    # 3. High Contrast Legend
    legend_html = '''
     <div style="position: fixed; bottom: 50px; left: 50px; width: 210px; height: auto; 
     background-color: rgba(255, 255, 255, 0.95); border:2px solid #1B4332; z-index:9999; 
     font-size: 13px; color: #000000; padding: 12px; border-radius: 8px; 
     box-shadow: 3px 3px 10px rgba(0,0,0,0.2); font-family: sans-serif;">
     
     <b style="font-size: 15px; color: #1B4332; display: block; margin-bottom: 8px; border-bottom: 1px solid #1B4332;">Map Legend</b>
     
     <div style="margin-bottom: 8px;">
         <b style="color: #1B4332; display: block; margin-bottom: 5px;">Risk Vulnerability:</b>
         <div style="line-height: 18px;">
             <i style="background: #cc3232; width: 14px; height: 14px; float: left; margin-right: 8px; border:1px solid #000;"></i> <b>High Risk (Danger)</b><br>
             <i style="background: #e7b416; width: 14px; height: 14px; float: left; margin-right: 8px; border:1px solid #000;"></i> <b>Moderate Risk</b><br>
             <i style="background: #2dc937; width: 14px; height: 14px; float: left; margin-right: 8px; border:1px solid #000;"></i> <b>Low Risk (Safe)</b><br>
         </div>
     </div>
     
     <div style="margin-top: 10px;">
         <b style="color: #1B4332; display: block; margin-bottom: 5px;">Annual Rainfall:</b>
         <div style="line-height: 18px;">
             <i style="background: #084594; width: 14px; height: 14px; float: left; margin-right: 8px; border:1px solid #000;"></i> <b>Heavy Rain (>3k mm)</b><br>
             <i style="background: #f7fbff; width: 14px; height: 14px; float: left; margin-right: 8px; border:1px solid #000;"></i> <b>Low Rain (<1.5k mm)</b><br>
         </div>
     </div>
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    st_folium(m, width="100%", height=500, key="main_map")

    # 4. Comprehensive Recommendations
    st.markdown("---")
    st.subheader("📋 Comprehensive Ginger Farming Manual")
    
    rec_col1, rec_col2 = st.columns(2)
    with rec_col1:
        st.markdown(f"### 🛡️ Targeted Mitigation for {res['risk']} Risk")
        if res['risk'] == "HIGH":
            st.error("""
            **🚨 CRITICAL OUTBREAK ALERT:**
            * **Immediate Drainage:** Deepen V-shaped canals to 30cm. Ginger rhizomes rot within 48 hours of saturation.
            * **Biological Shield:** Apply *Trichoderma harzianum* to soil immediately.
            * **Sterilization:** Use separate footwear for infected areas to avoid spreading bacterial wilt.
            """)
        elif res['risk'] == "MODERATE":
            st.warning("""
            **⚠️ ENHANCED MONITORING:**
            * **Twice-Weekly Scouting:** Check lower stems for water-soaked lesions.
            * **Potash Application:** Boost cell wall strength with Potassium-rich fertilizer (0-0-60).
            * **Hilling-Up:** Increase soil height around stems to improve water runoff.
            """)
        else:
            st.success("""
            **✅ IDEAL CONDITIONS:**
            * **Mulching:** Maintain 5-10cm rice straw mulch to stabilize moisture.
            * **Composting:** Feed soil with vermicompost to boost plant immunity.
            * **Airflow:** Ensure 25-30cm spacing between plants for ventilation.
            """)

    with rec_col2:
        st.markdown("### 🌿 Advanced Agricultural Practices")
        with st.expander("🩺 Disease & Pest Identification"):
            st.write("**Bacterial Wilt:** Sudden green drooping; milky ooze in stem cross-section.")
            st.write("**Soft Rot:** Foul-smelling mushy rhizomes caused by poor drainage.")
            st.write("**Shoot Borer:** Holes in pseudostem with sawdust-like frass (poop).")
        
        with st.expander("🧪 Soil & Nutrient Management"):
            st.write("**pH Balance:** Target 5.5–6.5. Use Dolomite if soil is too acidic.")
            st.write("**Calcium:** High rain leaches calcium; add gypsum to prevent internal rhizome browning.")
            st.write("**Rotation:** Never plant ginger after Tomato, Eggplant, or Pepper.")

        with st.expander("📈 Yield & Quality Optimization"):
            st.write("**Shade:** 25-30% shade (under coconut/corn) can increase yield by cooling soil.")
            st.write("**Harvesting:** 5-7 months for fresh use; 8-10 months for seed or high-oil quality.")
            st.write("**Seed Treatment:** Soak rhizomes in fungicide solution for 30 mins before planting.")
