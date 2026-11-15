# ========================================================================
# Includes Polynomial Regression, Calibration of load cell, MQTT Broker
# --- EDITED: Added Zero-Lag Serial Sync, Safe E-Stop Disarm, Static
# Chart Persistence, CSV Export, and 8-Rotor eVTOL Extrapolation ---
# --- EDITED: Integrated Seaborn Statistical Suite ---
# --- EDITED: Added Automated Mission Profile (Autonomous Flight Cycle) ---
# --- EDITED: Added Two-Way Ansys Twin Builder Interface & MQTT Callbacks ---
# --- FIXED: Background Thread safe MQTT Callback data store (Cache Resource) ---
# --- FIXED: Cached Persistent Serial Object to survive Slider Reruns ---
# --- FIXED: Manual PWM Sync inside live loop & Dedicated Voltage KPI ---
# ========================================================================

# --- Library Imports ---
import streamlit as st  # Core web dashboard framework
import paho.mqtt.client as mqtt  # MQTT protocol library for Ansys co-simulation
import serial  # PySerial for USB communication with the ESP32
import pandas as pd  # Data manipulation and CSV export
import json  # Parsing incoming telemetry and formatting outgoing commands
import time  # Timestamps for plotting and loop throttling
import numpy as np  # Mathematical operations and polynomial regression fitting
import collections  # Provides the 'deque' for efficient data buffering
import plotly.graph_objects as go  # High-performance interactive charting
from plotly.subplots import make_subplots  # Creating dual-axis Plotly charts
import seaborn as sns  # Statistical data visualization (heatmaps, regression bands)
import matplotlib.pyplot as plt  # Matplotlib backend required for Seaborn rendering

# ==========================================
# 1. PAGE CONFIGURATION & CUSTOM CSS
# ==========================================
# Set up a wide layout suitable for a dense, multi-chart engineering dashboard
st.set_page_config(page_title="DEP Digital Twin", layout="wide", initial_sidebar_state="expanded")

# Configure Seaborn and Matplotlib to match Streamlit's native dark mode aesthetic
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

# Custom CSS injected via HTML to style the top KPI metric boxes with borders and shadows
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
# 2. STATE MANAGEMENT & THREAD-SAFE STORES
# ==========================================
# Streamlit reruns the entire script top-to-bottom on every user interaction (e.g., clicking a button).
# st.session_state is used to persist variables and objects across these continuous reruns.

if 'data_buffer' not in st.session_state:
    # A deque with maxlen=200 acts as a sliding window. It holds the last ~4 seconds of data at 50Hz,
    # automatically dropping the oldest data to prevent memory overflow and UI lag.
    st.session_state.data_buffer = collections.deque(maxlen=200)
if 'start_millis' not in st.session_state:
    st.session_state.start_millis = None  # Used to normalize timestamps to T=0s
if 'is_running' not in st.session_state:
    st.session_state.is_running = False  # Flag to keep the main telemetry while-loop active
if 'is_connected' not in st.session_state:
    st.session_state.is_connected = False  # Tracks if the physical COM port is verified
if 'estop_triggered' not in st.session_state:
    st.session_state.estop_triggered = False
if 'mqtt_verified' not in st.session_state:
    st.session_state.mqtt_verified = False

# Variables for the Autonomous Mission Profile (Hover Cycle Test)
if 'mission_active' not in st.session_state:
    st.session_state.mission_active = False
if 'mission_start_time' not in st.session_state:
    st.session_state.mission_start_time = 0
if 'last_sent_pwm' not in st.session_state:
    st.session_state.last_sent_pwm = None  # Prevents flooding the serial bus with duplicate PWM commands

# --- FIXED: Cached Serial Object prevents OS port lock crashes ---
if 'ser_obj' not in st.session_state:
    st.session_state.ser_obj = None  # Holds the active PySerial object so it survives Streamlit reruns


# Thread-Safe Store for MQTT: The paho-mqtt library runs its network listener in a background thread.
# Streamlit prohibits background threads from writing directly to st.session_state.
# @st.cache_resource creates a persistent, thread-safe global dictionary to bridge the threads.
@st.cache_resource
def get_ansys_data_store():
    return {"rom_temp_c": 0.0, "rom_predicted_thrust": 0.0, "rom_status": "Waiting..."}


# ==========================================
# 3. SIDEBAR CONTROL PANEL
# ==========================================
st.sidebar.header("⚙️ ESP32 System Control")
serial_port = st.sidebar.text_input("COM Port", value="COM6")
baud_rate = st.sidebar.selectbox("Baud Rate", [115200, 9600, 57600], index=0)

