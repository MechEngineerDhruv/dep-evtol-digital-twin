import streamlit as st
import serial
import pandas as pd
import json
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==========================================
# 1. PAGE CONFIGURATION & CUSTOM CSS
# ==========================================
st.set_page_config(page_title="DEP Digital Twin", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for a cleaner, professional metric card look
st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    </style>
""", unsafe_allow_html=True)

st.title("🚁 DEP Digital Twin Analytics Engine")
st.markdown("Real-time Bidirectional Cyber-Physical Telemetry Dashboard")

# ==========================================
# 2. STATE MANAGEMENT
# ==========================================
if 'data' not in st.session_state:
    st.session_state.data = pd.DataFrame(
        columns=['time_s', 'thrust_g', 'voltage', 'current_A', 'power_W', 'pwm', 'efficiency_g_W'])
if 'start_millis' not in st.session_state:
    st.session_state.start_millis = None
if 'is_running' not in st.session_state:
    st.session_state.is_running = False

# ==========================================
# 3. SIDEBAR CONTROL PANEL
# ==========================================
st.sidebar.header("⚙️ System Control")
serial_port = st.sidebar.text_input("COM Port", value="COM3")
baud_rate = st.sidebar.selectbox("Baud Rate", [115200, 9600, 57600], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("Flight Controls")

# Emergency Stop overrides everything and kills the motor instantly
if st.sidebar.button("🚨 EMERGENCY STOP", type="primary", use_container_width=True):
    target_pwm = 1000
    st.session_state.is_running = False
    try:
        emergency_ser = serial.Serial(serial_port, baud_rate, timeout=0.1)
        emergency_ser.write(f"1000\n".encode())
        emergency_ser.close()
        st.sidebar.success("E-STOP TRIGGERED. Motor Disarmed.")
    except Exception as e:
        st.sidebar.error(f"E-Stop Comms Failure: {e}")
else:
    target_pwm = st.sidebar.slider("Throttle Override (PWM)", min_value=1000, max_value=2000, value=1000, step=10)

if st.sidebar.button("▶️ Start Telemetry Link", use_container_width=True):
    st.session_state.is_running = True

if st.sidebar.button("⏹️ Stop Link", use_container_width=True):
    st.session_state.is_running = False

# ==========================================
# 4. UI LAYOUT PLACEHOLDERS
# ==========================================
# Top Row: KPI Metrics
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
metric_thrust = kpi_col1.empty()
metric_power = kpi_col2.empty()
metric_current = kpi_col3.empty()
metric_efficiency = kpi_col4.empty()

st.markdown("---")

# Bottom Rows: Plotly Graphs
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    transient_chart = st.empty()
    thrust_curve_chart = st.empty()
with chart_col2:
    electrical_chart = st.empty()
    efficiency_curve_chart = st.empty()


# ==========================================
# 5. CHART GENERATION FUNCTIONS (PLOTLY)
# ==========================================
def get_transient_fig(df):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df['time_s'], y=df['thrust_g'], name='Thrust (g)', mode='lines',
                             line=dict(color='#00F0FF', width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df['time_s'], y=df['power_W'], name='Power (W)', mode='lines',
                             line=dict(color='#FF0055', width=2)), secondary_y=True)
    fig.update_layout(title="Transient Response", template="plotly_dark", height=350, margin=dict(l=0, r=0, t=40, b=0))
    fig.update_yaxes(title_text="Thrust (g)", secondary_y=False)
    fig.update_yaxes(title_text="Power (W)", secondary_y=True)
    return fig


def get_electrical_fig(df):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=df['time_s'], y=df['current_A'], name='Current (A)', mode='lines',
                             line=dict(color='#FFB300', width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=df['time_s'], y=df['voltage'], name='Voltage (V)', mode='lines',
                             line=dict(color='#B300FF', width=2)), secondary_y=True)
    fig.update_layout(title="Electrical Health", template="plotly_dark", height=350, margin=dict(l=0, r=0, t=40, b=0))
    fig.update_yaxes(title_text="Current (A)", secondary_y=False)
    fig.update_yaxes(title_text="Voltage (V)", secondary_y=True)
    return fig


def get_thrust_curve_fig(df):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=df['pwm'], y=df['thrust_g'], mode='markers', marker=dict(color='#00F0FF', size=6, opacity=0.7)))
    fig.update_layout(title="Aerodynamic Profile (PWM vs Thrust)", template="plotly_dark", height=350,
                      margin=dict(l=0, r=0, t=40, b=0), xaxis_title="PWM Signal (us)", yaxis_title="Thrust (g)")
    return fig


def get_efficiency_curve_fig(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['efficiency_g_W'], mode='markers',
                             marker=dict(color='#00FF44', size=6, opacity=0.7)))
    fig.update_layout(title="System Efficiency Profile (PWM vs g/W)", template="plotly_dark", height=350,
                      margin=dict(l=0, r=0, t=40, b=0), xaxis_title="PWM Signal (us)", yaxis_title="Efficiency (g/W)")
    return fig


# ==========================================
# 6. MAIN TELEMETRY LOOP
# ==========================================
if st.session_state.is_running:
    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=0.1)
        ser.write(f"{target_pwm}\n".encode())  # Send initial PWM

        last_ui_update = time.time()

        while st.session_state.is_running:
            # 1. Read Serial Hardware
            try:
                line = ser.readline().decode('utf-8').strip()
                if line:
                    payload = json.loads(line)

                    # Establish relative time zero-point
                    if st.session_state.start_millis is None:
                        st.session_state.start_millis = payload['time']

                    time_s = (payload['time'] - st.session_state.start_millis) / 1000.0

                    # Safely calculate efficiency
                    eff = payload['thrust_g'] / payload['power_W'] if payload['power_W'] > 0.5 else 0.0

                    # Package row
                    new_data = {
                        'time_s': time_s, 'thrust_g': payload['thrust_g'], 'voltage': payload['voltage'],
                        'current_A': payload['current_A'], 'power_W': payload['power_W'],
                        'pwm': payload['pwm'], 'efficiency_g_W': eff
                    }
                    new_row = pd.DataFrame([new_data])

                    # Append and truncate to last 200 data points to prevent memory bloat
                    st.session_state.data = pd.concat([st.session_state.data, new_row], ignore_index=True)
                    if len(st.session_state.data) > 200:
                        st.session_state.data = st.session_state.data.iloc[1:]

            except json.JSONDecodeError:
                pass  # Ignore cut-off serial lines

            # 2. UI Update Throttler (Updates Visuals at 5 FPS)
            current_time = time.time()
            if current_time - last_ui_update > 0.2 and not st.session_state.data.empty:
                df = st.session_state.data

                # Update KPI Metrics
                metric_thrust.metric("Thrust (g)", f"{df['thrust_g'].iloc[-1]:.1f}")
                metric_power.metric("Power (W)", f"{df['power_W'].iloc[-1]:.1f}")
                metric_current.metric("Current (A)", f"{df['current_A'].iloc[-1]:.2f}",
                                      f"{df['voltage'].iloc[-1]:.2f} V")
                metric_efficiency.metric("Efficiency (g/W)", f"{df['efficiency_g_W'].iloc[-1]:.2f}")

                # Render Plotly Charts
                transient_chart.plotly_chart(get_transient_fig(df), use_container_width=True)
                electrical_chart.plotly_chart(get_electrical_fig(df), use_container_width=True)
                thrust_curve_chart.plotly_chart(get_thrust_curve_fig(df), use_container_width=True)
                efficiency_curve_chart.plotly_chart(get_efficiency_curve_fig(df), use_container_width=True)

                last_ui_update = current_time

            # Sleep slightly to prevent CPU max-out, aligning with the 50Hz ESP32 output
            time.sleep(0.01)

    except Exception as e:
        st.error(f"Serial Connection Failed: {e}")
        st.session_state.is_running = False