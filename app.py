st.write(st.secrets)
import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from openai import OpenAI

# ----------------------------------------------------------
# INIT
# ----------------------------------------------------------
st.set_page_config(layout="wide")

# OpenAI
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Earth Engine
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
# LOCATION INPUT (NEW FEATURE)
# ----------------------------------------------------------
st.subheader("📍 Location Selection")

use_manual = st.toggle("Enter coordinates manually")

if use_manual:
    lat = st.number_input("Latitude", value=10.98)
    lon = st.number_input("Longitude", value=122.50)
else:
    loc = get_geolocation()
    if loc:
        lat = loc['coords']['latitude']
        lon = loc['coords']['longitude']
    else:
        lat, lon = 10.98, 122.50

st.success(f"Using Location: {lat:.4f}, {lon:.4f}")

roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000)

# ----------------------------------------------------------
# BASE DATA
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
# MONTHLY ANALYSIS (AUTO)
# ----------------------------------------------------------
year = 2023
months = list(range(5, 11))

scores = []
rain_vals = []
lst_vals = []

for m in months:

    start = ee.Date.fromYMD(year, m, 1)
    end = start.advance(1, 'month')

    rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
        .filterDate(start, end).sum().clip(buffer)

    lst = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterDate(start, end) \
        .filterBounds(buffer) \
        .map(lambda img: img.select('ST_B10')
             .multiply(0.00341802)
             .add(149.0)
             .subtract(273.15)) \
        .mean().clip(buffer)

    ndvi = ee.ImageCollection('COPERNICUS/S2_SR') \
        .filterDate(start, end) \
        .filterBounds(buffer) \
        .map(lambda img: img.normalizedDifference(['B8','B4'])) \
        .mean().clip(buffer)

    # Normalize
    slopeN = normalize(slope)
    twiN = normalize(twi)
    rainN = normalize(rain)
    lstN = normalize(lst)
    ndviN = normalize(ndvi.multiply(-1))

    vuln = (
        slopeN.multiply(0.2)
        .add(twiN.multiply(0.25))
        .add(rainN.multiply(0.25))
        .add(lstN.multiply(0.15))
        .add(ndviN.multiply(0.15))
    )

    val = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
    score = list(val.values())[0]

    scores.append(score)

    rain_vals.append(
        rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo().get('precipitation', 0)
    )

    lst_vals.append(
        lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo().get('ST_B10', 0)
    )

# ----------------------------------------------------------
# AVERAGES
# ----------------------------------------------------------
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

st.metric("Avg Rainfall (May–Oct)", f"{avg_rain:.1f} mm")
st.metric("Avg LST (May–Oct)", f"{avg_lst:.1f} °C")

# ----------------------------------------------------------
# GRAPH (NEW)
# ----------------------------------------------------------
st.subheader("📊 Monthly Risk Trend")

fig, ax = plt.subplots()
ax.plot(months, scores, marker='o')
ax.set_xlabel("Month")
ax.set_ylabel("Risk Index")
ax.set_title("Monthly Vulnerability Trend")

st.pyplot(fig)

# ----------------------------------------------------------
# CURRENT MONTH MAP (AUTO = LAST MONTH)
# ----------------------------------------------------------
latest_score = scores[-1]

if latest_score < 0.3:
    risk = "LOW"
elif latest_score < 0.6:
    risk = "MODERATE"
else:
    risk = "HIGH"

st.subheader(f"📍 Current Risk (Latest Month): {risk}")

# ----------------------------------------------------------
# GPT CHATBOT (REAL AI)
# ----------------------------------------------------------
st.subheader("🧠 AI Farm Advisor")

if "chat" not in st.session_state:
    st.session_state.chat = []

user_input = st.text_input("Ask your question:")

if user_input:

    context = f"""
    Location: {lat}, {lon}
    Monthly risk scores: {scores}
    Average rainfall: {avg_rain}
    Average temperature: {avg_lst}
    """

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "You are an agricultural expert helping ginger farmers."},
            {"role": "user", "content": context + user_input}
        ]
    )

    reply = response.choices[0].message.content

    st.session_state.chat.append(("You", user_input))
    st.session_state.chat.append(("AI", reply))

for speaker, msg in st.session_state.chat:
    st.write(f"**{speaker}:** {msg}")
