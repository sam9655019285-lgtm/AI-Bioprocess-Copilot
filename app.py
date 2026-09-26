import streamlit as st

st.set_page_config(page_title="AI Bioprocess Copilot", page_icon="🧬", layout="wide")

st.title("AI Bioprocess Copilot")
st.caption("Monitor fermentation performance and get operational recommendations.")

with st.sidebar:
    st.header("Process Inputs")
    biomass = st.slider("Biomass (g/L)", 0.0, 80.0, 25.0, step=0.5)
    substrate = st.slider("Substrate (g/L)", 0.0, 200.0, 85.0, step=1.0)
    do = st.slider("Dissolved oxygen (%)", 0.0, 100.0, 48.0, step=1.0)
    ph = st.slider("pH", 4.0, 9.0, 6.8, step=0.1)
    temperature = st.slider("Temperature (°C)", 15.0, 45.0, 30.0, step=0.5)
    feed_rate = st.slider("Feed rate (%)", 0.0, 100.0, 60.0, step=1.0)

    if st.button("Generate Recommendation"):
        st.session_state["recommendation_ready"] = True

if st.session_state.get("recommendation_ready"):
    productivity = 0.8 * (biomass / 30) + 0.6 * (substrate / 100) + 0.3 * (do / 60) - 0.5 * abs(ph - 6.8) - 0.2 * abs(temperature - 30)
    productivity = max(0.0, min(productivity, 1.0))

    st.subheader("Live Process Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Estimated Yield", f"{productivity * 100:.1f}%")
    col2.metric("DO Status", "Healthy" if do > 35 else "Low")
    col3.metric("pH Status", "In range" if 6.2 <= ph <= 7.4 else "Adjust")
    col4.metric("Feed Profile", "Balanced" if feed_rate < 80 else "Aggressive")

    st.subheader("Recommendation")
    if do < 30:
        recommendation = "Increase aeration to improve oxygen transfer and avoid metabolic slowdown."
    elif ph < 6.2:
        recommendation = "Raise pH slightly using a controlled base addition to remain within the optimal growth window."
    elif ph > 7.4:
        recommendation = "Reduce pH drift and verify buffering capacity to avoid stress on the culture."
    elif temperature > 33:
        recommendation = "Reduce heating load or improve cooling to protect productivity and cell viability."
    else:
        recommendation = "Maintain current operating conditions; productivity is stable and near target."

    st.info(recommendation)

    st.subheader("Process Insights")
    with st.expander("View rule-based model assumptions"):
        st.write(
            "This prototype uses a lightweight heuristic model for demonstration purposes. "
            "It evaluates biomass, substrate, dissolved oxygen, pH, temperature, and feed load to estimate process health."
        )
else:
    st.subheader("Welcome")
    st.write(
        "Start by adjusting the process parameters in the sidebar and click 'Generate Recommendation' "
        "to simulate an AI bioprocess advisory output."
    )

    st.markdown(
        """
        ### Example operating targets
        - Biomass: 20–40 g/L
        - DO: 30–60%
        - pH: 6.2–7.4
        - Temperature: 28–32°C
        """
    )
