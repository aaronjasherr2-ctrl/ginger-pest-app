import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from datetime import datetime

# ----------------------------------------------------------
# INIT
# ----------------------------------------------------------
st.set_page_config(layout="wide")

if "gcp_service_account" in st.secrets:
    creds = ee.ServiceAccountCredentials(
        st.secrets["gcp_service_account"]["client_email"],
        key_data=st.secrets["gcp_service_account"]["private_key"]
    )
    ee.Initialize(creds)
else:
    ee.Initialize()

# ----------------------------------------------------------
# UI
# ----------------------------------------------------------
st.title("🌱 AGUSIPAN GINGER VULNERABILITY SYSTEM")

# ----------------------------------------------------------
# LOCATION
# ----------------------------------------------------------
loc = get_geolocation()

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
else:
    lat, lon = 10.98, 122.50

roi = ee.Geometry.Point([lon, lat])
buffer = roi.buffer(1000)  # 1 KM RADIUS

# ----------------------------------------------------------
# BASE DATA
# ----------------------------------------------------------
dem = ee.Image('USGS/SRTMGL1_003').clip(buffer)
slope = ee.Terrain.slope(dem)
twi = dem.focal_mean(3).add(1).log().divide(slope.add(1))

def normalize(img):
    stats = img.reduceRegion(
        ee.Reducer.minMax(),
        buffer,
        100,
        maxPixels=1e9
    )
    band = img.bandNames().get(0)
    minv = ee.Number(stats.get(ee.String(band).cat('_min')))
    maxv = ee.Number(stats.get(ee.String(band).cat('_max')))
    return img.subtract(minv).divide(maxv.subtract(minv).max(0.0001))

# ----------------------------------------------------------
# MONTH SELECTOR
# ----------------------------------------------------------
month = st.selectbox("Select Month", [5,6,7,8,9,10])

year = 2023
start = ee.Date.fromYMD(year, month, 1)
end = start.advance(1, 'month')

# ----------------------------------------------------------
# DATA LAYERS
# ----------------------------------------------------------
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

# ----------------------------------------------------------
# VULNERABILITY MODEL
# ----------------------------------------------------------
vuln = (
    slopeN.multiply(0.2)
    .add(twiN.multiply(0.25))
    .add(rainN.multiply(0.25))
    .add(lstN.multiply(0.15))
    .add(ndviN.multiply(0.15))
)

vuln_class = (
    ee.Image(0)
    .where(vuln.lt(0.3), 1)
    .where(vuln.gte(0.3).And(vuln.lt(0.6)), 2)
    .where(vuln.gte(0.6), 3)
).clip(buffer)

# ----------------------------------------------------------
# MAP VISUALIZATION
# ----------------------------------------------------------
vis = {
    'min': 1,
    'max': 3,
    'palette': ['2dc937','e7b416','cc3232']
}

map_id = vuln_class.getMapId(vis)

m = folium.Map(location=[lat, lon], zoom_start=14)

folium.TileLayer(
    tiles=map_id['tile_fetcher'].url_format,
    attr='GEE',
    name='Vulnerability'
).add_to(m)

folium.Circle([lat, lon], radius=1000, color='blue', fill=False).add_to(m)

folium.LayerControl().add_to(m)

st_folium(m, width=700, height=500)

# ----------------------------------------------------------
# LEGEND
# ----------------------------------------------------------
st.markdown("""
### Legend
🟢 Low  
🟡 Moderate  
🔴 High  
""")

# ----------------------------------------------------------
# RISK VALUE (MEAN INSIDE 1KM)
# ----------------------------------------------------------
mean_val = vuln.reduceRegion(
    ee.Reducer.mean(),
    buffer,
    100
).getInfo()

score = list(mean_val.values())[0]

if score < 0.3:
    risk = "LOW"
elif score < 0.6:
    risk = "MODERATE"
else:
    risk = "HIGH"

st.subheader(f"📍 1km Radius Risk: {risk} ({score:.2f})")

# ----------------------------------------------------------
# EXPORT
# ----------------------------------------------------------
if st.button("Download GeoTIFF"):
    task = ee.batch.Export.image.toDrive(
        image=vuln_class,
        description='Ginger_Vulnerability',
        scale=30,
        region=buffer,
        maxPixels=1e9
    )
    task.start()
    st.success("Export started! Check your Google Drive.")

# ----------------------------------------------------------
# SIMPLE AI ADVISOR
# ----------------------------------------------------------
st.subheader("🤖 AI Advisor")

if risk == "HIGH":
    st.warning("Improve drainage, apply fungicide, avoid waterlogging.")
elif risk == "MODERATE":
    st.info("Monitor field, improve aeration.")
else:
    st.success("Low risk, maintain practices.")
