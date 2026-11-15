# ========================================================================
# Includes Polynomial Regression, Calibration of load cell, MQTT Broker
# --- EDITED: Added Zero-Lag Serial Sync, Safe E-Stop Disarm, Static
# Chart Persistence, CSV Export, and 8-Rotor eVTOL Extrapolation ---
# --- EDITED: Integrated Seaborn Statistical Suite ---
# --- EDITED: Added Automated Mission Profile (Autonomous Flight Cycle) ---
# --- EDITED: Added Two-Way Ansys Twin Builder Interface & MQTT Callbacks ---
# --- EDITED: Added Dedicated MQTT Broker Connection Section & Verifier ---
# ========================================================================
import streamlit as st
import paho.mqtt.client as mqtt
import serial
import pandas as pd
import json
import time
import numpy as np
import collections
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import seaborn as sns
import matplotlib.pyplot as plt

# ==========================================
# 1. PAGE CONFIGURATION & CUSTOM CSS
# ==========================================
st.set_page_config(page_title="DEP Digital Twin", layout="wide", initial_sidebar_state="expanded")

plt.style.use("dark_background")
sns.set_theme(style="darkgrid", rc={
    "axes.facecolor": "#121212",
    "figure.facecolor": "#0E1117",
    "grid.color": "#2A2A2A",
    "text.color": "#FFFFFF",
    "axes.labelcolor": "#CCCCCC",
    "xtick.color": "#CCCCCC",
    "ytick.color": "#CCCCCC"
})

