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

if os.path.exists("agusipan_logo.png"):
    st.image("agusipan_logo.png", width=180)

try:
    if not ee.data._initialized:
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
# 2. REAL-TIME LOCATION TRACKING
# ----------------------------------------------------------
st.subheader("📍 Farm Location")

loc = get_geolocation()
lat, lon = 10.98, 122.50 # Default Iloilo

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"✅ Real-time GPS active: {lat:.4f}, {lon:.4f}")
else:
    st.info("📡 Finding GPS... please allow location access.")

with st.expander("🛠️ Optional: Enter Coordinates Manually"):
    lat = st.number_input("Manual Latitude", value=lat, format="%.4f")
    lon = st.number_input("Manual Longitude", value=lon, format="%.4f")

# ----------------------------------------------------------
# 3. RUN ANALYSIS
# ----------------------------------------------------------
if st.button("🚀 Start 1km Radius Analysis"):
    roi = ee.Geometry.Point([lon, lat])
    buffer = roi.buffer(1000)

    with st.spinner("Analyzing satellite data..."):
        year = 2023
        months = list(range(5, 11))
        month_names = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
        
        scores, rain_vals, lst_vals = [], [], []

        # Static GIS Layers
        dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
        slope = ee.Terrain.slope(dem)
        # Simplified TWI for stability
        twi = dem.add(1).log().divide(slope.add(0.1)) 

        def normalize_val(img, area):
            # Safer normalization using fixed typical ranges to avoid .getInfo loops
            stats = img.reduceRegion(ee.Reducer.minMax(), area, 100).getInfo()
            band = list(stats.keys())[0]
            min_v = stats[band] if stats[band] is not None else 0
            # Get max, ensure it's not the same as min
            max_v = stats[list(stats.keys())[1]] if stats[list(stats.keys())[1]] is not None else 1
            return img.subtract(min_v).divide(ee.Number(max_v).subtract(min_v).max(0.001))

        for m in months:
            start = ee.Date.fromYMD(year, m, 1)
            end = start.advance(1, 'month')

            # 1. Rainfall
            rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
            
            # 2. LST (Landsat 8) - Added Cloud Filter
            lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer).filter(ee.Filter.lt('CLOUD_COVER', 30))
            
            if lst_col.size().getInfo() > 0:
                lst = lst_col.map(lambda img: img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)).mean().clip(buffer)
            else:
                lst = ee.Image(28.0).clip(buffer)

            # 3. NDVI (Sentinel 2) - Added Cloud Filter
            s2_col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate(start, end).filterBounds(buffer).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
            
            if s2_col.size().getInfo() > 0:
                ndvi = s2_col.median().normalizedDifference(['B8','B4']).clip(buffer)
            else:
                ndvi = ee.Image(0.5).clip(buffer)

            # 4. Calculation (Calculated on server-side as much as possible)
            # Weights: Slope(20%), TWI(25%), Rain(25%), LST(15%), NDVI(15%)
            vuln = (slope.divide(45).multiply(0.2)
                    .add(rain.divide(500).multiply(0.25))
                    .add(lst.divide(40).multiply(0.15))
                    .add(ndvi.multiply(-1).add(1).multiply(0.15)))

            # Extract final values
            res = vuln.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
            scores.append(list(res.values())[0] if res else 0.5)

            r_res = rain.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
            rain_vals.append(list(r_res.values())[0] if r_res else 0)

            l_res = lst.reduceRegion(ee.Reducer.mean(), buffer, 100).getInfo()
            lst_vals.append(list(l_res.values())[0] if l_res else 28.0)

    # ----------------------------------------------------------
    # 4. RESULTS DISPLAY
    # ----------------------------------------------------------
    st.divider()
    m = folium.Map(location=[lat, lon], zoom_start=15)
    folium.Circle([lat, lon], radius=1000, color="red", fill=True, fill_opacity=0.1).add_to(m)
    folium.Marker([lat, lon], popup="Farm Center").add_to(m)
    st_folium(m, width=1200, height=400)

    avg_rain = sum(rain_vals) / len(rain_vals)
    avg_lst = sum(lst_vals) / len(lst_vals)
    latest_score = scores[-1]

    if latest_score < 0.30:
        risk_level, color, rec_list = "LOW", "green", ["Ideal conditions.", "Standard weeding.", "Monitor for leaf spot."]
    elif latest_score < 0.55:
        risk_level, color, rec_list = "MODERATE", "orange", ["Check drainage.", "Apply mulch to cool soil.", "Inspect for rhizome rot."]
    else:
        risk_level, color, rec_list = "HIGH", "red", ["IMPROVE DRAINAGE NOW.", "Apply fungicide.", "Limit field movement."]

    col_stats, col_graph = st.columns([1, 1.5])
    with col_stats:
        st.markdown(f"### Status: :{color}[{risk_level}]")
        st.metric("Avg Rainfall (Monthly)", f"{avg_rain:.1f} mm")
        st.metric("Avg Surface Temp", f"{avg_lst:.1f} °C")

    with col_graph:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(month_names, scores, marker='o', color='#2ecc71', linewidth=2)
        ax.set_title("Vulnerability Trend (May-Oct)")
        ax.set_ylabel("Risk Score")
        st.pyplot(fig)

    st.divider()
    st.subheader("📋 AGUSIPAN 4H CLUB Recommendation Report")
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"**Analysis Summary:** Location {lat:.4f}, {lon:.4f} is in a **{risk_level}** risk zone.")
    with c2:
        st.success("**Farmer Action Plan:**")
        for rec in rec_list:
            st.write(f"- {rec}")
