import streamlit as st
import ee
import folium
import base64
import os
import requests
from streamlit_folium import st_folium

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================
if "lat"        not in st.session_state: st.session_state.lat        = 10.9300
if "lon"        not in st.session_state: st.session_state.lon        = 122.5200
if "loc_label"  not in st.session_state: st.session_state.loc_label  = "Default location"
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
# HELPER FUNCTIONS
# ============================================================
def get_ip_location():
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        d = r.json()
        return float(d["latitude"]), float(d["longitude"]), f"{d.get('city','')}, {d.get('region','')}"
    except: return None

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

    # 1. ANNUAL RAINFALL
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(f'{year}-01-01', f'{year}-12-31')
    annual_rain = rain_col.sum().clip(buffer).rename('annual_rain')

    # 2. VULNERABILITY
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, 'month')
    month_rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().unmask(0)

    # Weights
    slope_n = normalize_img(slope, buffer)
    rain_n = normalize_img(month_rain, buffer)
    vuln = slope_n.multiply(0.4).add(rain_n.multiply(0.6)).rename('vuln').clip(buffer)
    
    return vuln, annual_rain, buffer

# ============================================================
# UI CONTROLS
# ============================================================
st.subheader("📍 Location & Time Selection")
c1, c2 = st.columns([1, 2])

with c1:
    if st.button("📡 Auto-Detect My Location"):
        res = get_ip_location()
        if res:
            st.session_state.lat, st.session_state.lon, st.session_state.loc_label = res
            st.rerun()

with c2:
    st.info(f"Current Target: **{st.session_state.loc_label}**")