# Connect Button: Briefly opens and closes the port to verify the hardware exists
if st.sidebar.button("🔌 Connect to ESP32", use_container_width=True):
    try:
        test_ser = serial.Serial()
        test_ser.port = serial_port
        test_ser.baudrate = baud_rate
        test_ser.timeout = 0.1
        test_ser.setDTR(False)  # Prevents ESP32 from rebooting upon connection
        test_ser.setRTS(False)
        test_ser.open()
        test_ser.close()
        st.session_state.is_connected = True
        st.sidebar.success(f"✅ Successfully connected to {serial_port}")
    except Exception as e:
        st.session_state.is_connected = False
        st.sidebar.error(f"❌ Connection Failed: {e}")

st.sidebar.markdown("---")

st.sidebar.header("🌐 MQTT Broker Connection")
mqtt_broker_ip = st.sidebar.text_input("Broker IP Address", value="127.0.0.1")
mqtt_broker_port = st.sidebar.number_input("Broker Port", value=1883, step=1)

# Verify Broker: Pings the Mosquitto network to ensure it is alive before the main loop starts
if st.sidebar.button("🔌 Verify MQTT Broker", use_container_width=True):
    try:
        test_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Test_Connection")
        test_mqtt.connect(mqtt_broker_ip, mqtt_broker_port, keepalive=2)
        test_mqtt.disconnect()
        st.session_state.mqtt_verified = True
        st.sidebar.success(f"✅ Broker active at {mqtt_broker_ip}:{mqtt_broker_port}")
    except Exception as e:
        st.session_state.mqtt_verified = False
        st.sidebar.error("❌ Connection Refused: Ensure Mosquitto is running.")

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
    # Properly close and release the cached serial object back to Windows when stopping
    if st.session_state.ser_obj is not None and st.session_state.ser_obj.is_open:
        st.session_state.ser_obj.close()

if st.sidebar.button("🗑️ Clear Recorded Data", use_container_width=True):
    st.session_state.data_buffer.clear()
    st.session_state.start_millis = None

# Export to CSV: Converts the sliding window deque into a Pandas DataFrame, then to downloadable bytes
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
# Initiates the hands-free hover cycle state machine
if st.sidebar.button("▶️ Run Hover Cycle Test", use_container_width=True):
    if st.session_state.is_running:
        st.session_state.mission_active = True
        st.session_state.mission_start_time = time.time()
        st.session_state.last_sent_pwm = None  # Reset to force the new command sequence
    else:
        st.sidebar.error("⚠️ Start Telemetry Link first!")

if st.session_state.mission_active:
    st.sidebar.success("✅ Mission Active: Hands off controls!")

st.sidebar.markdown("---")
st.sidebar.subheader("✈️ Flight Controls")

# Initialize default slider states
if 'pwm_slider' not in st.session_state:
    st.session_state.pwm_slider = 1000
if 'cal_input' not in st.session_state:
    st.session_state.cal_input = 1.0

# E-STOP: Uses the already-open cached serial object to bypass buffers and cut power instantly
if st.sidebar.button("🚨 EMERGENCY STOP", type="primary", use_container_width=True):
    st.session_state.pwm_slider = 1000
    target_pwm = 1000
    st.session_state.is_running = False
    st.session_state.estop_triggered = True
    st.session_state.mission_active = False

    try:
        # Send a hardcoded 1000 PWM JSON packet to disarm the ESC
        if st.session_state.ser_obj is not None and st.session_state.ser_obj.is_open:
            cmd = {"pwm": 1000, "cal": st.session_state.cal_input, "tare": 0}
            st.session_state.ser_obj.write((json.dumps(cmd) + '\n').encode())
            st.session_state.ser_obj.flush()
            st.session_state.ser_obj.close()
            st.sidebar.success("🚨 E-STOP TRIGGERED. Motor Disarmed (1000 PWM).")
    except Exception as e:
        st.sidebar.error(f"E-Stop Comms Failure: {e}")

# Main manual throttle control (disabled when the autonomous mission is running)
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

# Input for the calculated HX711 scalar (requires physical weight calibration beforehand)
cal_factor = st.sidebar.number_input("Calibration Factor", step=1.0, format="%.2f", key="cal_input")

# Tare request button (flags a tare command to be sent in the next serial packet)
tare_requested = st.sidebar.button("Zero / Tare Scale", use_container_width=True)
if tare_requested:
    if target_pwm > 1000 or st.session_state.mission_active:
        # Hardware safety lock: Do not tare while the motor is spinning
        st.sidebar.error("❌ Motor must be OFF (1000 PWM) to tare the scale.")
        tare_requested = False
    else:
        st.sidebar.warning("Taring Scale... (Please wait 2 seconds)")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Statistical Suite (Seaborn)")
