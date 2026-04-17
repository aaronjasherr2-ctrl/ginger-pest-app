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
# Make sure "OPENAI_API_KEY" is in your Streamlit Secrets!
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Initialize Earth Engine with Key-Fix
try:
    if "gcp_service_account" in st.secrets:
        # The key fix: replace literal '\n' strings with actual newlines
        raw_key = st.secrets["gcp_service_account"]["private_key"]
        private_key = raw_key.replace("\\n", "\n")
        
        creds = ee.ServiceAccountCredentials(
            st.secrets["gcp_service_account"]["client_email"],
            key_data=private_key
        )
        ee.Initialize(creds)
    else:
        ee.Initialize()
except Exception as e:
    st.error(f"Earth Engine failed to initialize: {e}")
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
    # This tries to get the browser's GPS location
    loc = get_geolocation()
    if loc:
        lat = loc['coords']['latitude']
        lon = loc['coords']['longitude']
    else:
        lat, lon = 10.98, 122.50
        st.info("Waiting for GPS... using default coordinates for now.")

st.success(f"Using Location: {lat:.4f}, {lon:.4f}")

# Define Area of Interest
roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000)

# ----------------------------------------------------------
# 3. ANALYSIS FUNCTIONS
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
with st.spinner("Analyzing satellite data..."):
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

        # Calculate Vulnerability Index
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
# 5. DASHBOARD & VISUALS
# ----------------------------------------------------------
col1, col2 = st.columns(2)
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

with col1:
    st.metric("Avg Rainfall (May–Oct)", f"{avg_rain:.1f} mm")
with col2:
    st.metric("Avg Temp (May–Oct)", f"{avg_lst:.1f} °C")

st.subheader("📊 Monthly Risk Trend")
fig, ax = plt.subplots()
ax.plot(months, scores, marker='o', color='#e67e22', linewidth=2)
ax.set_xticks(months)
ax.set_xticklabels(['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'])
ax.set_ylabel("Risk Index")
st.pyplot(fig)

latest_score = scores[-1]
risk_level = "LOW" if latest_score < 0.3 else "MODERATE" if latest_score < 0.6 else "HIGH"
st.subheader(f"📍 Current Vulnerability Assessment: {risk_level}")

# ----------------------------------------------------------
# 6. AI FARM ADVISOR (CHAT)
# ----------------------------------------------------------
st.divider()
st.subheader("🧠 AI Farm Advisor")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input
if prompt := st.chat_input("Ask about ginger pests or soil health..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        context = f"Location: {lat}, {lon}. Recent Risk Score: {latest_score:.2f}. Avg Rain: {avg_rain:.1f}mm."
        
        # Use gpt-4o as a reliable production model
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful agricultural expert specializing in ginger farming. Use the context provided to give advice."},
                {"role": "user", "content": f"Context: {context}\n\nUser Question: {prompt}"}
            ],
            stream=True,
        )
        response = st.write_stream(stream)
    st.session_state.messages.append({"role": "assistant", "content": response})
