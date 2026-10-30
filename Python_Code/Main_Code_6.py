# ========================================================================
# --- Includes Polynomial Regression, Calibration of load cell, MQTT Broker
# and a dedicated Connect Button for ESP32 ---
# --- Added Zero-Lag Serial Sync, Safe E-Stop Disarm, Static
# Chart Persistence, CSV Export, and 8-Rotor eVTOL Extrapolation ---
# --- Integrated Seaborn Statistical Suite (Correlation Heatmap &
# Order-2 Regplot with Confidence Intervals) + Memory-Leak Protection ---
# ========================================================================
import streamlit as st
import paho.mqtt.client as mqtt
import serial
import pandas as pd
import json
import time
import numpy as np
# --- EDITED: Imported 'collections' to use 'deque' for the high-speed memory buffer ---
import collections
import plotly.graph_objects as go
from plotly.subplots import make_subplots
# --- EDITED: Imported Seaborn and Matplotlib for statistical telemetry analysis ---
import seaborn as sns
import matplotlib.pyplot as plt

# ==========================================
# 1. PAGE CONFIGURATION & CUSTOM CSS
# ==========================================
st.set_page_config(page_title="DEP Digital Twin", layout="wide", initial_sidebar_state="expanded")

# --- EDITED: Configure global dark-mode styling for Seaborn & Matplotlib charts ---
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
    </style>
