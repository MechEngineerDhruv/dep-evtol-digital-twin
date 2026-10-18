import streamlit as st
import serial
import pandas as pd
import json
import time

SERIAL_PORT = 'COM3' # Update this to your active port
BAUD_RATE = 115200

st.set_page_config(page_title="Rotor Thrust & Power Twin", layout="wide")
st.title("Rotor Thrust & Power Twin (INA219 Safe Mode)")
st.warning("Hardware Limit Active: Maximum throttle locked to 1350 PWM to prevent INA219 thermal failure.")

if 'data' not in st.session_state:
    st.session_state.data = pd.DataFrame(columns=['time', 'thrust_g', 'voltage', 'current_A', 'power_W', 'pwm'])

st.sidebar.header("Control Panel")
# SLIDER LOCKED TO 1350 MAX
target_pwm = st.sidebar.slider("Throttle (PWM)", min_value=1000, max_value=1350, value=1000, step=10)

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    ser.write(f"{target_pwm}\n".encode())
except Exception as e:
    st.sidebar.error(f"Serial Error: {e}")
    ser = None

col1, col2, col3 = st.columns(3)
metric_thrust = col1.empty()
metric_power = col2.empty()
metric_efficiency = col3.empty()

st.markdown("---")

st.subheader("Live Telemetry & Performance Curves")
graph_col1, graph_col2 = st.columns(2)

with graph_col1:
    st.markdown("**Transient Response: Thrust & Power**")
    time_series_chart = st.empty()
    st.markdown("**Aerodynamic Thrust Curve**")
    thrust_curve_chart = st.empty()

with graph_col2:
    st.markdown("**Electrical Health: Voltage & Current**")
    electrical_chart = st.empty()
    st.markdown("**System Efficiency (g/W)**")
    efficiency_curve_chart = st.empty()

if st.button("Start Telemetry Stream") and ser:
    while True:
        try:
            line = ser.readline().decode('utf-8').strip()
            if line:
                payload = json.loads(line)
                new_row = pd.DataFrame([payload])

                st.session_state.data = pd.concat([st.session_state.data, new_row], ignore_index=True)
                if len(st.session_state.data) > 150:
                    st.session_state.data = st.session_state.data.iloc[1:]

                df = st.session_state.data.copy()
                df['efficiency_g_W'] = df.apply(lambda row: row['thrust_g'] / row['power_W'] if row['power_W'] > 0.1 else 0, axis=1)

                current_thrust = df['thrust_g'].iloc[-1]
                current_power = df['power_W'].iloc[-1]
                current_voltage = df['voltage'].iloc[-1]
                current_amps = df['current_A'].iloc[-1]
                efficiency = df['efficiency_g_W'].iloc[-1]

                metric_thrust.metric("Live Thrust (g)", f"{current_thrust:.1f}")
                metric_power.metric("Live Power (W)", f"{current_power:.1f}", f"{current_voltage:.2f} V | {current_amps:.2f} A")
                metric_efficiency.metric("Efficiency (g/W)", f"{efficiency:.2f}")

                time_series_chart.line_chart(df[['thrust_g', 'power_W']])
                electrical_chart.line_chart(df[['voltage', 'current_A']])
                thrust_curve_chart.scatter_chart(df, x='pwm', y='thrust_g')
                efficiency_curve_chart.scatter_chart(df, x='pwm', y='efficiency_g_W')

            time.sleep(0.05)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            st.error(f"Stream interrupted: {e}")
            break