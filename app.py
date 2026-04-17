import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from openai import OpenAI

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# Initialize OpenAI
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Initialize Earth Engine 
try:
    if "gcp_service_account" in st.secrets:
        # We assume the key is now correctly formatted in the Secrets dashboard
        creds = ee.ServiceAccountCredentials(
            st.secrets["gcp_service_account"]["client_email"],
            key_data=st.secrets["gcp_service_account"]["private_key"]
        )
        ee.Initialize(creds)
    else:
        # Fallback for local testing
        ee.Initialize()
except Exception as e:
    st.error("🚨 Earth Engine failed to initialize.")
    st.info("Check your Streamlit Secrets for the correct private_key format.")
    st.stop()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")

# ----------------------------------------------------------
# 2. LOCATION SELECTION
# ----------------------------------------------------------
st.subheader("📍 Location Selection")

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
        st.info("Waiting for device GPS... Using default Iloilo coordinates.")

st.success(f"Targeting: {lat:.4f}, {lon:.4f}")

# Define Area of Interest
roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000)

# ----------------------------------------------------------
# 3. ANALYSIS LOGIC
# ----------------------------------------------------------
dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
slope = ee.Terrain.slope(dem)
twi = dem.focal_mean(3).add(1).log().divide(slope.add(1))

def normalize(img):
    stats = img.reduceRegion(ee.Reducer.minMax(), buffer, 100, maxPixels=1e9)
    band = img.bandNames().get(0)
    minv = ee.Number(stats.get(ee.String(band).cat('_min')))
    maxv = ee.Number(stats.get(ee.String(band).cat('_max')))
    return img.subtract(minv).divide(maxv.subtract(minv).max(0.0001))

# ----------------------------------------------------------
# 4. DATA PROCESSING (MONTHLY TRENDS)
# ----------------------------------------------------------
with st.spinner("Fetching satellite data from Google Earth Engine..."):
    year = 2023
    months = list(range(5, 11))
    scores, rain_vals, lst_vals = [], [], []

    for m in months:
        start = ee.Date.fromYMD(year, m, 1)
        end = start.advance(1, 'month')

        # Precipitation (Rainfall)
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        
        # Land Surface Temp (LST)
        lst = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer) \
                .map(lambda img: img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)) \
                .mean().clip(buffer)

        # Vegetation (NDVI)
        ndvi = ee.ImageCollection('COPERNICUS/S2_SR').filterDate(start, end).filterBounds(buffer) \
                .map(lambda img: img.normalizedDifference(['B8','B4'])) \
                .mean().clip(buffer)

        # Normalize and Calculate Risk
        slopeN = normalize(slope)
        twiN = normalize(twi)
        rainN = normalize(rain)
        lstN = normalize(lst)
        ndviN = normalize(ndvi.multiply(-1))

        vuln = (slopeN.multiply(0.2).add(twiN.multiply(0.25))
                .add(rainN.multiply(0.25)).add(lstN.multiply(0.15))
                .add(ndviN.multiply(0.15)))

        res = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        scores.append(list(res.values())[0] if res else 0)

        rain_res = rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        rain_vals.append(rain_res.get('precipitation', 0) if rain_res else 0)

        lst_res = lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        lst_vals.append(lst_res.get('ST_B10', 0) if lst_res else 0)

# ----------------------------------------------------------
# 5. DASHBOARD DISPLAY
# ----------------------------------------------------------
m_col1, m_col2 = st.columns(2)
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

with m_col1:
    st.metric("Avg Rainfall (May–Oct)", f"{avg_rain:.1f} mm")
with m_col2:
    st.metric("Avg Temperature", f"{avg_lst:.1f} °C")

st.subheader("📊 Monthly Vulnerability Trend")
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(months, scores, marker='o', color='#27ae60', linewidth=2)
ax.set_xticks(months)
ax.set_xticklabels(['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'])
ax.grid(True, linestyle='--', alpha=0.6)
st.pyplot(fig)

# Risk Level logic
latest_score = scores[-1]
if latest_score < 0.3:
    risk_text, color = "LOW", "green"
elif latest_score < 0.6:
    risk_text, color = "MODERATE", "orange"
else:
    risk_text, color = "HIGH", "red"

st.markdown(f"### Current Risk Status: :{color}[{risk_text}]")

# ----------------------------------------------------------
# 6. AI FARM ADVISOR (CHAT)
# ----------------------------------------------------------
st.divider()
st.subheader("🧠 AI Farm Advisor")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input Box
if prompt := st.chat_input("Ask about pest management or ginger health..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # Context building for GPT
        context = (f"Farm at {lat}, {lon}. Risk Score: {latest_score:.2f} ({risk_text}). "
                   f"Avg Rain: {avg_rain:.1f}mm. Avg Temp: {avg_lst:.1f}C.")
        
        # Using gpt-4o as it is the most stable version for 2026
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional agricultural consultant for ginger farming. Provide concise, actionable advice based on the climate data provided."},
                {"role": "user", "content": f"Data: {context}\n\nQuestion: {prompt}"}
            ],
            stream=True,
        )
        response = st.write_stream(stream)
    st.session_state.messages.append({"role": "assistant", "content": response})
