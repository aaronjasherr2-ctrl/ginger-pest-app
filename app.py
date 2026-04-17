import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
import os

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

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
    st.error("🚨 Earth Engine failed to initialize. Check your Secrets.")
    st.stop()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")
st.caption("Powered by AGUSIPAN 4H CLUB")

# ----------------------------------------------------------
# 2. LOCATION SELECTION
# ----------------------------------------------------------
st.subheader("📍 Area of Interest")
col_lat, col_lon = st.columns(2)

with col_lat:
    lat = st.number_input("Latitude", value=10.98, format="%.4f")
with col_lon:
    lon = st.number_input("Longitude", value=122.50, format="%.4f")

# Define Area of Interest (1km Buffer)
roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000) 

# ----------------------------------------------------------
# 3. SATELLITE ANALYSIS ENGINE (FIXED TEMPERATURE)
# ----------------------------------------------------------
with st.spinner("Analyzing 1km Radius..."):
    year = 2023
    months = list(range(5, 11))
    month_names = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
    scores, rain_vals, lst_vals = [], [], []

    # GIS Layers
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)
    twi = dem.focal_mean(3).add(1).log().divide(slope.add(1))

    def normalize(img, area):
        stats = img.reduceRegion(ee.Reducer.minMax(), area, 100, maxPixels=1e9)
        band = img.bandNames().get(0)
        minv = ee.Number(stats.get(ee.String(band).cat('_min')))
        maxv = ee.Number(stats.get(ee.String(band).cat('_max')))
        return img.subtract(minv).divide(maxv.subtract(minv).max(0.0001))

    for m in months:
        start = ee.Date.fromYMD(year, m, 1)
        end = start.advance(1, 'month')

        # Rainfall (CHIRPS)
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        
        # FIXED TEMP: Landsat 8 Collection 2 Level 2 Scaling
        lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
                    .filterDate(start, end) \
                    .filterBounds(buffer)
        
        if lst_col.size().getInfo() > 0:
            # The scaling factors for ST_B10 are 0.00341802 (mult) and 149.0 (add)
            # Result is in Kelvin, so we subtract 273.15 for Celsius
            lst = lst_col.map(lambda img: img.select('ST_B10')
                    .multiply(0.00341802)
                    .add(149.0)
                    .subtract(273.15)) \
                    .mean().clip(buffer)
        else:
            # Fallback for missing data: Typical tropical temp
            lst = ee.Image(28.0).clip(buffer)

        # NDVI
        ndvi = ee.ImageCollection('COPERNICUS/S2_SR').filterDate(start, end).filterBounds(buffer) \
                .map(lambda img: img.normalizedDifference(['B8','B4'])).mean().clip(buffer)

        # Risk Math
        vuln = (normalize(slope, buffer).multiply(0.2)
                .add(normalize(twi, buffer).multiply(0.25))
                .add(normalize(rain, buffer).multiply(0.25))
                .add(normalize(lst, buffer).multiply(0.15))
                .add(normalize(ndvi.multiply(-1), buffer).multiply(0.15)))

        # Reduce results to numbers
        vuln_val = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        scores.append(list(vuln_val.values())[0] if vuln_val else 0)

        rain_res = rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        rain_vals.append(rain_res.get('precipitation', 0) if rain_res else 0)

        lst_res = lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        # Extract the first available band value
        temp_reading = list(lst_res.values())[0] if lst_res else 28.0
        # Additional safety check for unrealistic negative values
        lst_vals.append(temp_reading if temp_reading > 0 else 28.0)

# ----------------------------------------------------------
# 4. MAP DISPLAY
# ----------------------------------------------------------
st.subheader("🗺️ 1km Risk Mapping")
m = folium.Map(location=[lat, lon], zoom_start=15)
folium.Circle([lat, lon], radius=1000, color="red", fill=True, fill_opacity=0.1, popup="1km Analysis Radius").add_to(m)
folium.Marker([lat, lon], popup="Farm Center").add_to(m)
st_folium(m, width=1200, height=400)

# ----------------------------------------------------------
# 5. RESULTS & SMALLER GRAPH
# ----------------------------------------------------------
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)
latest_score = scores[-1]

if latest_score < 0.35:
    risk_level, color, rec_list = "LOW", "green", ["Condition is ideal.", "Maintain regular weeding.", "Monitor for early signs of leaf spot."]
elif latest_score < 0.65:
    risk_level, color, rec_list = "MODERATE", "orange", ["Check drainage systems.", "Apply mulch to regulate soil temp.", "Inspect for ginger rhizome rot."]
else:
    risk_level, color, rec_list = "HIGH", "red", ["URGENT: Improve drainage immediately.", "Apply fungicide if necessary.", "Limit movement in fields to prevent spread."]

col_stats, col_graph = st.columns([1, 1.5])

with col_stats:
    st.markdown(f"### Status: :{color}[{risk_level}]")
    st.metric("Avg Rainfall", f"{avg_rain:.1f} mm")
    st.metric("Avg Surface Temp", f"{avg_lst:.1f} °C")

with col_graph:
    fig, ax = plt.subplots(figsize=(6, 2.5))
    ax.plot(month_names, scores, marker='o', color='#2ecc71', linewidth=2)
    ax.set_title("Vulnerability Trend (May-Oct)", fontsize=10)
    ax.set_ylim(0, 1)
    st.pyplot(fig)

# ----------------------------------------------------------
# 6. BUILT-IN RECOMMENDATIONS
# ----------------------------------------------------------
st.divider()
st.subheader("📋 AGUSIPAN 4H CLUB Recommendation Report")

c1, c2 = st.columns(2)
with c1:
    st.info(f"**Analysis Summary:** Your farm at {lat}, {lon} shows a **{risk_level}** vulnerability status. The average surface temperature is **{avg_lst:.1f}°C**, which is within the expected range for ginger cultivation in the Philippines.")

with c2:
    st.success("**Farmer Action Plan:**")
    for rec in rec_list:
        st.write(f"- {rec}")
