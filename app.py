import streamlit as st
import ee
from streamlit_js_eval import get_geolocation

# 1. Page Configuration
st.set_page_config(page_title="Ginger Early Warning - Badiangan", page_icon="🌱", layout="wide")

# Connect to Earth Engine
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(secret_info["client_email"], key_data=secret_info["private_key"])
    ee.Initialize(credentials)

# Professional Header CSS - Fixing the 4-H Green (#008F52) theme
st.markdown(
    """
    <style>
    .big-title { font-size: 2.5rem !important; color: #008F52 !important; font-weight: bold; margin-bottom: 0; }
    .risk-high { color: #cc0000 !important; font-weight: bold; }
    .risk-low { color: #008F52 !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { color: #008F52 !important; }
    .stApp { background-color: #ffffff; }
    </style>
    """,
    unsafe_allow_html=True
)

# Header with 4-H Logo
col_log, col_tit = st.columns([1, 5])
with col_log:
    # Using the official 4-H vector for high quality
    st.image("https://upload.wikimedia.org/wikipedia/commons/9/9f/4-H_emblem.svg", width=100)
with col_tit:
    st.markdown('<p class="big-title">Ginger Pest & Disease Early Warning System</p>', unsafe_allow_html=True)
    st.write("### 4-H Club Decision Support Tool | Badiangan, Iloilo")

st.divider()

# 2. GPS Location Tool
loc = get_geolocation()
if loc:
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
    st.success(f"📍 Analysis for coordinates: {lat:.4f}, {lon:.4f}")
else:
    lat, lon = 10.98, 122.50  # Default to Badiangan Center
    st.info("🛰️ Waiting for GPS... Defaulting to Badiangan Town Center.")

# 3. Scientific Methodology (Cumulative Rain)
def get_assessment(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    # Analyze the last 14 days for a better vulnerability trend
    dataset = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate('2026-04-03', '2026-04-17')
    
    total_rain = dataset.sum().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    max_rain = dataset.max().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    
    return total_rain, max_rain

total_mm, max_mm = get_assessment(lat, lon)

# 4. Results Dashboard
st.markdown("#### field vulnerability report")
c1, c2, c3 = st.columns(3)

# ABE Logic: High risk if 14-day total > 50mm OR any single day > 20mm
is_high = (total_mm > 50) or (max_mm > 20)

with c1:
    status = "HIGH" if is_high else "LOW"
    color_class = "risk-high" if is_high else "risk-low"
    st.markdown(f"Risk Level: <p class='{color_class}' style='font-size:2.5rem; margin:0;'>{status}</p>", unsafe_allow_html=True)

with c2:
    st.metric("14-Day Cumulative Rain", f"{total_mm:.2f} mm")

with c3:
    st.metric("Max Daily Intensity", f"{max_mm:.2f} mm")

st.divider()
st.map(data={'lat': [lat], 'lon': [lon]}, zoom=13)
st.caption("Developed for Badiangan Ginger Farmers. Data powered by Google Earth Engine.")