st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    .ansys-header { color: #F2C94C; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("🚁 DEP Digital Twin Analytics Engine")
st.markdown("Real-time Bidirectional Cyber-Physical Telemetry Dashboard")

# ==========================================
# 2. STATE MANAGEMENT
# ==========================================
if 'data_buffer' not in st.session_state:
    st.session_state.data_buffer = collections.deque(maxlen=200)
if 'start_millis' not in st.session_state:
    st.session_state.start_millis = None
if 'is_running' not in st.session_state:
    st.session_state.is_running = False
if 'is_connected' not in st.session_state:
    st.session_state.is_connected = False
if 'estop_triggered' not in st.session_state:
    st.session_state.estop_triggered = False

# --- EDITED: Added state tracking for MQTT Verification ---
if 'mqtt_verified' not in st.session_state:
    st.session_state.mqtt_verified = False
# ----------------------------------------------------------

# Automated Mission Profile - State tracking
if 'mission_active' not in st.session_state:
    st.session_state.mission_active = False
if 'mission_start_time' not in st.session_state:
    st.session_state.mission_start_time = 0
if 'last_sent_pwm' not in st.session_state:
    st.session_state.last_sent_pwm = None

# Ansys Incoming Data State Tracking
if 'ansys_feedback' not in st.session_state:
    st.session_state.ansys_feedback = {"rom_temp_c": 0.0, "rom_predicted_thrust": 0.0, "rom_status": "Waiting..."}

# ==========================================
# 3. SIDEBAR CONTROL PANEL
# ==========================================

st.sidebar.header("⚙️ ESP32 System Control")
serial_port = st.sidebar.text_input("COM Port", value="COM6")
baud_rate = st.sidebar.selectbox("Baud Rate", [115200, 9600, 57600], index=0)

if st.sidebar.button("🔌 Connect to ESP32", use_container_width=True):
    try:
        test_ser = serial.Serial()
        test_ser.port = serial_port
        test_ser.baudrate = baud_rate
        test_ser.timeout = 0.1
        test_ser.setDTR(False)
        test_ser.setRTS(False)
        test_ser.open()
        test_ser.close()
        st.session_state.is_connected = True
        st.sidebar.success(f"✅ Successfully connected to {serial_port}")
    except Exception as e:
        st.session_state.is_connected = False
        st.sidebar.error(f"❌ Connection Failed: {e}")

st.sidebar.markdown("---")

# --- EDITED: Dedicated MQTT Broker Connection Section ---
st.sidebar.header("🌐 MQTT Broker Connection")
mqtt_broker_ip = st.sidebar.text_input("Broker IP Address", value="127.0.0.1")
mqtt_broker_port = st.sidebar.number_input("Broker Port", value=1883, step=1)

if st.sidebar.button("🔌 Verify MQTT Broker", use_container_width=True):
    try:
        # Briefly connect and disconnect to verify the broker is alive
        test_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Test_Connection")
        test_mqtt.connect(mqtt_broker_ip, mqtt_broker_port, keepalive=2)
        test_mqtt.disconnect()
        st.session_state.mqtt_verified = True
        st.sidebar.success(f"✅ Broker active at {mqtt_broker_ip}:{mqtt_broker_port}")
    except Exception as e:
        st.session_state.mqtt_verified = False
        st.sidebar.error("❌ Connection Refused: Ensure Mosquitto is running.")
# --------------------------------------------------------

st.sidebar.markdown("---")
col_start, col_stop = st.sidebar.columns(2)
if col_start.button("▶️ Start Link", use_container_width=True):
    if st.session_state.is_connected:
        st.session_state.is_running = True
        st.session_state.estop_triggered = False
    else:
        st.sidebar.error("⚠️ Please click 'Connect to ESP32' first!")

if col_stop.button("⏹️ Stop Link", use_container_width=True):
    st.session_state.is_running = False
    st.session_state.mission_active = False

if st.sidebar.button("🗑️ Clear Recorded Data", use_container_width=True):
    st.session_state.data_buffer.clear()
    st.session_state.start_millis = None

if len(st.session_state.data_buffer) > 0:
    export_df = pd.DataFrame(list(st.session_state.data_buffer))
    csv_bytes = export_df.to_csv(index=False).encode('utf-8')
    st.sidebar.download_button(
        label="📥 Export Telemetry CSV",
        data=csv_bytes,
        file_name=f"dep_telemetry_{int(time.time())}.csv",
        mime="text/csv",
        use_container_width=True
    )

st.sidebar.markdown("---")

st.sidebar.subheader("🤖 Automated Mission Profile")
if st.sidebar.button("▶️ Run Hover Cycle Test", use_container_width=True):
    if st.session_state.is_running:
        st.session_state.mission_active = True
        st.session_state.mission_start_time = time.time()
        st.session_state.last_sent_pwm = None
    else:
        st.sidebar.error("⚠️ Start Telemetry Link first!")

if st.session_state.mission_active:
    st.sidebar.success("✅ Mission Active: Hands off controls!")

st.sidebar.markdown("---")
st.sidebar.subheader("✈️ Flight Controls")

if 'pwm_slider' not in st.session_state:
    st.session_state.pwm_slider = 1000
if 'cal_input' not in st.session_state:
    st.session_state.cal_input = 1.0

if st.sidebar.button("🚨 EMERGENCY STOP", type="primary", use_container_width=True):
    st.session_state.pwm_slider = 1000
    target_pwm = 1000
    st.session_state.is_running = False
    st.session_state.estop_triggered = True
    st.session_state.mission_active = False

    try:
        emergency_ser = serial.Serial()
        emergency_ser.port = serial_port
        emergency_ser.baudrate = baud_rate
        emergency_ser.timeout = 0.1
        emergency_ser.setDTR(False)
        emergency_ser.setRTS(False)
        emergency_ser.open()

        cmd = {"pwm": 1000, "cal": st.session_state.cal_input, "tare": 0}
        emergency_ser.write((json.dumps(cmd) + '\n').encode())
        emergency_ser.flush()
        emergency_ser.close()
        st.sidebar.success("🚨 E-STOP TRIGGERED. Motor Disarmed (1000 PWM).")
    except Exception as e:
        st.sidebar.error(f"E-Stop Comms Failure: {e}")

target_pwm = st.sidebar.slider(
    "Throttle Override (PWM)",
    min_value=1000,
    max_value=2000,
    step=10,
    key="pwm_slider",
    disabled=st.session_state.mission_active
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚖️ Load Cell Calibration")

cal_factor = st.sidebar.number_input("Calibration Factor", step=1.0, format="%.2f", key="cal_input")

tare_requested = st.sidebar.button("Zero / Tare Scale", use_container_width=True)
if tare_requested:
    if target_pwm > 1000 or st.session_state.mission_active:
        st.sidebar.error("❌ Motor must be OFF (1000 PWM) to tare the scale.")
        tare_requested = False
    else:
        st.sidebar.warning("Taring Scale... (Please wait 2 seconds)")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Statistical Suite (Seaborn)")
live_seaborn = st.sidebar.checkbox("Render Seaborn Live (1 FPS)", value=False)

# ==========================================
# 4. UI LAYOUT PLACEHOLDERS
# ==========================================
st.markdown("<h4 class='ansys-header'>🌐 Physical Hardware Telemetry</h4>", unsafe_allow_html=True)
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
metric_thrust = kpi_col1.empty()
metric_power = kpi_col2.empty()
metric_current = kpi_col3.empty()
metric_efficiency = kpi_col4.empty()

st.markdown("---")
st.markdown("<h4 class='ansys-header'>🔮 Ansys Twin Builder Feedback (ROM Predictions)</h4>", unsafe_allow_html=True)
ansys_col1, ansys_col2, ansys_col3 = st.columns(3)
ansys_metric_status = ansys_col1.empty()
ansys_metric_temp = ansys_col2.empty()
ansys_metric_thrust = ansys_col3.empty()

evtol_banner = st.empty()

st.markdown("---")
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    transient_chart = st.empty()
    thrust_curve_chart = st.empty()
with chart_col2:
    electrical_chart = st.empty()
    efficiency_curve_chart = st.empty()

st.markdown("---")
st.subheader("📊 Seaborn Statistical Telemetry Analysis")
sns_col1, sns_col2 = st.columns(2)
with sns_col1:
    sns_heatmap_slot = st.empty()
with sns_col2:
    sns_regplot_slot = st.empty()


# ==========================================
# 5. CHART GENERATION & MQTT CALLBACKS
# ==========================================
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    client.subscribe("evtol/rotor1/predictions")
    st.session_state.ansys_feedback["rom_status"] = "Connected"


def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        if "rom_temp_c" in payload:
            st.session_state.ansys_feedback["rom_temp_c"] = payload["rom_temp_c"]
        if "rom_thrust_g" in payload:
            st.session_state.ansys_feedback["rom_predicted_thrust"] = payload["rom_thrust_g"]
    except Exception:
        pass


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
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['thrust_g'], mode='markers', name='Physical Thrust Data',
                             marker=dict(color='#00F0FF', size=5, opacity=0.5)))
    if len(df['pwm'].unique()) > 3:
        try:
            coeffs = np.polyfit(df['pwm'], df['thrust_g'], 2)
            poly_func = np.poly1d(coeffs)
            x_trend = np.linspace(df['pwm'].min(), df['pwm'].max(), 50)
            y_trend = poly_func(x_trend)
            fig.add_trace(go.Scatter(x=x_trend, y=y_trend, mode='lines', name='Physical Regression',
                                     line=dict(color='#FFFFFF', width=3, dash='solid')))
        except Exception:
            pass
    fig.update_layout(title="Aerodynamic Profile (Thrust Curve)", template="plotly_dark", height=350,
                      margin=dict(l=0, r=0, t=40, b=0), xaxis_title="PWM Signal (us)", yaxis_title="Thrust (g)")
    return fig


