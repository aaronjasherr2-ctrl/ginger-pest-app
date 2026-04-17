import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from openai import OpenAI
import os

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# Logo Handling
if os.path.exists("agusipan_logo.png"):
    st.image("agusipan_logo.png", width=150)

# Initialize OpenAI
# Note: Ensure OPENAI_API_KEY is correctly set in Streamlit Secrets
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", "missing_key"))

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
    st.error("🚨 Earth Engine failed to initialize. Please check your Secrets format.")
    st.stop()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")
st.caption("Powered by AGUSIPAN 4H CLUB")

# ----------------------------------------------------------
# 2. LOCATION SELECTION (1km Radius Focus)
# ----------------------------------------------------------
st.subheader("📍 Location Selection (1km Analysis Radius)")

use_manual = st.toggle("Enter coordinates manually")

if use_manual:
    lat = st.number_input("Latitude", value=10.98, format="%.4f")
    lon = st.number_input("Longitude", value=122.50, format="%.4f")
else:
    loc = get_geolocation()
    if loc:
        lat = loc['coords']['latitude']
        lon = loc['coords']['longitude']
    else:
        lat, lon = 10.98, 122.50
        st.info("Waiting for GPS... Using default coordinates.")

st.success(f"Targeting: {lat:.4f}, {lon:.4f} within a 1km buffer.")

# Define Area of Interest
roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000) 

# ----------------------------------------------------------
# 3. ANALYSIS LOGIC
# ----------------------------------------------------------
def normalize(img, area):
    stats = img.reduceRegion(ee.Reducer.minMax(), area, 100, maxPixels=1e9)
    band = img.bandNames().get(0)
    minv = ee.Number(stats.get(ee.String(band).cat('_min')))
    maxv = ee.Number(stats.get(ee.String(band).cat('_max')))
    return img.subtract(minv).divide(maxv.subtract(minv).max(0.0001))

# ----------------------------------------------------------
# 4. DATA PROCESSING
# ----------------------------------------------------------
with st.spinner("Analyzing satellite data for your 1km radius..."):
    year = 2023
    months = list(range(5, 11))
    scores, rain_vals, lst_vals = [], [], []

    # Static layers
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)
    twi = dem.focal_mean(3).add(1).log().divide(slope.add(1))

    for m in months:
        start = ee.Date.fromYMD(year, m, 1)
        end = start.advance(1, 'month')

        # Precipitation
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        
        # Land Surface Temp (Corrected Scaling)
        lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer)
        
        if lst_col.size().getInfo() > 0:
            lst = lst_col.map(lambda img: img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)).mean().clip(buffer)
        else:
            lst = ee.Image(28).clip(buffer) 

        # NDVI
        ndvi = ee.ImageCollection('COPERNICUS/S2_SR').filterDate(start, end).filterBounds(buffer).map(lambda img: img.normalizedDifference(['B8','B4'])).mean().clip(buffer)

        # Risk Calculation
        slopeN = normalize(slope, buffer)
        twiN = normalize(twi, buffer)
        rainN = normalize(rain, buffer)
        lstN = normalize(lst, buffer)
        ndviN = normalize(ndvi.multiply(-1), buffer)

        vuln = (slopeN.multiply(0.2).add(twiN.multiply(0.25)).add(rainN.multiply(0.25)).add(lstN.multiply(0.15)).add(ndviN.multiply(0.15)))

        res = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        scores.append(list(res.values())[0] if res else 0)

        rain_res = rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        rain_vals.append(rain_res.get('precipitation', 0) if rain_res else 0)

        lst_res = lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        lst_vals.append(list(lst_res.values())[0] if lst_res else 28)

# ----------------------------------------------------------
# 5. DASHBOARD DISPLAY
# ----------------------------------------------------------
m_col1, m_col2 = st.columns(2)
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

with m_col1:
    st.metric("Avg Rainfall (1km Radius)", f"{avg_rain:.1f} mm")
with m_col2:
    st.metric("Avg Surface Temp", f"{avg_lst:.1f} °C")

st.subheader("📊 1km Radius Risk Trend")
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'], scores, marker='o', color='#27ae60', linewidth=2)
ax.set_ylabel("Risk Index")
st.pyplot(fig)

latest_score = scores[-1]
risk_text = "LOW" if latest_score < 0.3 else "MODERATE" if latest_score < 0.6 else "HIGH"
color = "green" if risk_text == "LOW" else "orange" if risk_text == "MODERATE" else "red"

st.markdown(f"### 🎯 Current Risk Assessment (1km Radius): :{color}[{risk_text}]")

# ----------------------------------------------------------
# 6. AI AUTOMATED RECOMMENDATIONS
# ----------------------------------------------------------
st.divider()
st.subheader("🧠 AGUSIPAN AI Farmer's Recommendation")

try:
    context = (f"Location: {lat}, {lon}. Risk Level: {risk_text} (Score: {latest_score:.2f}). "
               f"Avg Rainfall: {avg_rain:.1f}mm. Avg Surface Temperature: {avg_lst:.1f}C. "
               f"Months Analyzed: May to October.")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a professional agricultural expert for AGUSIPAN 4H CLUB. Summarize the risk and give clear, bulleted recommendations for ginger farmers based on the data provided."},
            {"role": "user", "content": f"Please summarize these findings and give advice: {context}"}
        ]
    )
    
    st.write(response.choices[0].message.content)

except Exception as ai_err:
    st.warning("⚠️ Could not generate AI recommendations. Please check your OpenAI API key and billing status.")
    st.error(f"Error details: {ai_err}")
