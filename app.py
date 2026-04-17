import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import os

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# Initialize Session State to keep data persistent
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
lat, lon = 10.98, 122.50 # Default

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"✅ GPS Position: {lat:.4f}, {lon:.4f}")

with st.expander("🛠️ Manual Coordinate Override"):
    lat = st.number_input("Latitude", value=lat, format="%.4f")
    lon = st.number_input("Longitude", value=lon, format="%.4f")

# ----------------------------------------------------------
# 3. ANALYSIS LOGIC
# ----------------------------------------------------------
if st.button("🚀 Run 1km Radius Analysis"):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000) 

    with st.spinner("Fetching Satellite Data..."):
        # We store everything in a dictionary inside session_state
        results = {
            "month_names": ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'],
            "scores": [],
            "rain_vals": [],
            "lst_vals": [],
            "lat": lat,
            "lon": lon
        }

        # Terrain (Static)
        dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
        slope = ee.Terrain.slope(dem)

        for m in range(5, 11):
            start = ee.Date.fromYMD(2023, m, 1)
            end = start.advance(1, 'month')

            # Rainfall
            rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
            
            # LST
            lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer).filter(ee.Filter.lt('CLOUD_COVER', 40))
            lst = lst_col.map(lambda img: img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)).mean().clip(buffer) if lst_col.size().getInfo() > 0 else ee.Image(28.0)

            # NDVI
            s2_col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate(start, end).filterBounds(buffer).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
            ndvi = s2_col.median().normalizedDifference(['B8','B4']).clip(buffer) if s2_col.size().getInfo() > 0 else ee.Image(0.5)

            # Calculation
            vuln = slope.divide(30).multiply(0.2).add(rain.divide(400).multiply(0.25)).add(lst.divide(35).multiply(0.15)).add(ndvi.multiply(-1).add(1).multiply(0.15))

            # Reduce to values
            results["scores"].append(vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('slope', 0.5))
            results["rain_vals"].append(rain.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('precipitation', 0))
            results["lst_vals"].append(lst.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo().get('ST_B10', 28.0))

        # Save to session state so it doesn't disappear
        st.session_state.analysis_results = results

# ----------------------------------------------------------
# 4. PERSISTENT DISPLAY
# ----------------------------------------------------------
if st.session_state.analysis_results:
    res = st.session_state.analysis_results
    
    st.divider()
    m = folium.Map(location=[res["lat"], res["lon"]], zoom_start=15)
    folium.Circle([res["lat"], res["lon"]], radius=1000, color="red", fill=True, fill_opacity=0.1).add_to(m)
    folium.Marker([res["lat"], res["lon"]], popup="Farm Center").add_to(m)
    st_folium(m, width=1200, height=400, key="farm_map")

    avg_rain = sum(res["rain_vals"]) / len(res["rain_vals"])
    avg_lst = sum(res["lst_vals"]) / len(res["lst_vals"])
    latest_score = res["scores"][-1]

    if latest_score < 0.35:
        risk, color, actions = "LOW", "green", ["Ideal conditions.", "Standard weeding."]
    elif latest_score < 0.55:
        risk, color, actions = "MODERATE", "orange", ["Check drainage.", "Apply mulch."]
    else:
        risk, color, actions = "HIGH", "red", ["IMPROVE DRAINAGE NOW.", "Apply fungicide."]

    c1, c2 = st.columns([1, 1.5])
    with c1:
        st.markdown(f"### Status: :{color}[{risk}]")
        st.metric("Avg Rainfall", f"{avg_rain:.1f} mm")
        st.metric("Avg Temp", f"{avg_lst:.1f} °C")
    
    with c2:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(res["month_names"], res["scores"], marker='o', color='#2ecc71')
        ax.set_ylim(0, 1)
        st.pyplot(fig)

    st.success("**Action Plan:**")
    for a in actions:
        st.write(f"- {a}")
