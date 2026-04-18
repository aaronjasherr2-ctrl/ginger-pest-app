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
# LOGO
# ============================================================
def get_logo_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo = get_logo_base64("agusipan_logo.png")
logo_html = f'<img src="data:image/png;base64,{logo}" width="80">' if logo else "🌱"

st.markdown(f"""
<div style="display:flex; align-items:center; gap:15px;
background:#1B4332; padding:15px; border-radius:15px; margin-bottom:20px;">
{logo_html}
<div>
<h2 style="margin:0; color:white;">Ginger Pest Warning System</h2>
<p style="margin:0; color:#D8F3DC;">Agusipan 4H CLUB MONITORING DASHBOARD</p>
</div>
</div>
""", unsafe_allow_html=True)


# ============================================================
# EARTH ENGINE INIT
# FIX: normalize private_key escaped newlines from Streamlit secrets
# ============================================================
EE_AVAILABLE = False
try:
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        # Streamlit secrets stores PEM newlines as literal "\\n" — fix it
        info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = ee.ServiceAccountCredentials(
            info["client_email"],
            key_data=info["private_key"]
        )
        ee.Initialize(creds, project=info["project_id"])
    else:
        ee.Initialize()
    EE_AVAILABLE = True
except Exception as e:
    st.warning(f"⚠️ Earth Engine unavailable — map will show 1 km fallback circle. ({e})")


# ============================================================
# AUTO-DETECT LOCATION via IP geolocation (two providers for reliability)
# ============================================================
def get_ip_location():
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        d = r.json()
        label = f"{d.get('city','')}, {d.get('region','')}".strip(", ")
        return float(d["latitude"]), float(d["longitude"]), label or "Detected location"
    except Exception:
        pass
    try:
        r2 = requests.get("http://ip-api.com/json/", timeout=5)
        d2 = r2.json()
        return float(d2["lat"]), float(d2["lon"]), d2.get("city", "Detected location")
    except Exception:
        return None


# ============================================================
# SESSION STATE — default to Badiangan, Iloilo area
# ============================================================
if "lat"       not in st.session_state: st.session_state.lat       = 10.9300
if "lon"       not in st.session_state: st.session_state.lon       = 122.5200
if "loc_label" not in st.session_state: st.session_state.loc_label = "Default location"


# ============================================================
# LOCATION UI
# ============================================================
st.subheader("📍 Farm Location")

btn_col, info_col = st.columns([1, 3])

with btn_col:
    if st.button("📡 Auto-Detect Location"):
        result = get_ip_location()
        if result:
            st.session_state.lat, st.session_state.lon, lbl = result
            st.session_state.loc_label = lbl + " (auto-detected)"
        else:
            st.error("Could not detect location. Please enter coordinates manually below.")

with info_col:
    st.info(
        f"📌 **{st.session_state.loc_label}** — "
        f"Lat: `{st.session_state.lat:.4f}`, Lon: `{st.session_state.lon:.4f}`"
    )

with st.expander("✏️ Enter Coordinates Manually"):
    mc1, mc2 = st.columns(2)
    manual_lat = mc1.number_input("Latitude",  value=float(st.session_state.lat), format="%.4f")
    manual_lon = mc2.number_input("Longitude", value=float(st.session_state.lon), format="%.4f")
    if st.button("✅ Use These Coordinates"):
        st.session_state.lat       = manual_lat
        st.session_state.lon       = manual_lon
        st.session_state.loc_label = f"Manual ({manual_lat:.4f}, {manual_lon:.4f})"
        st.rerun()

lat = float(st.session_state.lat)
lon = float(st.session_state.lon)

month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
month = st.selectbox("📅 Month for Analysis", range(1, 13),
                     index=4, format_func=lambda x: month_names[x - 1])

run = st.button("🚀 Run Analysis", type="primary")


# ============================================================
# EARTH ENGINE MODEL
# Based on validated GEE script — safeImage pattern prevents empty-band errors
# Weights: slope 0.20 | TWI 0.25 | rain 0.25 | LST 0.15 | NDVI 0.15
# ============================================================
def safe_image(ee_img, name):
    """Safely wraps any EE image — handles empty/missing collections."""
    return ee.Image(ee_img).rename(name).unmask(0)


