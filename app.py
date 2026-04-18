import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os
import datetime

# ----------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Ginger Pest Warning System")

# ----------------------------------------------------------
# 🎨 CUSTOM DARK UI
# ----------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');

html, body, [class*="css"]  {
    font-family: 'Inter', sans-serif;
    background-color: #0f172a;
    color: #e2e8f0;
}

/* HEADER */
.header {
    padding: 10px 20px;
    border-radius: 15px;
    background: linear-gradient(90deg, #064e3b, #065f46);
    color: white;
}

/* METRIC CARDS */
div[data-testid="metric-container"] {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 15px;
    padding: 15px;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,0.1);
}

/* SIDEBAR */
section[data-testid="stSidebar"] {
    background-color: #020617;
}

/* BUTTON */
.stButton>button {
    background: linear-gradient(90deg, #065f46, #10b981);
    border-radius: 10px;
    color: white;
    border: none;
}

/* TABS */
.stTabs [data-baseweb="tab"] {
    font-size: 16px;
}

.block-container {
    padding-top: 1rem;
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# HEADER WITH LOGO
# ----------------------------------------------------------
col1, col2 = st.columns([1, 6])

with col1:
    if os.path.exists("agusipan_logo.png"):
        st.image("agusipan_logo.png", width=90)

with col2:
    st.markdown("""
    <div class="header">
        <h1>🌱 Ginger Pest Warning System</h1>
        <p>Agusipan Smart Monitoring Dashboard</p>
    </div>
    """, unsafe_allow_html=True)

# ----------------------------------------------------------
# SIDEBAR CONTROLS
# ----------------------------------------------------------
st.sidebar.header("📍 Farm Settings")

loc = get_geolocation()
lat, lon = 10.98, 122.50

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']

lat = st.sidebar.number_input("Latitude", value=lat, format="%.4f")
lon = st.sidebar.number_input("Longitude", value=lon, format="%.4f")

current_month = datetime.datetime.now().month
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

selected_month = st.sidebar.selectbox(
    "📅 Month",
    options=list(range(1, 13)),
    format_func=lambda x: month_names[x-1],
    index=current_month-1
)

run = st.sidebar.button("🚀 Run Analysis")

# ----------------------------------------------------------
# SESSION STATE
# ----------------------------------------------------------
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None

# ----------------------------------------------------------
# EARTH ENGINE INIT
# ----------------------------------------------------------
try:
    if "gcp_service_account" in st.secrets:
        creds = ee.ServiceAccountCredentials(
            st.secrets["gcp_service_account"]["client_email"],
            key_data=st.secrets["gcp_service_account"]["private_key"]
        )
        ee.Initialize(creds)
    else:
        ee.Initialize()
except Exception as e:
    st.error(f"Earth Engine error: {e}")
    st.stop()

# ----------------------------------------------------------
# RUN ANALYSIS
# ----------------------------------------------------------
if run:
    progress = st.progress(0, text="Processing satellite data...")

    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    results = {
        "month_names": month_names,
        "scores": [],
        "rain_vals": [],
        "lst_vals": [],
        "lat": lat,
        "lon": lon
    }

    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)

    for i, month in enumerate(range(1, 13)):
        start = ee.Date.fromYMD(2023, month, 1)
        end = start.advance(1, 'month')

        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
                 .filterDate(start, end).sum().clip(buffer)

        lst = ee.ImageCollection('MODIS/061/MOD11A2') \
                .filterDate(start, end).mean() \
                .multiply(0.02).subtract(273.15).clip(buffer)

        s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                .filterDate(start, end).median()

        ndvi = s2.normalizedDifference(['B8', 'B4']).clip(buffer)

        vuln = slope.divide(30).multiply(0.2) \
            .add(rain.divide(500).multiply(0.25)) \
            .add(lst.divide(35).multiply(0.15)) \
            .add(ndvi.multiply(-1).add(1).multiply(0.15))

        score_dict = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()

        results["scores"].append(score_dict.get('slope', 0.5))
        results["rain_vals"].append(rain.reduceRegion(
            ee.Reducer.mean(), buffer, 100).getInfo().get('precipitation', 0))
        results["lst_vals"].append(lst.reduceRegion(
            ee.Reducer.mean(), buffer, 100).getInfo().get('LST_Day_1km', 28))

        progress.progress((i+1)/12, text=f"Processing month {month}...")

    st.session_state.analysis_results = results
    progress.empty()

# ----------------------------------------------------------
# DISPLAY RESULTS
# ----------------------------------------------------------
if st.session_state.analysis_results:

    res = st.session_state.analysis_results
    idx = selected_month - 1

    score = res["scores"][idx]
    rain = res["rain_vals"][idx]
    temp = res["lst_vals"][idx]

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
    c3.metric("⚠ Risk Level", risk)

    # TABS
    tab1, tab2, tab3 = st.tabs(["📊 Analysis", "🗺 Map", "📈 Trends"])

    # ---------------- TAB 1
    with tab1:
        alert(f"Risk Level: {risk}")

        if risk == "LOW":
            st.info("Maintain normal farming practices.")
        elif risk == "MODERATE":
            st.warning("Improve drainage and monitor crop health.")
        else:
            st.error("High pest/disease risk! Immediate action required.")

    # ---------------- TAB 2
    with tab2:
        m = folium.Map(location=[res["lat"], res["lon"]], zoom_start=15)
        folium.Circle([res["lat"], res["lon"]],
                      radius=1000,
                      color="green",
                      fill=True,
                      fill_opacity=0.2).add_to(m)
        st_folium(m, width=1200, height=500)

    # ---------------- TAB 3
    with tab3:
        fig, ax = plt.subplots()

        ax.plot(res["month_names"], res["scores"], linewidth=3)
        ax.scatter(res["month_names"][idx], score, s=100)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        ax.set_ylabel("Vulnerability Score")
        ax.set_xlabel("Month")

        st.pyplot(fig)
