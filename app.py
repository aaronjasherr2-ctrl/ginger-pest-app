import streamlit as st
import ee
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="Ginger Early Warning", page_icon="🌱")

# 1. Connect to Earth Engine
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(secret_info["client_email"], key_data=secret_info["private_key"])
    ee.Initialize(credentials)

st.title("🌱 Ginger Pest & Disease Early Warning System")

# 2. Get GPS Location
st.markdown("### 📍 Field Selection")
loc = get_geolocation()

# Default to Badiangan center if GPS isn't ready
lat, lon = 10.98, 122.50 

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"Targeting your current field: {lat:.4f}, {lon:.4f}")
else:
    st.info("Searching for GPS... (Make sure location is ON). Defaulting to Badiangan Center.")

# 3. Satellite Analysis Function
def get_vulnerability(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    # Last 17 days of rainfall
    data = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate('2026-04-01', '2026-04-17').sum()
    stats = data.reduceRegion(ee.Reducer.first(), roi, 5000).getInfo()
    return stats.get('precipitation', 0)

# 4. Results Dashboard
rain = get_vulnerability(lat, lon)
col1, col2 = st.columns(2)

with col1:
    # Based on your ABE research for Badiangan soils
    status = "HIGH" if rain > 50 else "LOW"
    st.metric(label="Risk Level", value=status)

with col2:
    st.metric(label="Recent Rainfall", value=f"{rain:.2f} mm")

st.map(data={'lat': [lat], 'lon': [lon]}, zoom=12)

st.caption("Data source: NASA/UCSB CHIRPS Satellite Imagery processed via Google Earth Engine.")
