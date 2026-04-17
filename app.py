import streamlit as st
import ee
from streamlit_js_eval import get_geolocation
from datetime import datetime, timedelta

# ----------------------------------------------------------
# 1. PAGE SETUP
# ----------------------------------------------------------
st.set_page_config(
    page_title="AGUSIPAN 4-H CLUB - Ginger System",
    page_icon="🍀",
    layout="wide"
)

# ----------------------------------------------------------
# 2. CONNECT TO EARTH ENGINE
# ----------------------------------------------------------
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(
        secret_info["client_email"],
        key_data=secret_info["private_key"]
    )
    ee.Initialize(credentials)
else:
    ee.Initialize()

# ----------------------------------------------------------
# 3. FIXED UI (WHITE BACKGROUND + READABLE TEXT)
# ----------------------------------------------------------
st.markdown("""
<style>
.stApp { background-color: #FFFFFF !important; }

body, p, span, div, label {
    color: #222222 !important;
}

.club-header {
    font-size: 3rem;
    color: #008F52;
    font-weight: 800;
}

.sub-header {
    font-size: 1.3rem;
    color: #444444;
    font-weight: 600;
}

div[data-testid="stMetricValue"] {
    color: #008F52 !important;
    font-weight: bold;
}

.risk-high { color: #D32F2F; font-size: 2.5rem; font-weight: bold; }
.risk-moderate { color: #E7B416; font-size: 2.5rem; font-weight: bold; }
.risk-low { color: #2DC937; font-size: 2.5rem; font-weight: bold; }

hr { border-top: 3px solid #008F52; }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# 4. HEADER
# ----------------------------------------------------------
col_logo, col_text = st.columns([1, 4])

with col_logo:
    st.image("agusipan_logo.png", width=140)

with col_text:
    st.markdown('<p class="club-header">AGUSIPAN 4-H CLUB</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Ginger Pest & Disease Early Warning System</p>', unsafe_allow_html=True)

st.divider()

# ----------------------------------------------------------
# 5. GPS LOCATION
# ----------------------------------------------------------
loc = get_geolocation()

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    st.success(f"📍 Location: {lat:.4f}, {lon:.4f}")
else:
    lat, lon = 10.98, 122.50
    st.info("📡 Using default location (Badiangan)")

# ----------------------------------------------------------
# 6. WEATHER DATA (GEE)
# ----------------------------------------------------------
def get_weather(lati, longi):
    roi = ee.Geometry.Point([longi, lati])

    end = datetime.now()
    start = end - timedelta(days=14)

    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
        .filterDate(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))

    total_rain = chirps.sum().reduceRegion(
        ee.Reducer.sum(), roi, 5000
    ).getInfo().get('precipitation', 0)

    max_rain = chirps.max().reduceRegion(
        ee.Reducer.max(), roi, 5000
    ).getInfo().get('precipitation', 0)

    chirts = ee.ImageCollection("UCSB-CHG/CHIRTS/DAILY") \
        .filterDate(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))

    tmax = chirts.mean().reduceRegion(
        ee.Reducer.mean(), roi, 5000
    ).getInfo().get('Tmax', None)

    return total_rain or 0, max_rain or 0, tmax

total_mm, peak_mm, tmax = get_weather(lat, lon)

# ----------------------------------------------------------
# 7. GEE-LIKE VULNERABILITY MODEL
# ----------------------------------------------------------
def normalize(val, min_val, max_val):
    if max_val - min_val == 0:
        return 0
    return (val - min_val) / (max_val - min_val)

# Baseline (approximation of annual)
BASE_RAIN = 120
BASE_TEMP = 28

rain_anom = total_mm / BASE_RAIN
temp_anom = (tmax - BASE_TEMP) if tmax else 0

rainN = normalize(rain_anom, 0, 2)
tempN = normalize(temp_anom, -5, 5)

veg_stress = normalize(total_mm - 30, 0, 100)

# Static approximations
slopeN = 0.5
twiN = 0.5

# Weighted model (SAME as your GEE)
vuln = (
    (slopeN * 0.2) +
    (twiN * 0.25) +
    (rainN * 0.25) +
    (tempN * 0.15) +
    (veg_stress * 0.15)
)

# Classification
if vuln < 0.3:
    risk_label = "LOW"
    risk_class = "risk-low"
elif vuln < 0.6:
    risk_label = "MODERATE"
    risk_class = "risk-moderate"
else:
    risk_label = "HIGH"
    risk_class = "risk-high"

# ----------------------------------------------------------
# 8. DISPLAY
# ----------------------------------------------------------
st.markdown("### 📊 FIELD VULNERABILITY REPORT")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(f"<p class='{risk_class}'>{risk_label}</p>", unsafe_allow_html=True)

    if risk_label == "HIGH":
        st.warning("⚠️ High disease risk. Improve drainage and apply preventive measures.")
    elif risk_label == "MODERATE":
        st.warning("⚠️ Moderate risk. Monitor closely.")
    else:
        st.success("✅ Low risk. Maintain practices.")

with c2:
    st.metric("14-Day Rainfall", f"{total_mm:.1f} mm")

with c3:
    st.metric("Peak Rainfall", f"{peak_mm:.1f} mm")

with c4:
    st.metric("Temperature", f"{tmax:.1f} °C" if tmax else "N/A")

st.divider()

# ----------------------------------------------------------
# 9. MAP
# ----------------------------------------------------------
st.map({'lat': [lat], 'lon': [lon]}, zoom=14)

st.caption("Powered by Google Earth Engine | AGUSIPAN 4-H CLUB")
