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
    st.error(f"❌ Earth Engine Authentication Failed: {e}")

# ============================================================
# HELPER FUNCTIONS
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

def build_analysis(lat, lon, month):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1500) # Slightly larger buffer for context
    year = 2023 

    # 1. ANNUAL RAINFALL (CHIRPS)
    rain_col = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(f'{year}-01-01', f'{year}-12-31')
    annual_rain = rain_col.sum().clip(buffer).rename('annual_rain')

    # 2. VULNERABILITY COMPONENTS
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    twi = dem.focal_mean(3).add(1).log().divide(slope.add(1)).rename('twi')
    
    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, 'month')
    month_rain = safe_image(ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum(), 'm_rain')

    # Normalize for score
    slope_n = normalize_img(slope, buffer)
    twi_n = normalize_img(twi, buffer)
    rain_n = normalize_img(month_rain, buffer)

    # Weights: Slope 30%, TWI 30%, Monthly Rain 40%
    vuln = slope_n.multiply(0.3).add(twi_n.multiply(0.3)).add(rain_n.multiply(0.4)).rename('vuln').clip(buffer)
    
    return vuln, annual_rain, buffer

# ============================================================
# UI CONTROLS
# ============================================================
st.subheader("📍 Farm Location & Parameters")
btn_col, info_col = st.columns([1, 3])

with btn_col:
    if st.button("📡 Auto-Detect Location"):
        res = get_ip_location()
        if res:
            st.session_state.lat, st.session_state.lon, st.session_state.loc_label = res
            st.rerun()

with info_col:
    st.info(f"📌 **{st.session_state.loc_label}** — Lat: `{st.session_state.lat:.4f}`, Lon: `{st.session_state.lon:.4f}`")

with st.expander("✏️ Manual Coordinates & Settings"):
    c1, c2, c3 = st.columns(3)
    mlat = c1.number_input("Latitude", value=st.session_state.lat, format="%.4f")
    mlon = c2.number_input("Longitude", value=st.session_state.lon, format="%.4f")
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    sel_month = c3.selectbox("Analysis Month", range(1, 13), index=4, format_func=lambda x: month_names[x-1])
    
    if st.button("✅ Update & Save Settings"):
        st.session_state.lat, st.session_state.lon = mlat, mlon
        st.session_state.loc_label = "Custom Entry"
        st.rerun()

if st.button("🚀 Run Full Analysis", type="primary"):
    if not EE_AVAILABLE:
        st.error("Cannot run analysis: Earth Engine is not connected.")
    else:
        with st.spinner("⏳ Fetching Satellite Data..."):
            try:
                vuln_img, rain_img, buffer = build_analysis(st.session_state.lat, st.session_state.lon, sel_month)
                
                # Extract numeric stats
                v_stats = vuln_img.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
                r_stats = rain_img.reduceRegion(ee.Reducer.mean(), buffer.centroid(), 100).getInfo()
                
                score = float(v_stats.get('vuln') or 0.5)
                rain_val = float(r_stats.get('annual_rain') or 0.0)
                risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"
                
                st.session_state.results = {
                    "score": score,
                    "risk": risk,
                    "avg_rain": rain_val,
                    "month_name": month_names[sel_month-1],
                    "vuln_img": vuln_img,
                    "rain_img": rain_img
                }
            except Exception as e:
                st.error(f"Analysis failed: {e}")

# ============================================================
# DISPLAY RESULTS
# ============================================================
if st.session_state.results:
    res = st.session_state.results
    
    # 1. METRICS
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Vulnerability Score", f"{res['score']:.2f}")
    m2.metric("⚠️ Risk Level", res['risk'])
    m3.metric("📅 Targeted Month", res['month_name'])
    m4.metric("🌧️ Avg Annual Rain", f"{res['avg_rain']:.0f} mm")

    # 2. MAP
    st.subheader("🗺️ Interactive Raster Layers")
    try:
        m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
        
        # Layer 1: Vulnerability
        vis_v = {'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']}
        v_id = res['vuln_img'].getMapId(vis_v)
        folium.TileLayer(
            tiles=v_id['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            name='Pest Vulnerability',
            overlay=True,
            opacity=0.7
        ).add_to(m)

        # Layer 2: Rainfall
        vis_r = {'min': 1500, 'max': 3500, 'palette': ['#f7fbff', '#9ecae1', '#084594']}
        r_id = res['rain_img'].getMapId(vis_r)
        folium.TileLayer(
            tiles=r_id['tile_fetcher'].url_format,
            attr='Google Earth Engine',
            name='Annual Rainfall Intensity',
            overlay=True,
            show=False, # Off by default
            opacity=0.6
        ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width="100%", height=550, key="ginger_map")
        
    except Exception as e:
        st.warning(f"Map Overlay Error: {e}. Check if layers exist for this area.")

    # 3. RECOMMENDATIONS
    st.subheader("📌 Action Plan")
    if res['risk'] == "HIGH":
        st.error(f"🚨 **High Alert for {res['month_name']}**: Environmental conditions strongly favor pest outbreaks. Implement strict drainage control and fungicide schedule.")
    elif res['risk'] == "MODERATE":
        st.warning(f"⚠️ **Moderate Caution**: Conditions are shifting. Increase field scouting to twice weekly.")
    else:
        st.success("✅ **Low Risk**: Conditions are currently stable for ginger cultivation.")

    with st.expander("ℹ️ About Raster Layers"):
        st.write("**Pest Vulnerability:** Derived from slope (drainage efficiency) and satellite-detected moisture.")
        st.write("**Rainfall Intensity:** Uses CHIRPS Daily precipitation data aggregated over 12 months.")