def normalize_img(img, buffer):
    img  = ee.Image(img).unmask(0)
    band = img.bandNames().get(0)
    stats = img.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=buffer, scale=100, maxPixels=1e9
    )
    mn  = ee.Number(stats.get(ee.String(band).cat('_min')))
    mx  = ee.Number(stats.get(ee.String(band).cat('_max')))
    rng = mx.subtract(mn).max(0.0001)
    return img.subtract(mn).divide(rng)


def build_vulnerability(lat, lon, month):
    roi    = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)
    year   = 2023

    # Static
    dem   = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem).rename('slope')
    twi   = dem.focal_mean(3).add(1).log().divide(slope.add(1)).rename('twi')
    slope_n = normalize_img(slope, buffer)
    twi_n   = normalize_img(twi,   buffer)

    # Annual baseline
    rain_annual = safe_image(
        ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
            .filterDate(f'{year}-01-01', f'{year}-12-31').sum(), 'rain')

    lst_annual = safe_image(
        ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
            .filterDate(f'{year}-01-01', f'{year}-12-31')
            .filterBounds(buffer)
            .map(lambda i: i.select('ST_B10')
                            .multiply(0.00341802).add(149.0).subtract(273.15)
                            .rename('lst'))
            .mean(), 'lst')

    ndvi_annual = safe_image(
        ee.ImageCollection('COPERNICUS/S2_SR')
            .filterDate(f'{year}-01-01', f'{year}-12-31')
            .filterBounds(buffer)
            .map(lambda i: i.normalizedDifference(['B8','B4']).rename('ndvi'))
            .mean(), 'ndvi')

    # Monthly
    start = ee.Date.fromYMD(year, month, 1)
    end   = start.advance(1, 'month')

    rain_m = safe_image(
        ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum(), 'rain')

    lst_m = safe_image(
        ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
            .filterDate(start, end).filterBounds(buffer)
            .map(lambda i: i.select('ST_B10')
                            .multiply(0.00341802).add(149.0).subtract(273.15)
                            .rename('lst'))
            .mean(), 'lst')

    ndvi_m = safe_image(
        ee.ImageCollection('COPERNICUS/S2_SR')
            .filterDate(start, end).filterBounds(buffer)
            .map(lambda i: i.normalizedDifference(['B8','B4']).rename('ndvi'))
            .mean(), 'ndvi')

    # Anomalies
    rain_anom   = rain_m.divide(rain_annual.add(1)).unmask(0)
    lst_anom    = lst_m.subtract(lst_annual).unmask(0)
    ndvi_stress = ndvi_annual.subtract(ndvi_m).unmask(0)

    rain_n = normalize_img(rain_anom,   buffer)
    lst_n  = normalize_img(lst_anom,    buffer)
    ndvi_n = normalize_img(ndvi_stress, buffer)

    vuln = (
        slope_n.multiply(0.20)
        .add(twi_n.multiply(0.25))
        .add(rain_n.multiply(0.25))
        .add(lst_n.multiply(0.15))
        .add(ndvi_n.multiply(0.15))
        .rename('vuln')
        .clip(buffer)
    )
    return vuln, buffer


