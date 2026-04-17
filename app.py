import streamlit as st
import ee
from streamlit_js_eval import get_geolocation
from datetime import datetime, timedelta

# 1. Page Setup
st.set_page_config(page_title="AGUSIPAN 4-H CLUB - Ginger System", page_icon="🍀", layout="wide")

# Connect to Earth Engine
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(secret_info["client_email"], key_data=secret_info["private_key"])
    ee.Initialize(credentials)
else:
    ee.Initialize()  # Fallback for local/dev

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

# 3. AGUSIPAN 4-H CLUB Header with your custom logo
col_logo, col_text = st.columns([1, 4])
with col_logo:
    st.image("agusipan_logo.png", width=150)  # ← Your custom logo here
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
    lat, lon = 10.98, 122.50  # Badiangan default
    st.info("📡 Locating field... Defaulting to Badiangan Town Center.")

# 5. Improved Scientific Methodology - Multi-parameter Pattern Analysis
def get_weather_data(lati, longi):
    roi = ee.Geometry.Point([longi, lati])
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    # Rainfall - CHIRPS
    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(start_str, end_str)
    total_rain = chirps.sum().reduceRegion(ee.Reducer.sum(), roi, 5000).getInfo().get('precipitation', 0)
    max_daily_rain = chirps.max().reduceRegion(ee.Reducer.max(), roi, 5000).getInfo().get('precipitation', 0)
    
    # Temperature - CHIRTS (good for daily max/min)
    chirts = ee.ImageCollection("UCSB-CHG/CHIRTS/DAILY").filterDate(start_str, end_str)
    mean_tmax = chirts.mean().reduceRegion(ee.Reducer.mean(), roi, 5000).getInfo().get('Tmax', None)
    mean_tmin = chirts.mean().reduceRegion(ee.Reducer.mean(), roi, 5000).getInfo().get('Tmin', None)
    
    # Basic humidity proxy (dewpoint depression from ERA5 if available, or simplify)
    # For simplicity we use temperature + rain as strong proxy for disease risk
    
    return {
        'total_rain': total_rain or 0,
        'max_daily_rain': max_daily_rain or 0,
        'mean_tmax': mean_tmax,
        'mean_tmin': mean_tmin,
        'start_date': start_str,
        'end_date': end_str
    }

weather = get_weather_data(lat, lon)

# Risk Assessment Logic (based on ginger disease favorable conditions)
total_mm = weather['total_rain']
peak_mm = weather['max_daily_rain']
tmax = weather['mean_tmax']
tmin = weather['mean_tmin']

# High risk if: heavy rain + warm temps (23-30°C optimal for many pathogens) + recent wet pattern
is_high = (
    (total_mm > 60) or 
    (peak_mm > 25) or 
    (tmax is not None and 23 <= tmax <= 32 and total_mm > 40)
)

st.markdown("### 📊 FIELD VULNERABILITY REPORT (14-day pattern analysis)")
st.caption(f"Period: {weather['start_date']} to {weather['end_date']}")

c1, c2, c3, c4 = st.columns(4)

with c1:
    if is_high:
        st.markdown(f"**RISK LEVEL:** <p class='risk-high'>HIGH</p>", unsafe_allow_html=True)
        st.warning("⚠️ Conditions favorable for rhizome rot, soft rot, leaf spot & bacterial wilt. Improve drainage immediately.")
    else:
        st.markdown(f"**RISK LEVEL:** <p class='risk-low'>LOW</p>", unsafe_allow_html=True)
        st.success("✅ Current patterns low risk. Continue regular monitoring.")

with c2:
    st.metric("14-Day Cumulative Rain", f"{total_mm:.1f} mm", help="High cumulative rain promotes soil-borne diseases")
with c3:
    st.metric("Peak Daily Rain", f"{peak_mm:.1f} mm", help="Heavy single-day rain increases splash dispersal of pathogens")
with c4:
    if tmax is not None:
        st.metric("Avg Daily Max Temp", f"{tmax:.1f} °C")
    else:
        st.metric("Avg Daily Max Temp", "N/A")

st.divider()

# Additional insights
st.markdown("### 🌡️ Key Environmental Insights")
insights = []
if total_mm > 50:
    insights.append("High rainfall in last 14 days — favorable for fungal and bacterial diseases.")
if tmax and 24 <= tmax <= 30:
    insights.append("Warm temperatures (optimal range for many ginger pathogens).")
if peak_mm > 20:
    insights.append("Intense rain events detected — watch for waterlogging.")

for insight in insights:
    st.info(insight)

st.divider()

# 6. Map
st.map(data={'lat': [lat], 'lon': [lon]}, zoom=14)
st.caption("Developed for AGUSIPAN 4-H CLUB • Satellite Data via Google Earth Engine • Ginger disease risk based on rainfall patterns, temperature, and known pathogen favorable conditions.")
