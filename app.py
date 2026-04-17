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

# 2. High-Contrast Branding CSS
st.markdown(
    """
    <style>
    .stApp { background-color: #FFFFFF !important; }
    
    .club-header { 
        font-size: 3rem !important; 
        color: #008F52 !important; 
        font-weight: 800; 
        margin-bottom: 0px;
    }
    .sub-header { 
        font-size: 1.4rem !important; 
        color: #333333 !important; 
        font-weight: 600;
        margin-top: -10px;
    }
    
    div[data-testid="stMetricValue"] { color: #008F52 !important; font-weight: bold; }
    
    .risk-high { color: #D32F2F !important; font-weight: bold; font-size: 2.5rem; display: inline; }
    .risk-low { color: #388E3C !important; font-weight: bold; font-size: 2.5rem; display: inline; }
    
    hr { border-top: 3px solid #008F52; }
    </style>
    """,
    unsafe_allow_html=True
)

# 3. AGUSIPAN 4-H CLUB Header
col_logo, col_text = st.columns([1, 4])
with col_logo:
    st.image("https://upload.wikimedia.org/wikipedia/commons/9/9f/4-H_emblem.svg", width=120)

with col_text:
    st.markdown('<p class="club-header">AGUSIPAN 4-H CLUB</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Ginger Pest & Disease Early Warning System | Badiangan, Iloilo</p>', unsafe_allow_html=True)

st.divider()

# 4. GPS Tool
loc = get_geolocation()
if loc:
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
    st.success(f"📍 Field Coordinates Captured: {lat:.4f}, {lon:.4f}")
else:
    lat, lon = 10.98, 122.50
    st.info("📡 Locating field... Defaulting to Badiangan Town Center.")

# 5. Scientific Methodology
def get_weather_data(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    # Fetching 14-day history to ensure we see the rainfall trend
    dataset = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate('2026-04-03', '2026-04-17')
    
    total = dataset.sum().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    peak = dataset.max().reduceRegion(ee.Reducer.first(), roi, 5000).getInfo().get('precipitation', 0)
    return total, peak

total_mm, peak_mm = get_weather_data(lat, lon)

# 6. Vulnerability Results
st.markdown("### 📊 FIELD VULNERABILITY REPORT")
c1, c2, c3 = st.columns(3)

# Thresholds for Badiangan: High risk if 14-day total > 50mm OR any day > 20mm
is_high = (total_mm > 50) or (peak_mm > 20)

with c1:
    if is_high:
        st.markdown(f"**RISK LEVEL:** <p class='risk-high'>HIGH</p>", unsafe_allow_html=True)
        st.warning("Immediate field drainage inspection recommended.")
    else:
        st.markdown(f"**RISK LEVEL:** <p class='risk-low'>LOW</p>", unsafe_allow_html=True)
        st.success("Standard monitoring sufficient.")

with c2:
    st.metric("14-Day Cumulative Rain", f"{total_mm:.2f} mm")

with c3:
    st.metric("Peak Daily Intensity", f"{peak_mm:.2f} mm")

st.divider()

# 7. Map
st.map(data={'lat': [lat], 'lon': [lon]}, zoom=14)
st.caption("Developed for AGUSIPAN 4-H CLUB. Satellite Data processed via Google Earth Engine.")