with st.expander("⚙️ Manual Adjustments"):
    mc1, mc2, mc3 = st.columns(3)
    mlat = mc1.number_input("Lat", value=st.session_state.lat, format="%.4f")
    mlon = mc2.number_input("Lon", value=st.session_state.lon, format="%.4f")
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = mc3.selectbox("Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    if st.button("Apply Changes"):
        st.session_state.lat, st.session_state.lon = mlat, mlon
        st.session_state.loc_label = "Manual Target"
        st.rerun()

if st.button("🚀 Run Analysis", type="primary"):
    with st.spinner("⏳ Processing Satellite Imagery..."):
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
# RESULTS DISPLAY
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Risk Score", f"{res['score']:.2f}")
    m2.metric("⚠️ Risk Level", res['risk'])
    m3.metric("📅 Month", res['month_name'])
    m4.metric("🌧️ Annual Rain", f"{res['avg_rain']:.0f} mm")

    # MAP SECTION
    st.subheader("🗺️ Risk Level Map")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
    
    # Add Raster Layers
    v_id = res['v_img'].getMapId({'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']})
    folium.TileLayer(tiles=v_id['tile_fetcher'].url_format, attr='GEE', name='Risk Level (Vulnerability)', overlay=True).add_to(m)

    r_id = res['r_img'].getMapId({'min': 1500, 'max': 3500, 'palette': ['#f7fbff', '#084594']})
    folium.TileLayer(tiles=r_id['tile_fetcher'].url_format, attr='GEE', name='Annual Rain Map', overlay=True, show=False).add_to(m)

    folium.LayerControl().add_to(m)

    # ADD CUSTOM LEGEND (HTML)
    legend_html = '''
     <div style="position: fixed; bottom: 50px; left: 50px; width: 190px; height: 180px; 
     background-color: white; border:2px solid grey; z-index:9999; font-size:12px;
     padding: 10px; border-radius: 5px;">
     <b>Map Legend</b><br>
     <div style="margin-top: 5px;"><b>Risk Vulnerability:</b></div>
     <i style="background: #cc3232; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> High Risk (Danger)<br>
     <i style="background: #e7b416; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Moderate Risk<br>
     <i style="background: #2dc937; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Low Risk (Safe)<br>
     <hr style="margin: 5px 0;">
     <div style="margin-top: 5px;"><b>Annual Rainfall:</b></div>
     <i style="background: #084594; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Heavy Rain (>3000mm)<br>
     <i style="background: #f7fbff; width: 12px; height: 12px; float: left; margin-right: 5px; border:1px solid #999"></i> Low Rain (<1500mm)
     </div>
     '''
    m.get_root().html.add_child(folium.Element(legend_html))
    st_folium(m, width="100%", height=500, key="main_map")

    # ============================================================
    # EXPANDED MANUAL RECOMMENDATIONS
    # ============================================================
    st.markdown("---")
    st.subheader("📋 Comprehensive Ginger Farming Manual")
    
    rec_col1, rec_col2 = st.columns(2)

    with rec_col1:
        st.markdown(f"### 🛡️ Targeted Mitigation for {res['risk']} Risk")
        if res['risk'] == "HIGH":
            st.error("""
            **🚨 CRITICAL OUTBREAK ALERT:**
            * **Immediate Drainage Construction:** Create "V-shaped" drainage canals every 2 meters. Stagnant water for even 24 hours can trigger irreversible Bacterial Wilt.
            * **Sanitary Harvesting:** If signs of rot appear, use separate tools for healthy vs. infected areas to prevent cross-contamination.
            * **Biological Protection:** Incorporate *Trichoderma* microbial inoculants into the soil to fight soil-borne pathogens.
            * **Early Harvest:** If rhizomes are near maturity, consider early harvesting to save the crop from rot.
            """)
        elif res['risk'] == "MODERATE":
            st.warning("""
            **⚠️ ENHANCED MONITORING:**
            * **Bi-Weekly Scouting:** Inspect the "collar" region (where the stem meets the soil) for water-soaked spots.
            * **Soil Amendment:** Apply potash-rich fertilizer (0-0-60) to strengthen the cell walls of the rhizomes against infection.
            * **Hill-Up Technique:** Increase the height of your plant rows to ensure rhizomes stay above the saturation line during heavy afternoon rains.
            """)
        else:
            st.success("""
            **✅ IDEAL CONDITIONS:**
            * **Mulch Maintenance:** Maintain a 5cm thick layer of organic mulch (rice straw) to prevent soil splash-back, which carries fungal spores.
            * **Organic Fertilization:** Apply well-decomposed chicken manure or vermicompost to build long-term plant resilience.
            * **Water Management:** Monitor for dry spells; ensure soil stays damp but never muddy.
            """)

    with rec_col2:
        st.markdown("### 🌿 Advanced Agricultural Practices")
        with st.expander("🩺 Pest & Disease Identification"):
            st.write("**Bacterial Wilt:** Look for sudden drooping of leaves while they are still green. A cut stem placed in water will show 'milky ooze'.")
            st.write("**Soft Rot:** Rhizomes become mushy and emit a foul odor. Usually caused by poor drainage during the monsoon.")
            st.write("**Shoot Borer:** Watch for holes in the stems and extrusion of frass (sawdust-like material).")
        
        with st.expander("🧪 Soil & Nutrient Optimization"):
            st.write("**pH Balance:** Ginger prefers 5.5 to 6.5 pH. Use dolomite if your soil is too acidic (common in high-rain areas).")
            st.write("**Rhizome Growth:** Ensure high Phosphorus (P) at planting and high Potassium (K) during the 4th to 6th months.")
            st.write("**Organic Matter:** Target 3% organic matter in soil to improve aeration and drainage.")

        with st.expander("🚜 Cultural Management & Rotation"):
            st.write("**Intercropping:** Planting ginger under light shade (like coconut or banana) can reduce heat stress, but requires better air circulation.")
            st.write("**Crop Rotation:** NEVER plant ginger after Solanaceous crops (Tomato, Eggplant, Potato) as they share the same wilt diseases.")
            st.write("**Seed Treatment:** Soak 'seeds' (rhizomes) in a fungicide solution for 30 minutes before planting to ensure a clean start.")
            
        with st.expander("🌦️ Weather Resilience"):
            st.write("**Extreme Rain:** In 'High Rain' blue zones, prioritize planting on steeper slopes where water runoff is naturally faster.")
            st.write("**Drought:** Use drip irrigation if possible, as overhead sprinklers can spread fungal spores from the soil to the leaves.")
