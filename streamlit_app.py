# streamlit_app.py
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import time
import google.generativeai as genai
import re

# ========== KONFIGURASI ==========
st.set_page_config(
    page_title="EduNudge AI - Smart Classroom",
    layout="wide",
    page_icon="🏫"
)

# ========== GAYA CSS TAMBAHAN ==========
st.markdown("""
<style>
html, body, [class*="css"] {
    font-family: 'Segoe UI', sans-serif;
}
h1 {
    font-size: 2.2rem !important;
}
h2 {
    font-size: 1.8rem !important;
}
.st-emotion-cache-1r4qj8v {
    padding: 2rem !important;
}
.metric-box {
    border-radius: 15px;
    padding: 1rem;
    background-color: #f5f7fa;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
}
.sidebar .css-1d391kg {
    padding-top: 2rem !important;
}
</style>
""", unsafe_allow_html=True)

# ========== GEMINI ENGINE ==========
class GeminiRecommendationEngine:
    def __init__(self):
        if 'GEMINI_API_KEY' not in st.secrets:
            st.error("API Key Gemini tidak ditemukan di secrets.toml")
            self.enabled = False
            return
        try:
            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
            available_models = [m.name for m in genai.list_models()]
            self.model_name = "models/gemini-1.5-pro-latest" if "models/gemini-1.5-pro-latest" in available_models else "models/gemini-pro"
            self.model = genai.GenerativeModel(self.model_name)
            self.enabled = True
        except Exception as e:
            st.error(f"Gagal inisialisasi Gemini: {str(e)}")
            self.enabled = False

    def generate_recommendations(self, sensor_data):
        if not self.enabled:
            return ["⚠️ Sistem rekomendasi AI tidak aktif"]

        latest = sensor_data[-1]
        try:
            prompt = f"""
            Buat 3 rekomendasi spesifik dan singkat untuk meningkatkan pembelajaran di kelas berdasarkan:
            - Suhu: {latest['temp']}°C
            - Kelembaban: {latest['hum']}%
            - Cahaya: {latest['light']}%
            - Kebisingan: {latest['sound']}%

            Format markdown dengan heading dan bullet point.
            """
            response = self.model.generate_content(prompt)
            return self._parse_recommendations(response.text)
        except Exception as e:
            st.error(f"Error: {str(e)}")
            return ["⚠️ Tidak dapat menghasilkan rekomendasi"]

    def _parse_recommendations(self, text):
        parts = [s.strip() for s in text.split("###") if s.strip()]
        return parts[:3] if parts else ["⚠️ Tidak ada data yang bisa ditampilkan"]

# ========== DASHBOARD ==========
def main():
    st.title("🏫 EduNudge AI – Smart Classroom Dashboard")
    engine = GeminiRecommendationEngine()

    with st.sidebar:
        st.header("⚙️ Konfigurasi")
        SERVER_URL = st.text_input("URL API Sensor", "http://localhost:5001")
        REFRESH_INTERVAL = st.slider("Interval Refresh (detik)", 5, 60, 15)
        st.markdown("### 🎯 Nilai Ideal")
        st.markdown("- 🌡️ Suhu: 22–26°C\n- 💧 Kelembaban: 40–60%\n- 💡 Cahaya: 40–70%\n- 🔊 Kebisingan: <45%")

    # Fetch Sensor Data
    sensor_data = fetch_sensor_data(SERVER_URL)
    if not sensor_data:
        st.warning("⏳ Menunggu data sensor...")
        time.sleep(3)
        st.rerun()

    df = pd.DataFrame(sensor_data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    st.markdown("### 🔍 Data Sensor Terkini")
    col1, col2, col3, col4 = st.columns(4)
    metrics = [
        ("🌡️ Suhu", "temp", (22, 26), col1),
        ("💧 Kelembaban", "hum", (40, 60), col2),
        ("💡 Cahaya", "light", (40, 70), col3),
        ("🔊 Kebisingan", "sound", (0, 45), col4),
    ]

    for label, key, (low, high), col in metrics:
        val = df.iloc[-1][key]
        color = "#34a853" if low <= val <= high else "#ea4335"
        with col:
            st.markdown(f"<div class='metric-box'><strong>{label}</strong><br><span style='font-size: 1.5rem; color:{color}'>{val:.1f}</span></div>", unsafe_allow_html=True)
            st.plotly_chart(create_sensor_gauge(val, label, (low, high)), use_container_width=True)

    st.markdown("## 🧠 Rekomendasi AI")

    if st.button("✨ Hasilkan Rekomendasi AI"):
        with st.spinner("Menganalisis kondisi kelas..."):
            st.session_state.recommendations = engine.generate_recommendations(sensor_data)
            st.session_state.show_recommendations = True

    if st.session_state.get("show_recommendations", False):
        with st.expander("📋 Lihat Rekomendasi Lengkap", expanded=True):
            for rec in st.session_state.get("recommendations", []):
                st.markdown(f"### {rec.splitlines()[0]}")
                for line in rec.splitlines()[1:]:
                    st.markdown(line)

    st.markdown("## 📈 Tren Data Sensor (24 Jam Terakhir)")
    fig = px.line(df.tail(24), x='timestamp', y=['temp', 'hum', 'light', 'sound'],
                 markers=True, title="Trend Lingkungan Kelas")
    st.plotly_chart(fig, use_container_width=True)

    # Auto-refresh
    time.sleep(REFRESH_INTERVAL)
    st.rerun()

# ========== FUNGSI BANTUAN ==========
@st.cache_data(ttl=10)
def fetch_sensor_data(server_url):
    try:
        res = requests.get(f"{server_url}/api/sensor/latest", timeout=3)
        return res.json()["data"] if res.status_code == 200 else []
    except:
        return []

def create_sensor_gauge(value, title, optimal_range):
    color = "#34a853" if optimal_range[0] <= value <= optimal_range[1] else "#ea4335"
    fig = px.bar(x=[value], title=f"{title} ({value:.1f})", color_discrete_sequence=[color])
    fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=40, b=20), height=150)
    fig.update_xaxes(range=[0, 100], visible=False)
    return fig

# ========== RUN APLIKASI ==========
if __name__ == "__main__":
    main()