# Seaborn rendering is computationally heavy, so it runs at 1 FPS (opt-in)
live_seaborn = st.sidebar.checkbox("Render Seaborn Live (1 FPS)", value=False)

# ==========================================
# 4. UI LAYOUT PLACEHOLDERS (5 Columns)
# ==========================================
# Streamlit placeholders (.empty()) allow us to rapidly overwrite charts and metrics
# in real-time without forcing the entire DOM/page to refresh, preventing flicker.

st.markdown("<h4 class='ansys-header'>🌐 Physical Hardware Telemetry</h4>", unsafe_allow_html=True)
kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
metric_thrust = kpi_col1.empty()
metric_power = kpi_col2.empty()
metric_voltage = kpi_col3.empty()
metric_current = kpi_col4.empty()
metric_efficiency = kpi_col5.empty()

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

# MQTT Callback triggered when successfully connected to the Mosquitto broker
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    client.subscribe("evtol/rotor1/predictions")
    get_ansys_data_store()["rom_status"] = "Connected"


# MQTT Callback triggered whenever Ansys Twin Builder sends a new ROM prediction
def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        ansys_store = get_ansys_data_store()
        # Parse incoming thermal and aerodynamic predictions
        if "rom_temp_c" in payload:
            ansys_store["rom_temp_c"] = payload["rom_temp_c"]
        if "rom_thrust_g" in payload:
            ansys_store["rom_predicted_thrust"] = payload["rom_thrust_g"]
    except Exception:
        pass


# Generates a dual-axis line chart for physical Thrust and Power over time
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


# Generates a dual-axis line chart for Current draw and SMPS Voltage over time
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


# Generates a scatter plot of PWM vs Thrust, and calculates a live 2nd-degree polynomial curve
def get_thrust_curve_fig(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['thrust_g'], mode='markers', name='Physical Thrust Data',
                             marker=dict(color='#00F0FF', size=5, opacity=0.5)))
    # Only compute regression if we have swept across more than 3 distinct PWM points
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


# Generates a scatter plot of system efficiency (grams of thrust per Watt)
def get_efficiency_curve_fig(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['pwm'], y=df['efficiency_g_W'], mode='markers', name='Live Sensor Data',
                             marker=dict(color='#00FF44', size=5, opacity=0.5)))
    if len(df['pwm'].unique()) > 3:
        # Filter out noisy data near 0 Watts before attempting to fit the curve to prevent division by zero errors
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


# Generates a Seaborn Heatmap showing the correlation coefficients between all major parameters
def get_seaborn_heatmap(df):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    cols = ['pwm', 'thrust_g', 'voltage', 'current_A', 'power_W', 'efficiency_g_W']
    corr = df[cols].corr().fillna(0)  # Calculate Pearson correlation matrix
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="mako", vmin=-1, vmax=1,
        ax=ax, cbar_kws={'shrink': 0.8}, linewidths=0.5, linecolor="#222222"
    )
    ax.set_title("Multi-Variate Parameter Correlation Matrix", color="white", fontsize=11, pad=12)
    fig.tight_layout()
    return fig