def get_efficiency_curve_fig(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['efficiency_g_W'], mode='markers', name='Live Sensor Data',
                             marker=dict(color='#00FF44', size=5, opacity=0.5)))
    if len(df['pwm'].unique()) > 3:
        clean_df = df[df['power_W'] > 1.0]
        if len(clean_df['pwm'].unique()) > 3:
            try:
                coeffs = np.polyfit(clean_df['pwm'], clean_df['efficiency_g_W'], 2)
                poly_func = np.poly1d(coeffs)
                x_trend = np.linspace(clean_df['pwm'].min(), clean_df['pwm'].max(), 50)
                y_trend = poly_func(x_trend)
                fig.add_trace(go.Scatter(x=x_trend, y=y_trend, mode='lines', name='Regression Curve',
                                         line=dict(color='#FFFFFF', width=3, dash='solid')))
            except Exception:
                pass
    fig.update_layout(title="System Efficiency Profile", template="plotly_dark", height=350,
                      margin=dict(l=0, r=0, t=40, b=0), xaxis_title="PWM Signal (us)", yaxis_title="Efficiency (g/W)")
    return fig


def get_seaborn_heatmap(df):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    cols = ['pwm', 'thrust_g', 'voltage', 'current_A', 'power_W', 'efficiency_g_W']
    corr = df[cols].corr().fillna(0)
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="mako", vmin=-1, vmax=1,
        ax=ax, cbar_kws={'shrink': 0.8}, linewidths=0.5, linecolor="#222222"
    )
    ax.set_title("Multi-Variate Parameter Correlation Matrix", color="white", fontsize=11, pad=12)
    fig.tight_layout()
    return fig


