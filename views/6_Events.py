"""Events — season points, anomaly portals, special events."""
import streamlit as st

st.set_page_config(page_title="Events", page_icon="🎯", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import plotly.graph_objects as go
import pandas as pd
from time_utils import local_month_start, timezone_selector

st.title("Events & Anomalies")
tz_name = timezone_selector()

# ── season points ──
season_files = {
    "Alpha": "event_alpha", "Bravo": "event_bravo", "Delta": "event_delta",
    "Echo": "event_echo", "Foxtrot": "event_foxtrot", "Golf": "event_golf",
    "India": "event_india", "Juliet": "event_juliet", "Kilo": "event_kilo",
    "Mike": "event_mike", "November": "event_november", "Oscar": "event_oscar",
    "+Alpha Op": "plus_alpha_global_op_points", "+Beta": "plus_beta_season_points",
    "+Gamma": "plus_gamma_season_points", "+Delta": "plus_delta_season_points",
    "+Theta": "plus_theta_season_points", "Orion": "orion_season_points",
    "Chronos": "operation_chronos_points", "Buried Memories": "buried_memories_event_points",
    "Cryptic Memories": "cryptic_memories_points",
    "Erased Memories": "erased_memories_global_op_points",
    "Shared Memories": "shared_memories_event_points",
    "Field Test": "field_test_dispatch_points",
}

pts = {}
for name, key in season_files.items():
    df = data.get(key)
    if df is not None and len(df) > 0:
        p = df["Value"].sum() if "Value" in df.columns else len(df)
        if p > 0:
            pts[name] = p

if pts:
    st.subheader("Season & Event Points")
    labels = list(pts.keys())
    values = list(pts.values())
    fig = go.Figure(data=go.Bar(
        x=labels, y=values, marker_color="#4CAF50",
        text=[f"{v:.0f}" for v in values],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="%{x}: %{y} points<extra></extra>",
    ))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=5, b=80), xaxis=dict(tickangle=-45))
    st.plotly_chart(fig, width="stretch")

# ── anomaly portals ──
anomaly_keys = {
    "Buried Memories": "buried_memories_anomaly_guids",
    "Cryptic Memories": "cryptic_memories_anomaly_guids",
    "Erased Memories": "erased_memories_anomaly_guids",
    "Shared Memories": "shared_memories_anomaly_guids",
    "Ctrl 2023": "ctrl_anomaly_guids_2023",
    "Discoverie 2023": "discoverie_anomaly_guids_2023",
    "Echo 2023": "echo_anomaly_guids_2023",
    "+Alpha Anomaly": "plus_alpha_anomaly_guids",
    "Orion Global": "orion_global_guids",
}
anom = {}
for name, key in anomaly_keys.items():
    df = data.get(key)
    if df is not None and len(df) > 0:
        c = df["Unique_ID"].nunique() if "Unique_ID" in df.columns else len(df)
        if c > 0:
            anom[name] = c

if anom:
    st.subheader("Anomaly Portal Interactions")
    st.table(pd.DataFrame({"Anomaly": list(anom.keys()), "Portals": list(anom.values())}))

# ── special event KPIs ──
st.subheader("Special Events")
c1, c2, c3, c4 = st.columns(4)
ss = data.get("second_sunday_events")
c1.metric("Second Sunday", len(ss) if ss is not None else 0)
nl = data.get("nl1331_meetup_points")
c2.metric("NL-1331 Meetups", len(nl) if nl is not None else 0)
md = data.get("mission_day_points")
c3.metric("Mission Day", len(md) if md is not None else 0)
courier = data.get("courier_ap_gained")
c4.metric("Courier AP", len(courier) if courier is not None else 0)

darkxm = data.get("darkxm_link_length")
if darkxm is not None and len(darkxm) > 0:
    st.metric("DarkXM Link (km)", f"{darkxm['Value'].sum():.1f}" if "Value" in darkxm.columns else str(len(darkxm)))

# ── Second Sunday timeline ──
if ss is not None and len(ss) > 0:
    st.subheader("Second Sunday Participation")
    ss_dates = local_month_start(ss["Time"], tz_name).dt.strftime("%Y-%m")
    ss_c = ss_dates.value_counts().sort_index()
    fig_ss = go.Figure(data=go.Bar(x=ss_c.index, y=ss_c.values, marker_color="#2196F3"))
    fig_ss.update_layout(height=200, margin=dict(l=10, r=10, t=5, b=60), xaxis=dict(tickangle=-45))
    st.plotly_chart(fig_ss, width="stretch")
