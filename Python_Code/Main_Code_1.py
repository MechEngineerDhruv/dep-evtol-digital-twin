import streamlit as st
import serial
import pandas as pd
import json
import time

# --- Configuration ---
# You must update this to match the COM port your ESP32 uses when plugged in
SERIAL_PORT = 'COM3'
BAUD_RATE = 115200

# Configure the Streamlit page layout to use the full width of the monitor
st.set_page_config(page_title="Rotor Thrust & Power Twin", layout="wide")
st.title("Rotor Thrust & Power Twin (Hardware Mod 0.01Ω)")

# --- State Management ---
# Initialize an empty Pandas DataFrame in Streamlit's session state.
# This preserves historical data across UI refreshes.
if 'data' not in st.session_state:
    st.session_state.data = pd.DataFrame(columns=['time', 'thrust_g', 'voltage', 'current_A', 'power_W', 'pwm'])

# --- Control Downlink (Virtual to Physical) ---
st.sidebar.header("Control Panel")
# Slider allows the operator to set the target RPM. Limit restored to 2000 due to hardware mod.
target_pwm = st.sidebar.slider("Throttle (PWM)", min_value=1000, max_value=2000, value=1000, step=10)

# Attempt to open the serial port and send the target PWM command to the ESP32
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    ser.write(f"{target_pwm}\n".encode())
except Exception as e:
    st.sidebar.error(f"Serial Error: {e}")
    ser = None

# --- UI Layout Definition ---
# Create three columns for large, real-time KPI metrics at the top of the dashboard
col1, col2, col3 = st.columns(3)
metric_thrust = col1.empty()
metric_power = col2.empty()
metric_efficiency = col3.empty()

st.markdown("---")  # Visual divider

st.subheader("Live Telemetry & Performance Curves")
# Create a 2x2 grid for the live telemetry charts
graph_col1, graph_col2 = st.columns(2)

with graph_col1:
    st.markdown("**Transient Response: Thrust & Power**")
    time_series_chart = st.empty()  # Tracks thrust and power over time
    st.markdown("**Aerodynamic Thrust Curve**")
    thrust_curve_chart = st.empty()  # Plots Thrust vs PWM

with graph_col2:
    st.markdown("**Electrical Health: Voltage & Current**")
    electrical_chart = st.empty()  # Tracks voltage stability and current draw
    st.markdown("**System Efficiency (g/W)**")
    efficiency_curve_chart = st.empty()  # Plots Lift Efficiency vs PWM

# --- Telemetry Uplink (Physical to Virtual) ---
# Starts the continuous loop to read and plot incoming sensor data
if st.button("Start Telemetry Stream") and ser:
    while True:
        try:
            # Read one line of incoming serial data and decode it
            line = ser.readline().decode('utf-8').strip()
            if line:
                # Parse the JSON string into a Python dictionary
                payload = json.loads(line)
                new_row = pd.DataFrame([payload])

                # Append the new sensor readings to the historical DataFrame
                st.session_state.data = pd.concat([st.session_state.data, new_row], ignore_index=True)

                # Truncate the DataFrame to keep only the most recent 150 readings.
                # This prevents the dashboard from crashing due to memory overload.
                if len(st.session_state.data) > 150:
                    st.session_state.data = st.session_state.data.iloc[1:]

                df = st.session_state.data.copy()

                # Compute real-time efficiency (grams of thrust per Watt of power).
                # The lambda function prevents a 'division by zero' error when the motor is off.
                df['efficiency_g_W'] = df.apply(
                    lambda row: row['thrust_g'] / row['power_W'] if row['power_W'] > 0.1 else 0,
                    axis=1
                )

                # Extract the most recent (last) values from the DataFrame
                current_thrust = df['thrust_g'].iloc[-1]
                current_power = df['power_W'].iloc[-1]
                current_voltage = df['voltage'].iloc[-1]
                current_amps = df['current_A'].iloc[-1]
                efficiency = df['efficiency_g_W'].iloc[-1]

                # Update the KPI metric numbers in the UI
                metric_thrust.metric("Live Thrust (g)", f"{current_thrust:.1f}")
                metric_power.metric("Live Power (W)", f"{current_power:.1f}",
                                    f"{current_voltage:.2f} V | {current_amps:.2f} A")
                metric_efficiency.metric("Efficiency (g/W)", f"{efficiency:.2f}")

                # Redraw all four charts with the newly updated DataFrame
                time_series_chart.line_chart(df[['thrust_g', 'power_W']])
                electrical_chart.line_chart(df[['voltage', 'current_A']])
                thrust_curve_chart.scatter_chart(df, x='pwm', y='thrust_g')
                efficiency_curve_chart.scatter_chart(df, x='pwm', y='efficiency_g_W')

            # Sleep briefly to sync with the ESP32's 50Hz transmission rate
            time.sleep(0.05)

            # Ignore lines where the JSON was cut off mid-transmission
        except json.JSONDecodeError:
            pass
            # Halt the stream gracefully if the user stops the script or pulls the USB
        except Exception as e:
            st.error(f"Stream interrupted: {e}")
            break