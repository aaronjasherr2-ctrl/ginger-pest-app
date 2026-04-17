import streamlit as st

st.set_page_config(page_title="Ginger Early Warning", page_icon="🌱")

st.title("🌱 Ginger Pest & Disease Early Warning System")
st.markdown("### Location: Badiangan, Iloilo")

st.info("This system uses satellite data to monitor environmental risks for Bacterial Wilt and Rhizome Rot.")

# Sidebar for inputs
st.sidebar.header("Farmer Controls")
farm_id = st.sidebar.text_input("Farm ID / Name", "Badiangan Farm 1")

# Mock Data for now (until we connect GEE)
col1, col2 = st.columns(2)
with col1:
    st.metric(label="Current Risk Level", value="LOW", delta="Stable")
with col2:
    st.metric(label="Recent Rainfall", value="12mm", delta="Below Threshold")

st.warning("⚠️ PRO-TIP: Always check your ginger rhizomes for yellowing after heavy rains.")