# ============================================================
# FALLBACK MAP — 1 km colored circle when EE tiles unavailable
# ============================================================
def render_fallback_map(lat, lon, score, risk):
    color = {'LOW': '#2dc937', 'MODERATE': '#e7b416', 'HIGH': '#cc3232'}[risk]
    fol_color = {'LOW': 'green', 'MODERATE': 'orange', 'HIGH': 'red'}[risk]
    m = folium.Map(location=[lat, lon], zoom_start=15)
    folium.Circle(
        [lat, lon], radius=1000,
        color=color, fill=True, fill_color=color, fill_opacity=0.30, weight=2,
        popup=f"Risk: {risk}  |  Score: {score:.2f}"
    ).add_to(m)
    folium.Marker(
        [lat, lon],
        popup=f"Farm — Risk: {risk}",
        icon=folium.Icon(color=fol_color, icon='leaf', prefix='fa')
    ).add_to(m)
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed; bottom:50px; left:50px;
    background:rgba(0,0,0,0.75); padding:12px 16px;
    border-radius:10px; color:white; z-index:1000; font-size:13px;">
    <b>Risk: {risk}</b><br>Score: {score:.2f}<br><br>
    🟢 Low (&lt;0.35)<br>🟡 Moderate (0.35–0.60)<br>🔴 High (&gt;0.60)
    </div>"""))
    return m


# ============================================================
# RUN ANALYSIS
# ============================================================
if run:
    score    = 0.5
    vuln_img = None

    with st.spinner("⏳ Running vulnerability analysis…"):
        if EE_AVAILABLE:
            try:
                vuln_img, buffer = build_vulnerability(lat, lon, month)
                score_dict = vuln_img.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=buffer, scale=100
                ).getInfo()
                raw   = score_dict.get("vuln")
                score = float(raw) if raw is not None else 0.5
            except Exception as e:
                st.warning(f"EE computation note: {e}")
                vuln_img = None   # fall through to fallback map

    risk = "HIGH" if score > 0.6 else "MODERATE" if score > 0.35 else "LOW"

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("📊 Vulnerability Score", f"{score:.2f}")
    c2.metric("⚠️ Risk Level", risk)
    c3.metric("📅 Month", month_names[month - 1])

    # Map
    st.subheader("🗺️ Vulnerability Map")
    map_rendered = False

    if EE_AVAILABLE and vuln_img is not None:
        try:
            vis = {'min': 0, 'max': 0.8, 'palette': ['2dc937', 'e7b416', 'cc3232']}
            map_id_dict = vuln_img.getMapId(vis)

            # FIX: safely retrieve tile URL across earthengine-api versions
            tile_fetcher = map_id_dict.get('tile_fetcher')
            if tile_fetcher and hasattr(tile_fetcher, 'url_format'):
                tile_url = tile_fetcher.url_format
            elif tile_fetcher and hasattr(tile_fetcher, 'formatTileUrl'):
                sample   = tile_fetcher.formatTileUrl(0, 0, 0)
                tile_url = '/'.join(sample.split('/')[:5]) + '/{z}/{x}/{y}'
            else:
                tile_url = (
                    "https://earthengine.googleapis.com/map/"
                    f"{map_id_dict['mapid']}/{{z}}/{{x}}/{{y}}"
                    f"?token={map_id_dict['token']}"
                )

            m = folium.Map(location=[lat, lon], zoom_start=15)
            folium.TileLayer(tiles=tile_url, attr='Google Earth Engine',
                             overlay=True, name='Vulnerability').add_to(m)
            folium.Circle([lat, lon], radius=1000,
                          color='blue', fill=False, weight=2).add_to(m)
            folium.LayerControl().add_to(m)
            m.get_root().html.add_child(folium.Element("""
            <div style="position:fixed; bottom:50px; left:50px;
            background:rgba(0,0,0,0.75); padding:12px 16px;
            border-radius:10px; color:white; z-index:1000; font-size:13px;">
            <b>Vulnerability</b><br>🟢 Low<br>🟡 Moderate<br>🔴 High</div>"""))
            st_folium(m, width=1200, height=500)
            map_rendered = True

        except Exception as e:
            st.warning(f"EE tile map unavailable: `{e}` — showing fallback map.")

    if not map_rendered:
        st.info("ℹ️ Showing 1 km radius map (EE satellite tiles unavailable).")
        m = render_fallback_map(lat, lon, score, risk)
        st_folium(m, width=1200, height=500)

    # Recommendation
    st.subheader("📌 Recommendation")
    if risk == "LOW":
        st.success(
            "✅ **Low Risk** — Conditions are favorable. "
            "Maintain standard practices and continue regular monitoring."
        )
    elif risk == "MODERATE":
        st.warning(
            "⚠️ **Moderate Risk** — Increased pest/disease pressure. "
            "Improve field drainage, inspect plants weekly, and consider preventive fungicide application."
        )
    else:
        st.error(
            "🚨 **High Risk** — Critical outbreak conditions detected. "
            "Apply appropriate pesticides/fungicides immediately, improve drainage, "
            "and coordinate with your local agricultural office."
        )

    with st.expander("📐 Model Factor Weights"):
        st.markdown("""
| Factor | Weight | Data Source |
|--------|--------|-------------|
| Slope | 20% | USGS SRTM DEM |
| Topographic Wetness Index (TWI) | 25% | USGS SRTM DEM |
| Rainfall Anomaly | 25% | CHIRPS Daily |
| LST Anomaly | 15% | Landsat 8 C2 |
| NDVI Stress | 15% | Sentinel-2 SR |
        """)