""", unsafe_allow_html=True)

st.title("🚁 DEP Digital Twin Analytics Engine")
st.markdown("Real-time Bidirectional Cyber-Physical Telemetry Dashboard")

# ==========================================
# 2. STATE MANAGEMENT
# ==========================================
# --- EDITED: Replaced the heavy Pandas DataFrame with a lightning-fast O(1) deque buffer.
# This prevents RAM exhaustion when updating at 50Hz. ---
if 'data_buffer' not in st.session_state:
    st.session_state.data_buffer = collections.deque(maxlen=200)

if 'start_millis' not in st.session_state:
    st.session_state.start_millis = None
if 'is_running' not in st.session_state:
    st.session_state.is_running = False
# --- NEW CODE: Add connection state tracking ---
if 'is_connected' not in st.session_state:
    st.session_state.is_connected = False
# -----------------------------------------------
# --- EDITED: Added state flag to safely trigger E-Stop inside the active serial port ---
if 'estop_triggered' not in st.session_state:
    st.session_state.estop_triggered = False

# ==========================================
# 3. SIDEBAR CONTROL PANEL
# ==========================================

# ----------------- SYSTEM CONTROL ----------------------------

st.sidebar.header("⚙️ System Control")
serial_port = st.sidebar.text_input("COM Port", value="COM6")
baud_rate = st.sidebar.selectbox("Baud Rate", [115200, 9600, 57600], index=0)

# --- NEW CODE: Separate Connect Button to Verify ESP32 COM Port ---
if st.sidebar.button("🔌 Connect to ESP32", use_container_width=True):
    try:
        # --- EDITED: Set DTR/RTS to False BEFORE opening test port so testing doesn't reboot ESP32 ---
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
# ------------------------------------------------------------------

st.sidebar.markdown("---")

# --------------- START LINK, STOP LINK AND CSV EXPORT ------------------------------
# --- EDITED CODE: Enforce COM connection before allowing Telemetry Link to Start ---
col_start, col_stop = st.sidebar.columns(2)
if col_start.button("▶️ Start Link", use_container_width=True):
    if st.session_state.is_connected:
        st.session_state.is_running = True
        st.session_state.estop_triggered = False
    else:
        st.sidebar.error("⚠️ Please click 'Connect to ESP32' first!")

if col_stop.button("⏹️ Stop Link", use_container_width=True):
    st.session_state.is_running = False

# --- EDITED: Added Reset Buffer & CSV Export buttons for empirical throttle sweeps ---
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

# ------------------------------------------------------------------

st.sidebar.markdown("---")

# -------------------- FLIGHT CONTROLS -----------------------------

st.sidebar.subheader("✈️ Flight Controls")

# --- EDITED: Initialize slider and calibration state so E-Stop can safely reset/read them ---
if 'pwm_slider' not in st.session_state:
    st.session_state.pwm_slider = 1000
if 'cal_input' not in st.session_state:
    st.session_state.cal_input = 1.0

if st.sidebar.button("🚨 EMERGENCY STOP", type="primary", use_container_width=True):
    st.session_state.pwm_slider = 1000  # Visually snaps slider back to 1000 PWM
    target_pwm = 1000
    st.session_state.is_running = False
    st.session_state.estop_triggered = True
    try:
        # --- EDITED: Cleanly sends kill command when loop is not holding the port, or after loop cleanup ---
        emergency_ser = serial.Serial()
        emergency_ser.port = serial_port
        emergency_ser.baudrate = baud_rate
        emergency_ser.timeout = 0.1
        emergency_ser.setDTR(False)
        emergency_ser.setRTS(False)
        emergency_ser.open()

        # Send emergency kill JSON while preserving active calibration factor
        cmd = {"pwm": 1000, "cal": st.session_state.cal_input, "tare": 0}
        emergency_ser.write((json.dumps(cmd) + '\n').encode())
        emergency_ser.flush()
        emergency_ser.close()
        st.sidebar.success("🚨 E-STOP TRIGGERED. Motor Disarmed (1000 PWM).")
    except Exception as e:
        st.sidebar.error(f"E-Stop Comms Failure: {e}")

# --- EDITED: Keep slider outside 'else' so it stays visible and snaps to 1000 on E-Stop ---
target_pwm = st.sidebar.slider(
    "Throttle Override (PWM)",
    min_value=1000,
    max_value=2000,
    step=10,
    key="pwm_slider"
)

# --------------------------------------------------------------------

st.sidebar.markdown("---")

# ----------------- LOAD CELL CALIBRATION ----------------------------

st.sidebar.subheader("⚖️ Load Cell Calibration")

# Live Calibration Factor Input bound to session_state
cal_factor = st.sidebar.number_input(
    "Calibration Factor",
    step=1.0,
    format="%.2f",
    key="cal_input"
)

# Tare Button Logic with Safety Lock
tare_requested = st.sidebar.button("Zero / Tare Scale", use_container_width=True)
if tare_requested:
    if target_pwm > 1000:
        st.sidebar.error("❌ Motor must be OFF (1000 PWM) to tare the scale.")
        tare_requested = False
    else:
        st.sidebar.warning("Taring Scale... (Please wait 2 seconds)")

# -----------------------------------------------------------------------------------

# --- EDITED: Added Sidebar Toggle for Live Seaborn Statistical Rendering ---
st.sidebar.markdown("---")
st.sidebar.subheader("📊 Statistical Suite (Seaborn)")
live_seaborn = st.sidebar.checkbox(
    "Render Seaborn Live (1 FPS)",
    value=False,
    help="Seaborn renders automatically when paused. Enable this to also update Seaborn charts every 1s during live telemetry."
)
# ---------------------------------------------------------------------------

# ==========================================
# 4. UI LAYOUT PLACEHOLDERS
# ==========================================
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
metric_thrust = kpi_col1.empty()
metric_power = kpi_col2.empty()
metric_current = kpi_col3.empty()
metric_efficiency = kpi_col4.empty()

# --- EDITED: Added an 8-Rotor eVTOL Extrapolation & Regression Equation banner ---
evtol_banner = st.empty()

st.markdown("---")
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    transient_chart = st.empty()
    thrust_curve_chart = st.empty()
with chart_col2:
    electrical_chart = st.empty()
    efficiency_curve_chart = st.empty()

# --- EDITED: Added UI Placeholders for Seaborn Statistical Charts ---
st.markdown("---")
st.subheader("📊 Seaborn Statistical Telemetry Analysis")
sns_col1, sns_col2 = st.columns(2)
with sns_col1:
    sns_heatmap_slot = st.empty()
with sns_col2:
    sns_regplot_slot = st.empty()
# --------------------------------------------------------------------


# ==========================================
# 5. CHART GENERATION FUNCTIONS
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
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['thrust_g'], mode='markers', name='Live Sensor Data',
                             marker=dict(color='#00F0FF', size=5, opacity=0.5)))
    # --- EDITED: Wrapped polyfit in try/except RankWarning guard for numerical stability ---
    if len(df['pwm'].unique()) > 3:
        try:
            coeffs = np.polyfit(df['pwm'], df['thrust_g'], 2)
            poly_func = np.poly1d(coeffs)
            x_trend = np.linspace(df['pwm'].min(), df['pwm'].max(), 50)
            y_trend = poly_func(x_trend)
            fig.add_trace(go.Scatter(x=x_trend, y=y_trend, mode='lines', name='Regression Curve',
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


# --- EDITED: Added Seaborn Statistical Chart Generation Functions ---
def get_seaborn_heatmap(df):
    """Generates a Seaborn Pearson correlation matrix across all propulsion parameters."""
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
    """Generates a Seaborn 2nd-order polynomial regression plot with 95% confidence interval bands."""
    fig, ax = plt.subplots(figsize=(6, 4.2))
    # Only calculate polynomial regression if more than 3 distinct PWM steps exist
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
    """Renders Seaborn figures and immediately closes Matplotlib objects to prevent memory leaks."""
    if len(df) > 2:
        fig_corr = get_seaborn_heatmap(df)
        sns_heatmap_slot.pyplot(fig_corr, use_container_width=True)
        plt.close(fig_corr)  # Critical: Frees Matplotlib figure from RAM

        fig_reg = get_seaborn_regplot(df)
        sns_regplot_slot.pyplot(fig_reg, use_container_width=True)
        plt.close(fig_reg)   # Critical: Frees Matplotlib figure from RAM
    else:
        sns_heatmap_slot.info("Waiting for >2 telemetry samples to compute Seaborn correlation matrix...")
# --------------------------------------------------------------------


# --- EDITED: Helper function to render UI elements both inside the live loop AND when paused ---
def render_dashboard_ui(df, key_suffix):
    latest = df.iloc[-1]
    metric_thrust.metric("Thrust (g)", f"{latest['thrust_g']:.1f}")
    metric_power.metric("Power (W)", f"{latest['power_W']:.1f}")
    metric_current.metric("Current (A)", f"{latest['current_A']:.2f}", f"{latest['voltage']:.2f} V")
    metric_efficiency.metric("Efficiency (g/W)", f"{latest['efficiency_g_W']:.2f}")

    # Calculate 8-Rotor eVTOL Extrapolation (Jetson ONE class scaling) & Polynomial Fit Equation
    evtol_lift_kg = (latest['thrust_g'] * 8.0) / 1000.0
    evtol_power_kw = (latest['power_W'] * 8.0) / 1000.0
    poly_str = "Sweep across >3 throttle steps to generate real-time 2nd-degree polynomial model..."
    if len(df['pwm'].unique()) > 3:
        try:
            c = np.polyfit(df['pwm'], df['thrust_g'], 2)
            poly_str = f"Fitted Twin Model: Thrust(g) = ({c[0]:.4e})·PWM² + ({c[1]:.3f})·PWM + ({c[2]:.1f})"
        except Exception:
            pass

    evtol_banner.info(
        f"**🛸 8-Rotor eVTOL Virtual Extrapolation:** Projected Total Lift: **`{evtol_lift_kg:.2f} kg`** | "
        f"Projected Total Power: **`{evtol_power_kw:.2f} kW`** | `{poly_str}`"
    )

    # --- EDITED CODE: Added unique dynamic keys to prevent Streamlit ID collisions ---
    transient_chart.plotly_chart(get_transient_fig(df), use_container_width=True, key=f"transient_{key_suffix}")
    electrical_chart.plotly_chart(get_electrical_fig(df), use_container_width=True, key=f"elec_{key_suffix}")
    thrust_curve_chart.plotly_chart(get_thrust_curve_fig(df), use_container_width=True, key=f"thrust_{key_suffix}")
    efficiency_curve_chart.plotly_chart(get_efficiency_curve_fig(df), use_container_width=True, key=f"eff_{key_suffix}")


# ==========================================
# 6. MAIN TELEMETRY LOOP
# ==========================================
if st.session_state.is_running:
    # --- EDITED: Pre-declare global variables so the 'finally' cleanup block can access them ---
    ser = None
    mqtt_client = None
    mqtt_connected = False

    try:
        # OPEN SERIAL WITHOUT RESETTING THE ESP32
        ser = serial.Serial()
        ser.port = serial_port
        ser.baudrate = baud_rate
        ser.timeout = 0.05  # --- EDITED: Tight 50ms timeout matched to 50Hz (20ms) hardware loop ---
        ser.setDTR(False)   # <--- Critical: Prevents ESP32 hardware reset on UI interaction
        ser.setRTS(False)   # <--- Critical: Prevents ESP32 hardware reset on UI interaction
        ser.open()

        # --- EDITED: Flush any stale backlog bytes in the OS serial buffer so telemetry has zero lag ---
        ser.reset_input_buffer()

        # Build and send JSON Command Downlink
        cmd_payload = {
            "pwm": target_pwm,
            "cal": cal_factor,
            "tare": 1 if tare_requested else 0
        }
        ser.write((json.dumps(cmd_payload) + '\n').encode())
        ser.flush()  # --- EDITED: Ensure downlink bytes are transmitted immediately ---

        # --- Initialize MQTT Broker for Ansys ---
        # --- EDITED: Wrapped in try/except and using 'mqtt_connected' flag to prevent silent failures ---
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "DEP_Gateway")
            mqtt_client.connect("localhost", 1883, keepalive=60)
            mqtt_client.loop_start()  # Starts network loop in background
            mqtt_connected = True
        except Exception:
            st.sidebar.warning("⚠️ MQTT Broker not running. Simulating locally.")
        # --------------------------------------------------

        last_ui_update = time.time()
        # --- EDITED: Added separate 1 FPS timer for Seaborn so static raster plots don't lag the 5 FPS loop ---
        last_sns_update = time.time()

        while st.session_state.is_running:
            try:
                # --- EDITED: If OS buffer ever accumulates backlog during a UI render, drain to latest line ---
                if ser.in_waiting > 250:
                    ser.reset_input_buffer()

                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    payload = json.loads(line)

                    # --- Publish Live Data to Ansys Twin Builder ---
                    # --- EDITED: Checks flag before publishing to avoid errors if broker is offline ---
                    if mqtt_connected:
                        mqtt_client.publish("evtol/rotor1/telemetry", json.dumps(payload))
                    # ---------------------------------------------------------

                    if st.session_state.start_millis is None:
                        st.session_state.start_millis = payload['time']

                    time_s = (payload['time'] - st.session_state.start_millis) / 1000.0
                    eff = payload['thrust_g'] / payload['power_W'] if payload['power_W'] > 0.5 else 0.0

                    # --- EDITED: Appending to the O(1) deque buffer instead of using heavy pd.concat() ---
                    st.session_state.data_buffer.append({
                        'time_s': time_s, 'thrust_g': payload['thrust_g'], 'voltage': payload['voltage'],
                        'current_A': payload['current_A'], 'power_W': payload['power_W'],
                        'pwm': payload['pwm'], 'efficiency_g_W': eff
                    })
                else:
                    # --- EDITED: Only sleep briefly if no serial line arrived, preventing buffer lag! ---
                    time.sleep(0.002)

            except (json.JSONDecodeError, KeyError, ValueError):
                # --- EDITED: Also catches KeyError/ValueError in case a half-written JSON line is read ---
                pass

            # --- EDITED: 5 FPS UI THROTTLER IMPLEMENTED HERE ---
            # Updates the heavy frontend elements ONLY once every 0.2 seconds
            current_time = time.time()
            if current_time - last_ui_update > 0.2 and len(st.session_state.data_buffer) > 0:
                # --- EDITED: Convert the fast buffer into a Pandas DataFrame for Plotly to read ---
                df = pd.DataFrame(list(st.session_state.data_buffer))
                render_dashboard_ui(df, key_suffix=f"{current_time}")
                last_ui_update = current_time

                # --- EDITED: 1 FPS Throttler for Live Seaborn Statistical Plots (if enabled in sidebar) ---
                if live_seaborn and (current_time - last_sns_update > 1.0):
                    render_seaborn_ui(df)
                    last_sns_update = current_time

    except Exception as e:
        st.error(f"Serial Connection Failed: {e}")
        st.session_state.is_running = False
        # --- NEW CODE: Reset connection state if crash occurs ---
        st.session_state.is_connected = False
        # --------------------------------------------------------

    # --- EDITED: OPTIMIZATION 2: Bulletproof Resource Cleanup & Fail-Safe Disarm ---
    finally:
        # This guarantees the COM port and MQTT client are freed even if you hit "Stop", move a slider, or an error occurs.
        if ser is not None and ser.is_open:
            try:
                # If Emergency Stop was clicked while loop was active, disarm motor before closing port
                if st.session_state.estop_triggered:
                    kill_cmd = {"pwm": 1000, "cal": cal_factor, "tare": 0}
                    ser.write((json.dumps(kill_cmd) + '\n').encode())
                    ser.flush()
            except Exception:
                pass
            ser.close()
        if mqtt_connected and mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    # ------------------------------------------------------------

# --- EDITED: Static Render Fallback ---
# Keeps your last recorded charts and KPIs (including Seaborn) visible on screen when the telemetry link is paused/stopped!
elif len(st.session_state.data_buffer) > 0:
    df_paused = pd.DataFrame(list(st.session_state.data_buffer))
    render_dashboard_ui(df_paused, key_suffix="paused_state")
    render_seaborn_ui(df_paused)