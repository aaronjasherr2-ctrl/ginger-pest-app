import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import datetime
import os

# ----------------------------------------------------------
# CONFIG
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

# ----------------------------------------------------------
# 🎨 UI / DARK GLASS THEME
# ----------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');

html, body {
    font-family: 'Inter', sans-serif;
    background-color: #081c15;
    color: #D8F3DC;
}

/* HEADER */
.header {
    display: flex;
    align-items: center;
    gap: 15px;
    background: rgba(27,67,50,0.6);
    padding: 15px 20px;
    border-radius: 15px;
    backdrop-filter: blur(10px);
}

/* METRIC CARDS */
div[data-testid="metric-container"] {
    background: rgba(255,255,255,0.05);
    border-radius: 15px;
    padding: 15px;
    border: 1px solid rgba(255,255,255,0.1);
}

/* SIDEBAR */
section[data-testid="stSidebar"] {
    background-color: #020617;
}

/* LEGEND */
.legend {
    position: fixed;
    bottom: 40px;
    left: 40px;
    background: rgba(0,0,0,0.7);
    padding: 10px;
    border-radius: 10px;
    color: white;
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# HEADER
# ----------------------------------------------------------
logo_html = ""
if os.path.exists("agusipan_logo.png"):
    logo_html = f'<img src="agusipan_logo.png" width="60">'

st.markdown(f"""
<div class="header">
    {logo_html}
    <div>
        <h2 style="margin:0;">🌱 Ginger Pest Warning System</h2>
        <p style="margin:0; font-size:14px;">Agusipan 4H CLUB MONITORING DASHBOARD</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------
st.sidebar.header("📍 Farm Settings")

loc = get_geolocation()
lat, lon = 10.98, 122.50

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']

lat = st.sidebar.number_input("Latitude", value=lat, format="%.4f")
lon = st.sidebar.number_input("Longitude", value=lon, format="%.4f")

month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
selected_month = st.sidebar.selectbox("Month", range(1,13),
                                      format_func=lambda x: month_names[x-1])

run = st.sidebar.button("🚀 Run Analysis")

# ----------------------------------------------------------
# EARTH ENGINE INIT
# ----------------------------------------------------------
ee.Initialize()

# ----------------------------------------------------------
# CACHE ANALYSIS
# ----------------------------------------------------------
@st.cache_data(show_spinner=False)
def run_analysis(lat, lon):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    results = {
        "scores": [],
        "rain": [],
        "temp": [],
        "images": []
    }

    for month in range(1, 13):
        start = ee.Date.fromYMD(2023, month, 1)
        end = start.advance(1, 'month')

        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum()
        lst = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).mean()\
                .multiply(0.02).subtract(273.15)

        ndvi = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')\
                .filterDate(start, end).median()\
                .normalizedDifference(['B8','B4'])

        vuln = slope.divide(30).multiply(0.2)\
            .add(rain.divide(500).multiply(0.25))\
            .add(lst.divide(35).multiply(0.15))\
            .add(ndvi.multiply(-1).add(1).multiply(0.15))\
            .clip(buffer)

        score = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()

        results["scores"].append(score.get('slope',0.5))
        results["rain"].append(rain.reduceRegion(ee.Reducer.mean(), buffer,100).getInfo().get('precipitation',0))
        results["temp"].append(lst.reduceRegion(ee.Reducer.mean(), buffer,100).getInfo().get('LST_Day_1km',28))
        results["images"].append(vuln)

    return results

# ----------------------------------------------------------
# RUN
# ----------------------------------------------------------
if run:
    with st.spinner("Processing satellite data..."):
        st.session_state.data = run_analysis(lat, lon)

# ----------------------------------------------------------
# DISPLAY
# ----------------------------------------------------------
if "data" in st.session_state:

    data = st.session_state.data
    idx = selected_month - 1

    score = data["scores"][idx]
    rain = data["rain"][idx]
    temp = data["temp"][idx]
    vuln_img = data["images"][idx]

    # Risk
    if score < 0.35:
        risk = "LOW"
        alert = st.success
    elif score < 0.55:
        risk = "MODERATE"
        alert = st.warning
    else:
        risk = "HIGH"
        alert = st.error

    # METRICS
    c1, c2, c3 = st.columns(3)
    c1.metric("🌧 Rainfall", f"{rain:.1f} mm")
    c2.metric("🌡 Temperature", f"{temp:.1f} °C")
    c3.metric("⚠ Risk", risk)

    # ------------------------------------------------------
    # MAP WITH RASTER
    # ------------------------------------------------------
    m = folium.Map(location=[lat, lon], zoom_start=15)

    vis = {
        'min':0,
        'max':1,
        'palette':['green','yellow','red']
    }

    map_id = vuln_img.getMapId(vis)

    folium.TileLayer(
        tiles=map_id['tile_fetcher'].url_format,
        attr='EE',
        overlay=True,
        name='Vulnerability'
    ).add_to(m)

    # Circle boundary
    folium.Circle([lat, lon], radius=1000).add_to(m)

    # Legend
    legend_html = """
    <div class="legend">
        <b>Risk Level</b><br>
        🟢 Low<br>
        🟡 Moderate<br>
        🔴 High
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    st_folium(m, width=1200, height=500)

    # ------------------------------------------------------
    # ACTION PLAN
    # ------------------------------------------------------
    alert(f"Risk Level: {risk}")

    if risk == "LOW":
        st.info("Maintain normal practices.")
    elif risk == "MODERATE":
        st.warning("Improve drainage and monitor crops.")
    else:
        st.error("High risk! Apply disease control immediately.")

    # ------------------------------------------------------
    # TREND GRAPH
    # ------------------------------------------------------
    fig, ax = plt.subplots()

    ax.plot(month_names, data["scores"], linewidth=3)
    ax.scatter(month_names[idx], score, s=100)

    ax.set_facecolor("#081c15")
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    ax.set_ylabel("Vulnerability")
    ax.set_xlabel("Month")

    st.pyplot(fig)
