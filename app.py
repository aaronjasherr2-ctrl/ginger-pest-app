import streamlit as st
import ee
from streamlit_js_eval import get_geolocation

# 1. Page Configuration and Theming
st.set_page_config(page_title="Ginger Early Warning - Badiangan", page_icon="🌱", layout="wide")

# Connect to Earth Engine
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(secret_info["client_email"], key_data=secret_info["private_key"])
    ee.Initialize(credentials)

# Professional Header with 4-H Logo (image_10.png)
logo_url = "https://upload.wikimedia.org/wikipedia/commons/9/9f/4-H_emblem.svg" # Using a placeholder for your local logo path

# CSS to enforce Green (#008F52) and White contrast for branding
st.markdown(
    """
    <style>
    .big-title { font-size: 3rem !important; color: #008F52 !important; font-weight: bold; }
    .risk-high { color: #cc0000 !important; font-weight: bold; }
    .risk-low { color: #008F52 !important; font-weight: bold; }
    div[data-testid="stMetricValue"] { color: #008F52 !important; }
    div[data-testid="stMetricLabel"] { font-size: 1.1rem !important; }
    [data-testid="stHeader"] { background-color: rgba(0,0,0,0); }
    .stApp { background-color: #ffffff; }
    </style>
    """,
    unsafe_allow_stdio=True
)

# Header with Logo
col_log, col_tit = st.columns([1, 5])
with col_log:
    st.image(logo_url, width=120)
with col_tit:
    st.markdown('<p class="big-title">Ginger Pest & Disease Early Warning System</p>', unsafe_allow_html=True)
    st.markdown("### Decision Support System for Badiangan, Iloilo")

st.divider()

# 2. Get GPS Location
st.markdown("#### 📍 Field Tool")
loc = get_geolocation()

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"Targeting Field: {lat:.4f}, {lon:.4f}")
else:
    lat, lon = 10.98, 122.50
    st.info("GPS locating... Defaulting to Badiangan Center coordinates.")

# 3. New Spatiotemporal Methodology
def get_assessment(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    
    # Analyze cumulative moisture (Last 10 days) and intensity (last 24h)
    dataset = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate('2026-04-07', '2026-04-17')
    
    # Last 10 days cumulative rain
    cumulative = dataset.sum()
    # Most intense single day in that period
    intensity = dataset.max()

    # Reducers
    stats_cumul = cumulative.reduceRegion(ee.Reducer.first(), roi, 5000).getInfo()
    stats_intens = intensity.reduceRegion(ee.Reducer.first(), roi, 5000).getInfo()
    
    return {
        'total': stats_cumul.get('precipitation', 0),
        'max_day': stats_intens.get('precipitation', 0)
    }

data = get_assessment(lat, lon)
rain_total = data['total']
rain_max = data['max_day']

# 4. Results Dashboard in 4-H Theme
st.divider()
st.markdown("#### Vulnerability Report")

col1, col2, col3 = st.columns(3)

# Define logical threshold for Ginger in Badiangan soil types
risk_threshold_cumul = 50.0  # >50mm cumulative
risk_threshold_intens = 15.0 # >15mm in 24h

is_high_risk = (rain_total > risk_threshold_cumul) or (rain_max > risk_threshold_intens)

with col1:
    status = "HIGH RISK" if is_high_risk else "LOW RISK"
    class_name = "risk-high" if is_high_risk else "risk-low"
    st.markdown(f"**Current Status:** <p class='{class_name}' style='font-size:3rem; margin:0;'>{status}</p>", unsafe_allow_html=True)
    if is_high_risk:
        st.warning("Action: Check fields for yellowing; ensure adequate soil drainage.")
    else:
        st.success("Safe: Standard monitoring recommended.")

with col2:
    st.metric(label="Total Moisture (Last 10 Days)", value=f"{rain_total:.2f} mm", help=f"High risk if > {risk_threshold_cumul}mm")

with col3:
    st.metric(label="Max 24h Intensity", value=f"{rain_max:.2f} mm", help=f"High risk if > {risk_threshold_intens}mm")

st.divider()
# Use 4-H Green and White contrast for the map as well
st.markdown("#### Field View")
st.map(data={'lat': [lat], 'lon': [lon]}, zoom=12)

# Footer and scientific verification
col_fot1, col_fot2 = st.columns([1,1])
with col_fot1:
    st.image(logo_url, width=100)
with col_fot2:
    st.caption("A decision support tool for Badiangan, Iloilo. Satellite Data: CHIRPS Daily Rainfall via Google Earth Engine.")
    st.caption("Pest Model: Cumulative and Intensity Thresholding for Rhizome Rot Risk.")
