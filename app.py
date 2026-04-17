import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from openai import OpenAI

# ----------------------------------------------------------
# INIT & CONFIG
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# 1. Setup OpenAI (Use a valid model name like 'gpt-4o')
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 2. Earth Engine Initialization
if "gcp_service_account" in st.secrets:
    creds = ee.ServiceAccountCredentials(
        st.secrets["gcp_service_account"]["client_email"],
        key_data=st.secrets["gcp_service_account"]["private_key"]
    )
    ee.Initialize(creds)
else:
    ee.Initialize()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")

# ----------------------------------------------------------
# LOCATION INPUT
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
        # Fallback defaults
        lat, lon = 10.98, 122.50
        st.info("Waiting for GPS... using default coordinates.")

st.success(f"Using Location: {lat:.4f}, {lon:.4f}")

roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000)

# ----------------------------------------------------------
# BASE DATA & NORMALIZATION
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
# MONTHLY ANALYSIS
# ----------------------------------------------------------
st.info("🔄 Running Earth Engine analysis. Please wait...")

year = 2023
months = list(range(5, 11))
scores, rain_vals, lst_vals = [], [], []

for m in months:
    start = ee.Date.fromYMD(year, m, 1)
    end = start.advance(1, 'month')

    # Rainfall
    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
    
    # Temperature (LST)
    lst = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer) \
            .map(lambda img: img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15)) \
            .mean().clip(buffer)

    # Vegetation (NDVI)
    ndvi = ee.ImageCollection('COPERNICUS/S2_SR').filterDate(start, end).filterBounds(buffer) \
            .map(lambda img: img.normalizedDifference(['B8','B4'])) \
            .mean().clip(buffer)

    # Risk Scoring
    slopeN = normalize(slope)
    twiN = normalize(twi)
    rainN = normalize(rain)
    lstN = normalize(lst)
    ndviN = normalize(ndvi.multiply(-1))

    vuln = (slopeN.multiply(0.2).add(twiN.multiply(0.25))
            .add(rainN.multiply(0.25)).add(lstN.multiply(0.15))
            .add(ndviN.multiply(0.15)))

    val = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
    scores.append(list(val.values())[0])

    rain_vals.append(rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo().get('precipitation', 0))
    lst_vals.append(lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo().get('ST_B10', 0))

# ----------------------------------------------------------
# DASHBOARD DISPLAY
# ----------------------------------------------------------
col1, col2 = st.columns(2)
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

with col1:
    st.metric("Avg Rainfall (May–Oct)", f"{avg_rain:.1f} mm")
with col2:
    st.metric("Avg LST (May–Oct)", f"{avg_lst:.1f} °C")

st.subheader("📊 Monthly Risk Trend")
fig, ax = plt.subplots()
ax.plot(months, scores, marker='o', color='#2ecc71')
ax.set_xlabel("Month")
ax.set_ylabel("Risk Index")
st.pyplot(fig)

latest_score = scores[-1]
risk_level = "LOW" if latest_score < 0.3 else "MODERATE" if latest_score < 0.6 else "HIGH"
st.subheader(f"📍 Current Risk: {risk_level}")

# ----------------------------------------------------------
# AI CHATBOT
# ----------------------------------------------------------
st.divider()
st.subheader("🧠 AI Farm Advisor")

if "chat" not in st.session_state:
    st.session_state.chat = []

user_input = st.chat_input("Ask about your ginger farm...")

if user_input:
    context = f"Lat: {lat}, Lon: {lon}. Monthly risk scores: {scores}. Avg rain: {avg_rain}mm. Avg temp: {avg_lst}C."
    
    # Note: Using 'gpt-4o' as 'gpt-5-mini' is not available
    response = client.chat.completions.create(
        model="gpt-4o", 
        messages=[
            {"role": "system", "content": "You are an agricultural expert helping ginger farmers."},
            {"role": "user", "content": f"Context: {context} \nQuestion: {user_input}"}
        ]
    )

    reply = response.choices[0].message.content
    st.session_state.chat.append(("You", user_input))
    st.session_state.chat.append(("AI", reply))

for speaker, msg in st.session_state.chat:
    with st.chat_message("user" if speaker == "You" else "assistant"):
        st.write(msg)
