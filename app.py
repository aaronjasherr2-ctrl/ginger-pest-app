import streamlit as st
import ee

st.set_page_config(page_title="Ginger Early Warning", page_icon="🌱")

# 1. Connect to Earth Engine using your Secret Key
if "gcp_service_account" in st.secrets:
    secret_info = st.secrets["gcp_service_account"]
    credentials = ee.ServiceAccountCredentials(
        secret_info["client_email"], 
        key_data=secret_info["private_key"]
    )
    ee.Initialize(credentials)

st.title("🌱 Ginger Pest & Disease Early Warning System")
st.markdown("### Location: Badiangan, Iloilo")

# 2. Function to get REAL Rainfall for Badiangan center
def get_badiangan_rainfall():
    roi = ee.Geometry.Point([122.50, 10.98])
    # Pulling satellite rainfall data for the last 17 days
    dataset = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY") \
                .filterDate('2026-04-01', '2026-04-17') \
                .sum()
    value = dataset.reduceRegion(ee.Reducer.first(), roi, 5000).getInfo()
    return value.get('precipitation', 0)

# 3. Create the Dashboard UI
try:
    rain_amount = get_badiangan_rainfall()
    
    col1, col2 = st.columns(2)
    with col1:
        # High rainfall (>50mm) increases Bacterial Wilt risk in Badiangan
        risk_status = "HIGH" if rain_amount > 50 else "LOW"
        st.metric(label="Bacterial Wilt Risk", value=risk_status)
    with col2:
        st.metric(label="Total April Rainfall", value=f"{rain_amount:.2f} mm")

    st.success("Satellite data successfully pulled from Google Earth Engine!")

except Exception as e:
    st.warning("Awaiting satellite connection... Ensure your GEE Secrets are saved in Streamlit.")