def get_seaborn_regplot(df):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    has_variance = len(df['pwm'].unique()) > 3
    sns.regplot(
        data=df, x='pwm', y='thrust_g',
        order=2 if has_variance else 1,
        fit_reg=has_variance,
        ax=ax,
        scatter_kws={'color': '#00F0FF', 'alpha': 0.6, 's': 25},
        line_kws={'color': '#FF0055', 'linewidth': 2}
    )
    ax.set_title("Seaborn Order-2 Polynomial Fit & 95% Confidence Band", color="white", fontsize=11, pad=12)
    ax.set_xlabel("PWM Command (us)")
    ax.set_ylabel("Thrust (g)")
    fig.tight_layout()
    return fig


def render_seaborn_ui(df):
    if len(df) > 2:
        fig_corr = get_seaborn_heatmap(df)
        sns_heatmap_slot.pyplot(fig_corr, use_container_width=True)
        plt.close(fig_corr)

        fig_reg = get_seaborn_regplot(df)
        sns_regplot_slot.pyplot(fig_reg, use_container_width=True)
        plt.close(fig_reg)
    else:
        sns_heatmap_slot.info("Waiting for >2 telemetry samples to compute Seaborn correlation matrix...")


def render_dashboard_ui(df, key_suffix):
    latest = df.iloc[-1]

    metric_thrust.metric("Thrust (g)", f"{latest['thrust_g']:.1f}")
    metric_power.metric("Power (W)", f"{latest['power_W']:.1f}")
    metric_current.metric("Current (A)", f"{latest['current_A']:.2f}", f"{latest['voltage']:.2f} V")
    metric_efficiency.metric("Efficiency (g/W)", f"{latest['efficiency_g_W']:.2f}")

    ansys_metric_status.metric("Co-Sim Status", st.session_state.ansys_feedback["rom_status"])
    ansys_metric_temp.metric("ROM Motor Temp", f"{st.session_state.ansys_feedback['rom_temp_c']:.1f} °C")

    phys_thrust = latest['thrust_g']
    virt_thrust = st.session_state.ansys_feedback['rom_predicted_thrust']
    dev = virt_thrust - phys_thrust if phys_thrust > 0 else 0
    ansys_metric_thrust.metric("ROM Predicted Thrust", f"{virt_thrust:.1f} g",
                               f"{dev:.1f} g error" if virt_thrust > 0 else None, delta_color="inverse")

    evtol_lift_kg = (latest['thrust_g'] * 8.0) / 1000.0
    evtol_power_kw = (latest['power_W'] * 8.0) / 1000.0
    poly_str = "Sweep across >3 throttle steps to generate real-time 2nd-degree polynomial model..."
    if len(df['pwm'].unique()) > 3:
        try:
            c = np.polyfit(df['pwm'], df['thrust_g'], 2)
            poly_str = f"Fitted Twin Model: Thrust(g) = ({c[0]:.4e})·PWM² + ({c[1]:.3f})·PWM + ({c[2]:.1f})"
        except Exception:
            pass

    mission_status = "🟢 AUTONOMOUS HOVER CYCLE ACTIVE" if st.session_state.mission_active else "🛸 8-Rotor eVTOL Virtual Extrapolation"

    evtol_banner.info(
        f"**{mission_status}:** Projected Total Lift: **`{evtol_lift_kg:.2f} kg`** | "
        f"Projected Total Power: **`{evtol_power_kw:.2f} kW`** | `{poly_str}`"
    )

    transient_chart.plotly_chart(get_transient_fig(df), use_container_width=True, key=f"transient_{key_suffix}")
    electrical_chart.plotly_chart(get_electrical_fig(df), use_container_width=True, key=f"elec_{key_suffix}")
    thrust_curve_chart.plotly_chart(get_thrust_curve_fig(df), use_container_width=True, key=f"thrust_{key_suffix}")
    efficiency_curve_chart.plotly_chart(get_efficiency_curve_fig(df), use_container_width=True, key=f"eff_{key_suffix}")


