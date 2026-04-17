import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os
import datetime

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# Initialize Session State
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None

# Logo Handling
if os.path.exists("agusipan_logo.png"):
    st.image("agusipan_logo.png", width=180)

# Initialize Earth Engine
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
    st.error(f"🚨 Earth Engine failed to initialize: {e}")
    st.stop()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")
st.caption("Official Decision Support System | Powered by AGUSIPAN 4H CLUB")

# ----------------------------------------------------------
# 2. LOCATION TRACKING
# ----------------------------------------------------------
st.subheader("📍 Farm Location")
loc = get_geolocation()
lat, lon = 10.98, 122.50  # Default: Iloilo, PH

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"✅ GPS Position: {lat:.4f}, {lon:.4f}")

with st.expander("🛠️ Manual Coordinate Override"):
    lat = st.number_input("Latitude", value=lat, format="%.4f")
    lon = st.number_input("Longitude", value=lon, format="%.4f")

# ----------------------------------------------------------
# 3. MONTH SELECTION (default = current month)
# ----------------------------------------------------------
current_month = datetime.datetime.now().month
month_names_full = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
selected_month = st.selectbox(
    "📅 Select month to analyze",
    options=list(range(1, 13)),
    format_func=lambda x: month_names_full[x-1],
    index=current_month-1
)

# ----------------------------------------------------------
# 4. ANALYSIS LOGIC (runs for all 12 months)
# ----------------------------------------------------------
if st.button("🚀 Run 1km Radius Analysis"):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    with st.spinner("Fetching satellite data for all months..."):
        results = {
            "month_names": month_names_full,
            "scores": [],
            "rain_vals": [],
            "lst_vals": [],
            "lat": lat,
            "lon": lon
        }

        # Static terrain (same for all months)
        dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
        slope = ee.Terrain.slope(dem)

        for month in range(1, 13):
            start = ee.Date.fromYMD(2023, month, 1)
            end = start.advance(1, 'month')

            # Rainfall: CHIRPS daily sum
            rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
                     .filterDate(start, end) \
                     .sum() \
                     .clip(buffer)

            # Land Surface Temperature (Landsat 8, cloud-filtered + clamping)
            lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
                        .filterDate(start, end) \
                        .filterBounds(buffer) \
                        .filter(ee.Filter.lt('CLOUD_COVER', 30))  # stricter cloud filter

            def lst_from_landsat(img):
                lst = img.select('ST_B10') \
                         .multiply(0.00341802) \
                         .add(149.0) \
                         .subtract(273.15)
                # Clamp to realistic range for Philippines (20-40°C)
                return lst.clamp(20, 40)

            lst_img = lst_col.map(lst_from_landsat).mean().clip(buffer)
            # If no Landsat images, fallback to MODIS LST (more reliable)
            if lst_col.size().getInfo() == 0:
                modis = ee.ImageCollection('MODIS/061/MOD11A2') \
                          .filterDate(start, end) \
                          .filterBounds(buffer) \
                          .select('LST_Day_1km') \
                          .mean() \
                          .multiply(0.02) \
                          .subtract(273.15) \
                          .clip(buffer)
                lst_img = ee.Image(modis).clamp(20, 40)

            # NDVI from Sentinel-2
            s2_col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
                       .filterDate(start, end) \
                       .filterBounds(buffer) \
                       .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
            if s2_col.size().getInfo() > 0:
                ndvi = s2_col.median().normalizedDifference(['B8', 'B4']).clip(buffer)
            else:
                ndvi = ee.Image(0.5)  # fallback

            # Vulnerability score (0-1 scale)
            # Normalized factors: slope/30, rain/500 (tropical), lst/35, (1-ndvi)
            vuln = slope.divide(30).multiply(0.2) \
                   .add(rain.divide(500).multiply(0.25)) \
                   .add(lst_img.divide(35).multiply(0.15)) \
                   .add(ndvi.multiply(-1).add(1).multiply(0.15))

            # Reduce to single value
            score = vuln.reduceRegion(
                ee.Reducer.mean(), buffer, 100
            ).getInfo().get('slope', 0.5)

            rain_val = rain.reduceRegion(
                ee.Reducer.mean(), buffer, 100
            ).getInfo().get('precipitation', 0)

            lst_val = lst_img.reduceRegion(
                ee.Reducer.mean(), buffer, 100
            ).getInfo().get('ST_B10', 28.0)

            results["scores"].append(score)
            results["rain_vals"].append(rain_val)
            results["lst_vals"].append(lst_val)

        st.session_state.analysis_results = results

# ----------------------------------------------------------
# 5. PERSISTENT DISPLAY (using selected month)
# ----------------------------------------------------------
if st.session_state.analysis_results:
    res = st.session_state.analysis_results
    month_idx = selected_month - 1

    st.divider()

    # Map
    m = folium.Map(location=[res["lat"], res["lon"]], zoom_start=15)
    folium.Circle([res["lat"], res["lon"]], radius=1000, color="red", fill=True, fill_opacity=0.1).add_to(m)
    folium.Marker([res["lat"], res["lon"]], popup="Farm Center").add_to(m)
    st_folium(m, width=1200, height=400, key="farm_map")

    # Data for the selected month
    month_score = res["scores"][month_idx]
    month_rain = res["rain_vals"][month_idx]
    month_lst = res["lst_vals"][month_idx]

    # Risk assessment based on selected month
    if month_score < 0.35:
        risk, color, actions = "LOW", "green", ["Ideal conditions.", "Standard weeding."]
    elif month_score < 0.55:
        risk, color, actions = "MODERATE", "orange", ["Check drainage.", "Apply mulch."]
    else:
        risk, color, actions = "HIGH", "red", ["IMPROVE DRAINAGE NOW.", "Apply fungicide."]

    c1, c2 = st.columns([1, 1.5])
    with c1:
        st.markdown(f"### {month_names_full[month_idx]} Status: :{color}[{risk}]")
        st.metric("Rainfall", f"{month_rain:.1f} mm")
        st.metric("Temperature", f"{month_lst:.1f} °C")

    with c2:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(res["month_names"], res["scores"], marker='o', color='#2ecc71')
        ax.scatter([res["month_names"][month_idx]], [month_score], color='red', s=100, zorder=5)
        ax.set_ylim(0, 1)
        ax.set_ylabel("Vulnerability Score")
        ax.set_xlabel("Month")
        ax.grid(True, linestyle='--', alpha=0.5)
        st.pyplot(fig)

    st.success("**Action Plan for this month:**")
    for a in actions:
        st.write(f"- {a}")
