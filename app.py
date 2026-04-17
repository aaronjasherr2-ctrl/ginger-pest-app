import streamlit as st
import ee
import folium
import matplotlib.pyplot as plt
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from openai import OpenAI
import os

# ----------------------------------------------------------
# 1. INITIALIZATION & AUTHENTICATION
# ----------------------------------------------------------
st.set_page_config(layout="wide", page_title="Agusipan Smart Ginger System")

# Logo Handling
if os.path.exists("agusipan_logo.png"):
    st.image("agusipan_logo.png", width=180)
else:
    st.warning("Logo file 'agusipan_logo.png' not found in directory.")

# Initialize OpenAI
# AuthenticationError usually means your key is invalid or your balance is zero.
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", ""))

# Initialize Earth Engine with your Service Account
try:
    if "gcp_service_account" in st.secrets:
        # We use the key exactly as stored in your Secrets
        creds = ee.ServiceAccountCredentials(
            st.secrets["gcp_service_account"]["client_email"],
            key_data=st.secrets["gcp_service_account"]["private_key"]
        )
        ee.Initialize(creds)
    else:
        ee.Initialize()
except Exception as e:
    st.error("🚨 Earth Engine failed to initialize.")
    st.info("Check your Streamlit Secrets for the correct private_key format and ensure the EE API is enabled.")
    st.stop()

st.title("🌱 AGUSIPAN SMART GINGER SYSTEM")
st.markdown("#### **Official Decision Support System of AGUSIPAN 4H CLUB**")

# ----------------------------------------------------------
# 2. LOCATION SELECTION (1km Radius)
# ----------------------------------------------------------
st.subheader("📍 Area of Interest (1km Radius Analysis)")

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
        lat, lon = 10.98, 122.50
        st.info("Waiting for GPS signal... Using default center point.")

st.success(f"Scanning 1km radius around: {lat:.4f}, {lon:.4f}")

# Define Area of Interest (Strict 1km Buffer)
roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000) 

# ----------------------------------------------------------
# 3. ANALYSIS UTILITIES
# ----------------------------------------------------------
def normalize(img, area):
    stats = img.reduceRegion(ee.Reducer.minMax(), area, 100, maxPixels=1e9)
    band = img.bandNames().get(0)
    minv = ee.Number(stats.get(ee.String(band).cat('_min')))
    maxv = ee.Number(stats.get(ee.String(band).cat('_max')))
    # Safety divide to avoid zero-division errors
    return img.subtract(minv).divide(maxv.subtract(minv).max(0.0001))

# ----------------------------------------------------------
# 4. DATA PROCESSING (SATELLITE PIPELINE)
# ----------------------------------------------------------
with st.spinner("Processing satellite imagery and climate data..."):
    # Historical Window for analysis
    year = 2023
    months = list(range(5, 11)) # May to Oct
    month_names = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
    
    scores, rain_vals, lst_vals = [], [], []

    # Static GIS Layers
    dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
    slope = ee.Terrain.slope(dem)
    twi = dem.focal_mean(3).add(1).log().divide(slope.add(1))

    for m in months:
        start = ee.Date.fromYMD(year, m, 1)
        end = start.advance(1, 'month')

        # 1. Rainfall (CHIRPS Daily)
        rain = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(start, end).sum().clip(buffer)
        
        # 2. Surface Temperature (Landsat 8 - Corrected Scale)
        lst_col = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(start, end).filterBounds(buffer)
        
        if lst_col.size().getInfo() > 0:
            # Landsat 8 C2 L2 ST_B10 Scaling: DN * 0.00341802 + 149.0
            lst = lst_col.map(lambda img: img.select('ST_B10')
                    .multiply(0.00341802).add(149.0)
                    .subtract(273.15)) \
                    .mean().clip(buffer)
        else:
            lst = ee.Image(27.0).clip(buffer) # Regional fallback average

        # 3. Vegetation Index (NDVI)
        ndvi = ee.ImageCollection('COPERNICUS/S2_SR').filterDate(start, end).filterBounds(buffer) \
                .map(lambda img: img.normalizedDifference(['B8','B4'])) \
                .mean().clip(buffer)

        # 4. Vulnerability Score Normalization
        slopeN = normalize(slope, buffer)
        twiN = normalize(twi, buffer)
        rainN = normalize(rain, buffer)
        lstN = normalize(lst, buffer)
        ndviN = normalize(ndvi.multiply(-1), buffer) # Invert NDVI (low veg = higher risk)

        # Multi-Criteria Weighted Overlay
        vuln = (slopeN.multiply(0.2).add(twiN.multiply(0.25))
                .add(rainN.multiply(0.25)).add(lstN.multiply(0.15))
                .add(ndviN.multiply(0.15)))

        # Average results for the month
        res = vuln.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        scores.append(list(res.values())[0] if res else 0)

        rain_res = rain.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        rain_vals.append(rain_res.get('precipitation', 0) if rain_res else 0)

        lst_res = lst.reduceRegion(ee.Reducer.mean(), buffer, 1000).getInfo()
        # Ensure we don't get negative data from fallback or processing
        temp_val = list(lst_res.values())[0] if lst_res else 27.0
        lst_vals.append(temp_val if temp_val > 0 else 27.0)