# Generates a Seaborn Regplot which automatically calculates a 95% confidence band around the fit
def get_seaborn_regplot(df):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    has_variance = len(df['pwm'].unique()) > 3
    sns.regplot(
        data=df, x='pwm', y='thrust_g',
        order=2 if has_variance else 1,  # Use quadratic fit if sufficient data exists, otherwise linear
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


# Wrapper function to render Seaborn plots and manage matplotlib memory cleanup
def render_seaborn_ui(df):
    if len(df) > 2:
        fig_corr = get_seaborn_heatmap(df)
        sns_heatmap_slot.pyplot(fig_corr, use_container_width=True)
        plt.close(fig_corr)  # Close figure to prevent memory leaks

        fig_reg = get_seaborn_regplot(df)
        sns_regplot_slot.pyplot(fig_reg, use_container_width=True)
        plt.close(fig_reg)
    else:
        sns_heatmap_slot.info("Waiting for >2 telemetry samples to compute Seaborn correlation matrix...")


# Main function to push the latest data frame into the Streamlit UI placeholders
def render_dashboard_ui(df, key_suffix):
    latest = df.iloc[-1]
    ansys_store = get_ansys_data_store()

    # Update Physical Hardware KPIs
    metric_thrust.metric("Thrust (g)", f"{latest['thrust_g']:.1f}")
    metric_power.metric("Power (W)", f"{latest['power_W']:.1f}")
    metric_voltage.metric("Voltage (V)", f"{latest['voltage']:.2f}")
    metric_current.metric("Current (A)", f"{latest['current_A']:.2f}")
    metric_efficiency.metric("Efficiency (g/W)", f"{latest['efficiency_g_W']:.2f}")

    # Update Ansys ROM Metrics (Extracted from background thread store)
    ansys_metric_status.metric("Co-Sim Status", ansys_store["rom_status"])
    ansys_metric_temp.metric("ROM Motor Temp", f"{ansys_store['rom_temp_c']:.1f} °C")

    # Calculate Twin accuracy deviation (Predicted Virtual vs Physical Reality)
    phys_thrust = latest['thrust_g']
    virt_thrust = ansys_store['rom_predicted_thrust']
    dev = virt_thrust - phys_thrust if phys_thrust > 0 else 0
    ansys_metric_thrust.metric("ROM Predicted Thrust", f"{virt_thrust:.1f} g",
                               f"{dev:.1f} g error" if virt_thrust > 0 else None, delta_color="inverse")

    # Extrapolate physical data from 1 test rotor to a theoretical 8-rotor airframe
    evtol_lift_kg = (latest['thrust_g'] * 8.0) / 1000.0
    evtol_power_kw = (latest['power_W'] * 8.0) / 1000.0

    # Format the live mathematical regression equation for display
    poly_str = "Sweep across >3 throttle steps to generate real-time 2nd-degree polynomial model..."
    if len(df['pwm'].unique()) > 3:
        try:
            c = np.polyfit(df['pwm'], df['thrust_g'], 2)
            poly_str = f"Fitted Twin Model: Thrust(g) = ({c[0]:.4e})·PWM² + ({c[1]:.3f})·PWM + ({c[2]:.1f})"
        except Exception:
            pass

    mission_status = "🟢 AUTONOMOUS HOVER CYCLE ACTIVE" if st.session_state.mission_active else "🛸 8-Rotor eVTOL Virtual Extrapolation"

    # Display the Banner
    evtol_banner.info(
        f"**{mission_status}:** Projected Total Lift: **`{evtol_lift_kg:.2f} kg`** | "
        f"Projected Total Power: **`{evtol_power_kw:.2f} kW`** | `{poly_str}`"
    )

    # Push updated Plotly charts to the UI
    transient_chart.plotly_chart(get_transient_fig(df), use_container_width=True, key=f"transient_{key_suffix}")
    electrical_chart.plotly_chart(get_electrical_fig(df), use_container_width=True, key=f"elec_{key_suffix}")
    thrust_curve_chart.plotly_chart(get_thrust_curve_fig(df), use_container_width=True, key=f"thrust_{key_suffix}")
    efficiency_curve_chart.plotly_chart(get_efficiency_curve_fig(df), use_container_width=True, key=f"eff_{key_suffix}")


# ==========================================
# 6. MAIN TELEMETRY LOOP
# ==========================================
# This loop blocks the Streamlit app from fully finishing its script execution.
# It runs continuously, reading serial data, publishing it via MQTT, and forcing UI updates.

if st.session_state.is_running:
    mqtt_client = None
    mqtt_connected = False

    try:
        # 1. Initialize persistent Serial Connection (if not already opened by a slider rerun)
        if st.session_state.ser_obj is None or not st.session_state.ser_obj.is_open:
            st.session_state.ser_obj = serial.Serial()
            st.session_state.ser_obj.port = serial_port
            st.session_state.ser_obj.baudrate = baud_rate
            st.session_state.ser_obj.timeout = 0.05
            st.session_state.ser_obj.setDTR(False)
            st.session_state.ser_obj.setRTS(False)
            st.session_state.ser_obj.open()

        st.session_state.ser_obj.reset_input_buffer()

        # Send initial command upon starting the loop (applies Tare requests immediately)
        if not st.session_state.mission_active:
            cmd_payload = {"pwm": target_pwm, "cal": st.session_state.cal_input, "tare": 1 if tare_requested else 0}
            st.session_state.ser_obj.write((json.dumps(cmd_payload) + '\n').encode())
            st.session_state.ser_obj.flush()
            st.session_state.last_sent_pwm = target_pwm

        # 2. Initialize MQTT Broker connection for Co-Simulation
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "DEP_Dashboard_Node")
            mqtt_client.on_connect = on_mqtt_connect
            mqtt_client.on_message = on_mqtt_message
            mqtt_client.connect(mqtt_broker_ip, mqtt_broker_port, keepalive=60)
            mqtt_client.loop_start()  # Starts network daemon in background
            mqtt_connected = True
        except Exception:
            get_ansys_data_store()["rom_status"] = "Offline"
            st.sidebar.warning(f"⚠️ MQTT Broker not found at {mqtt_broker_ip}:{mqtt_broker_port}")

        # Throttle UI refreshes to ~5 FPS to prevent Streamlit from lagging
        last_ui_update = time.time()
        last_sns_update = time.time()

        while st.session_state.is_running:
            try:
                # --- COMMAND UPLINK (Send controls TO the ESP32) ---
                if st.session_state.mission_active:
                    # Execute time-based state machine for hover cycle test
                    elapsed = time.time() - st.session_state.mission_start_time
                    new_pwm = 1000
                    if elapsed < 5.0:
                        new_pwm = 1200  # Spool up
                    elif elapsed < 8.0:
                        new_pwm = 1800  # Max Thrust (Climb)
                    elif elapsed < 18.0:
                        new_pwm = 1500  # Sustained Hover
                    elif elapsed < 22.0:
                        new_pwm = 1200  # Descent
                    else:
                        new_pwm = 1000  # Disarm
                        st.session_state.mission_active = False

                    # Only send command if it has changed to prevent serial flooding
                    if st.session_state.last_sent_pwm != new_pwm:
                        mission_cmd = {"pwm": new_pwm, "cal": st.session_state.cal_input, "tare": 0}
                        st.session_state.ser_obj.write((json.dumps(mission_cmd) + '\n').encode())
                        st.session_state.ser_obj.flush()
                        st.session_state.last_sent_pwm = new_pwm
                else:
                    # Sync manual Streamlit slider directly to hardware if it changed
                    if st.session_state.last_sent_pwm != target_pwm:
                        manual_cmd = {"pwm": target_pwm, "cal": st.session_state.cal_input, "tare": 0}
                        st.session_state.ser_obj.write((json.dumps(manual_cmd) + '\n').encode())
                        st.session_state.ser_obj.flush()
                        st.session_state.last_sent_pwm = target_pwm

                # --- TELEMETRY DOWNLINK (Read sensors FROM the ESP32) ---
                # Drop stale packets to prevent the UI charting from falling behind physical reality
                if st.session_state.ser_obj.in_waiting > 250:
                    st.session_state.ser_obj.reset_input_buffer()

                line = st.session_state.ser_obj.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    payload = json.loads(line)

                    # Forward physical telemetry to Ansys Twin Builder via MQTT
                    if mqtt_connected:
                        mqtt_client.publish("evtol/rotor1/telemetry", json.dumps(payload))

                    if st.session_state.start_millis is None:
                        st.session_state.start_millis = payload['time']

                    # Normalize timestamps relative to Dashboard start time
                    time_s = (payload['time'] - st.session_state.start_millis) / 1000.0
                    eff = payload['thrust_g'] / payload['power_W'] if payload['power_W'] > 0.5 else 0.0

                    # Append to sliding window buffer
                    st.session_state.data_buffer.append({
                        'time_s': time_s, 'thrust_g': payload['thrust_g'], 'voltage': payload['voltage'],
                        'current_A': payload['current_A'], 'power_W': payload['power_W'],
                        'pwm': payload['pwm'], 'efficiency_g_W': eff
                    })
                else:
                    time.sleep(0.002)

            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # Ignore occasional corrupted serial packets without crashing the loop

            # --- RENDER UPDATES ---
            # Throttle UI re-renders to roughly 5 Hz
            current_time = time.time()
            if current_time - last_ui_update > 0.2 and len(st.session_state.data_buffer) > 0:
                df = pd.DataFrame(list(st.session_state.data_buffer))
                render_dashboard_ui(df, key_suffix=f"{current_time}")
                last_ui_update = current_time

                # Seaborn is throttled to 1 Hz due to matplotlib's slower rendering engine
                if live_seaborn and (current_time - last_sns_update > 1.0):
                    render_seaborn_ui(df)
                    last_sns_update = current_time

    except Exception as e:
        st.error(f"Serial Connection Failed: {e}")
        st.session_state.is_running = False
        st.session_state.is_connected = False
        st.session_state.mission_active = False

    finally:
        # Cleanly stop MQTT listener when the telemetry loop is stopped
        if mqtt_connected and mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

# If the loop is paused/stopped, keep the last known data charted on the screen
elif len(st.session_state.data_buffer) > 0:
    df_paused = pd.DataFrame(list(st.session_state.data_buffer))
    render_dashboard_ui(df_paused, key_suffix="paused_state")
    render_seaborn_ui(df_paused)