# ==========================================
# 6. MAIN TELEMETRY LOOP
# ==========================================
if st.session_state.is_running:
    ser = None
    mqtt_client = None
    mqtt_connected = False

    try:
        ser = serial.Serial()
        ser.port = serial_port
        ser.baudrate = baud_rate
        ser.timeout = 0.05
        ser.setDTR(False)
        ser.setRTS(False)
        ser.open()

        ser.reset_input_buffer()

        if not st.session_state.mission_active:
            cmd_payload = {"pwm": target_pwm, "cal": st.session_state.cal_input, "tare": 1 if tare_requested else 0}
            ser.write((json.dumps(cmd_payload) + '\n').encode())
            ser.flush()

        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "DEP_Dashboard_Node")
            mqtt_client.on_connect = on_mqtt_connect
            mqtt_client.on_message = on_mqtt_message
            mqtt_client.connect(mqtt_broker_ip, mqtt_broker_port, keepalive=60)
            mqtt_client.loop_start()
            mqtt_connected = True
        except Exception:
            st.session_state.ansys_feedback["rom_status"] = "Offline"
            st.sidebar.warning(f"⚠️ MQTT Broker not found at {mqtt_broker_ip}:{mqtt_broker_port}")

        last_ui_update = time.time()
        last_sns_update = time.time()

        while st.session_state.is_running:
            try:
                if st.session_state.mission_active:
                    elapsed = time.time() - st.session_state.mission_start_time
                    new_pwm = 1000

                    if elapsed < 5.0:
                        new_pwm = 1200
                    elif elapsed < 8.0:
                        new_pwm = 1800
                    elif elapsed < 18.0:
                        new_pwm = 1500
                    elif elapsed < 22.0:
                        new_pwm = 1200
                    else:
                        new_pwm = 1000
                        st.session_state.mission_active = False

                    if st.session_state.last_sent_pwm != new_pwm:
                        mission_cmd = {"pwm": new_pwm, "cal": st.session_state.cal_input, "tare": 0}
                        ser.write((json.dumps(mission_cmd) + '\n').encode())
                        ser.flush()
                        st.session_state.last_sent_pwm = new_pwm

                if ser.in_waiting > 250:
                    ser.reset_input_buffer()

                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    payload = json.loads(line)

                    if mqtt_connected:
                        mqtt_client.publish("evtol/rotor1/telemetry", json.dumps(payload))

                    if st.session_state.start_millis is None:
                        st.session_state.start_millis = payload['time']

                    time_s = (payload['time'] - st.session_state.start_millis) / 1000.0
                    eff = payload['thrust_g'] / payload['power_W'] if payload['power_W'] > 0.5 else 0.0

                    st.session_state.data_buffer.append({
                        'time_s': time_s, 'thrust_g': payload['thrust_g'], 'voltage': payload['voltage'],
                        'current_A': payload['current_A'], 'power_W': payload['power_W'],
                        'pwm': payload['pwm'], 'efficiency_g_W': eff
                    })
                else:
                    time.sleep(0.002)

            except (json.JSONDecodeError, KeyError, ValueError):
                pass

            current_time = time.time()
            if current_time - last_ui_update > 0.2 and len(st.session_state.data_buffer) > 0:
                df = pd.DataFrame(list(st.session_state.data_buffer))
                render_dashboard_ui(df, key_suffix=f"{current_time}")
                last_ui_update = current_time

                if live_seaborn and (current_time - last_sns_update > 1.0):
                    render_seaborn_ui(df)
                    last_sns_update = current_time

    except Exception as e:
        st.error(f"Serial Connection Failed: {e}")
        st.session_state.is_running = False
        st.session_state.is_connected = False
        st.session_state.mission_active = False

    finally:
        if ser is not None and ser.is_open:
            try:
                if st.session_state.estop_triggered:
                    kill_cmd = {"pwm": 1000, "cal": st.session_state.cal_input, "tare": 0}
                    ser.write((json.dumps(kill_cmd) + '\n').encode())
                    ser.flush()
            except Exception:
                pass
            ser.close()
        if mqtt_connected and mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

elif len(st.session_state.data_buffer) > 0:
    df_paused = pd.DataFrame(list(st.session_state.data_buffer))
    render_dashboard_ui(df_paused, key_suffix="paused_state")
    render_seaborn_ui(df_paused)