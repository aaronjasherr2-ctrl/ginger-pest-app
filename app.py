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
if "results"    not in st.session_state: st.session_state.results    = None  # Store results here

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
<h2 style="margin:0; color:white;">Ginger Pest Warning System</h2>
<p style="margin:0; color:#D8F3DC;">Agusipan 4H CLUB MONITORING DASHBOARD</p>
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
    st.warning(f"⚠️ Earth Engine unavailable ({e})")

# ============================================================
# HELPER FUNCTIONS (Location & Image Logic)
# ============================================================
def get_ip_location():
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        d = r.json()
        return float(d["latitude"]), float(d["longitude"]), f"{d.get('city','')}, {d.get('region','')}"
    except: return None

def safe_image(ee_img, name):
    return ee.Image(ee_img).rename(name).unmask(0)

def normalize_img(img, buffer):
    img = ee.Image(img).unmask(0)
    band = img.bandNames().get(0)
    stats = img.reduceRegion(reducer=ee.Reducer.minMax(), geometry=buffer, scale=100, maxPixels=1e9)
    mn = ee.Number(stats.get(ee.String(band).cat('_min')))
    mx = ee.Number(stats.get(ee.String(band).cat('_max')))
    rng = mx.subtract(mn).max(0.0001)
    return img.subtract(mn).divide(rng)

def build_vulnerability(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    year = 2023
    
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    twi = dem.focal_mean(3).add(1).log().divide(slope.add(1)).rename('twi')
    
    # Monthly processing logic...
    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, 'month')
    
    # Simple example logic for brevity in this fix:
    rain = safe_image(ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum(), 'rain')
    rain_n = normalize_img(rain, buffer)
    slope_n = normalize_img(slope, buffer)
    
    vuln = slope_n.multiply(0.4).add(rain_n.multiply(0.6)).rename('vuln').clip(buffer)
    return vuln, buffer

def render_fallback_map(lat, lon, score, risk):
    color = {'LOW': '#2dc937', 'MODERATE': '#e7b416', 'HIGH': '#cc3232'}[risk]
    m = folium.Map(location=[lat, lon], zoom_start=15)
    folium.Circle([lat, lon], radius=1000, color=color, fill=True, fill_opacity=0.3).add_to(m)
    return m

# ============================================================
# UI CONTROLS
# ============================================================
st.subheader("📍 Farm Location")
btn_col, info_col = st.columns([1, 3])

with btn_col:
    if st.button("📡 Auto-Detect Location"):
        res = get_ip_location()
        if res:
            st.session_state.lat, st.session_state.lon, st.session_state.loc_label = res
            st.rerun()

with info_col:
    st.info(f"📌 **{st.session_state.loc_label}** — Lat: `{st.session_state.lat:.4f}`, Lon: `{st.session_state.lon:.4f}`")

with st.expander("✏️ Enter Coordinates Manually"):
    mlat = st.number_input("Lat", value=st.session_state.lat, format="%.4f")
    mlon = st.number_input("Lon", value=st.session_state.lon, format="%.4f")
    if st.button("✅ Update Coordinates"):
        st.session_state.lat, st.session_state.lon = mlat, mlon
        st.session_state.loc_label = "Manual Entry"
        st.rerun()

month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
month = st.selectbox("📅 Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])

if st.button("🚀 Run Analysis", type="primary"):
    with st.spinner("⏳ Analyzing..."):
        try:
            vuln_img, buffer = build_vulnerability(st.session_state.lat, st.session_state.lon, month)
            stats = vuln_img.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
            score = float(stats.get('vuln') or 0.5)
            risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"
            
            # Store everything in session state
            st.session_state.results = {
                "score": score,
                "risk": risk,
                "month_name": month_names[month-1],
                "vuln_img": vuln_img  # Keep the image object
            }
        except Exception as e:
            st.error(f"Analysis failed: {e}")

# ============================================================
# DISPLAY RESULTS (Outside the button block)
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    c1, c2, c3 = st.columns(3)
    c1.metric("📊 Score", f"{res['score']:.2f}")
    c2.metric("⚠️ Risk", res['risk'])
    c3.metric("📅 Month", res['month_name'])

    st.subheader("🗺️ Vulnerability Map")
    
    try:
        vis = {'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']}
        map_id = res['vuln_img'].getMapId(vis)
        
        m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        tile_url = f"https://earthengine.googleapis.com/map/{map_id['mapid']}/{{z}}/{{x}}/{{y}}?token={map_id['token']}"
        
        folium.TileLayer(tiles=tile_url, attr='GEE', overlay=True, name='Vulnerability').add_to(m)
        st_folium(m, width=1000, height=500, key="map_stable")
    except Exception as e:
        st.warning("Visualizing fallback map...")
        m = render_fallback_map(st.session_state.lat, st.session_state.lon, res['score'], res['risk'])
        st_folium(m, width=1000, height=500)

    # Recommendations...
    if res['risk'] == "HIGH": st.error("🚨 High Risk: Apply fungicides.")
    elif res['risk'] == "MODERATE": st.warning("⚠️ Moderate Risk: Inspect plants.")
    else: st.success("✅ Low Risk: Normal monitoring.")
