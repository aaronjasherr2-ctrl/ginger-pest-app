import streamlit as st
import ee
from streamlit_js_eval import get_geolocation

# 1. Page Setup
st.set_page_config(page_title="AGUSIPAN 4-H CLUB - Ginger System", page_icon="🍀", layout="wide")

# Connect to Earth Engine
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(secret_info["client_email"], key_data=secret_info["private_key"])
    ee.Initialize(credentials)

# 2. Enhanced Styling for White Background Contrast
st.markdown(
    """
    <style>
    /* Force high contrast for the white background */
    .stApp { background-color: #FFFFFF !important; }
    
    /* AGUSIPAN 4-H CLUB Header Styling */
    .club-header { 
        font-size: 3.5rem !important; 
        color: #008F52 !important; 
        font-weight: 800; 
        margin-bottom: -10px;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
    }
    .sub-header { 
        font-size: 1.5rem !important; 
        color: #333333 !important; 
        margin-top: 0;
        font-weight: 400;
    }
    
    /* Metric Styling */
    div[data-testid="stMetricValue"] { color: #008F52 !important; font-weight: bold; }
    div[data-testid="stMetricLabel"] { color: #555555 !important; }
    
    /* Risk Status Colors */
    .risk-high { color: #D32F2F !important; font-weight: bold; font-size: 2.5rem; }
    .risk-low { color: #388E3C !important; font-weight: bold; font-size: 2.5rem; }
    
    hr { border-top: 2px solid #008F52; }
    </style>
    """,
    unsafe_allow_html=True
)

# 3. Branding Header (Logo + Club Name)
col_logo, col_text = st.columns([1, 4])
with col_logo:
    # Using a clean version of the 4-H Clover
    st.image("https://upload.wikimedia.org/wikipedia/commons/9/9f/4-H_emblem.svg", width=120)

with col_text:
    st.markdown('<p class="club-header">AGUSIPAN 4-H CLUB</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Ginger Pest & Disease Early Warning System | Badiangan, Iloilo</p>', unsafe_allow_html=True)

st.divider()

# 4. GPS & Location
loc = get_geolocation()
if loc:
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
    st.success(f"📍 Analysis running for coordinates: {lat:.4f}, {lon:.4f}")
else:
    lat, lon = 10.98, 122.50
    st.info("📡 Locating your field... (Defaulting to Badiangan Center)")

# 5. Scientific Logic (Last 14 Days)
def get_weather_data(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    # Fetching 14-day history to avoid the 0mm "today" error
    dataset = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate('2026-04-03', '2026-04-17')
    
    total = dataset.sum().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    peak = dataset.max().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    return total, peak

total_mm, peak_mm = get_weather_data(lat, lon)

# 6. Dashboard Display
st.markdown("### 📊 FIELD VULNERABILITY REPORT")
c1, c2, c3 = st.columns(3)

# Thresholds: High risk if total > 50mm OR peak day > 20mm
is_high = (total_mm > 50) or (peak_mm > 20)

with c1:
    if is_high:
        st.markdown("**RISK LEVEL:** <p class="risk-high">HIGH</p>", unsafe_allow_html=True)
    else:
        st.markdown("**RISK LEVEL:** <p class="risk-low">LOW</p>", unsafe_allow_html=True)

with c2:
    st.metric("14-Day Total Rainfall", f"{total_mm:.2f} mm")

with c3:
    st.metric("Daily Intensity (Max)", f"{peak_mm:.2f} mm")

st.divider()

# 7. Map & Footer
st.map(data={'lat': [lat], 'lon': [lon]}, zoom=14)
st.caption("Powered by Google Earth Engine | Developed for the AGUSIPAN 4-H CLUB Undergraduate Thesis Research.")