# ----------------------------------------------------------
# 5. DASHBOARD DISPLAY
# ----------------------------------------------------------
st.divider()
col_a, col_b = st.columns(2)
avg_rain = sum(rain_vals) / len(rain_vals)
avg_lst = sum(lst_vals) / len(lst_vals)

with col_a:
    st.metric("Avg Rainfall (1km Buffer)", f"{avg_rain:.1f} mm")
with col_b:
    st.metric("Avg Surface Temp", f"{avg_lst:.1f} °C")

# Trend Chart
st.subheader("📊 Vulnerability & Risk Trend")
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(month_names, scores, marker='o', color='#2ecc71', linewidth=3, markersize=8)
ax.fill_between(month_names, scores, color='#2ecc71', alpha=0.1)
ax.set_ylabel("Risk Index")
ax.set_ylim(0, 1)
st.pyplot(fig)

# Assessment
latest_score = scores[-1]
if latest_score < 0.35:
    risk_level, color = "LOW", "green"
elif latest_score < 0.65:
    risk_level, color = "MODERATE", "orange"
else:
    risk_level, color = "HIGH", "red"

st.markdown(f"### 🎯 Current Environmental Risk: :{color}[{risk_level}]")

# ----------------------------------------------------------
# 6. AGUSIPAN AI: AUTOMATED REPORT & RECOMMENDATION
# ----------------------------------------------------------
st.divider()
st.subheader("🤖 AGUSIPAN AI Farmer's Report")

# Check for OpenAI Key before calling
if not st.secrets.get("OPENAI_API_KEY"):
    st.error("OpenAI API Key is missing. Please add it to Streamlit Secrets.")
else:
    try:
        report_context = (
            f"Farmer Location: Lat {lat}, Lon {lon}. "
            f"Risk Level: {risk_level} (Index: {latest_score:.2f}). "
            f"Climate Stats: Avg Rain {avg_rain:.1f}mm, Avg Temp {avg_lst:.1f}C. "
            f"Period: Ginger Planting/Growing Season (May-Oct)."
        )

        with st.status("AI Generating customized recommendations...", expanded=True):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a senior agricultural expert for the AGUSIPAN 4H CLUB. Your task is to analyze environmental data for ginger farmers. Summarize the current risk and provide specific, actionable recommendations (pest control, irrigation, soil health) in a clear, bulleted format."},
                    {"role": "user", "content": f"Analyze this data and provide a farmer's report: {report_context}"}
                ]
            )
            report = response.choices[0].message.content
            st.markdown(report)
            
    except Exception as e:
        st.warning("⚠️ AI Recommendation engine is currently unavailable.")
        # Fallback recommendations if AI fails due to authentication/billing
        st.info("Manual Recommendation: Based on your current risk level, ensure proper drainage (for High Rain) or mulching (for High Temp). Consult your local AGUSIPAN 4H CLUB representative for local pest alerts.")
