"""Overview — KPI cards, daily activity, AP progression."""
import streamlit as st

st.set_page_config(page_title="Overview", page_icon="📊", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

# ── KPI bar (2 rows) ──
prof_df = data.get("_profile")
agent_name = faction = level = ap = created_full = "–"
if prof_df is not None:
    pmap = dict(zip(prof_df["key"], prof_df["value"]))
    agent_name = pmap.get("Agent name", "–")
    faction = pmap.get("Faction", "–")
    level = pmap.get("Agent level", "–")
    ap = pmap.get("Action Points (AP)", "–")
    created_full = pmap.get("Creation Time", "–")
if ap != "–" and ap.isdigit():
    ap = f"{int(ap)/1e6:.1f}M"
created = created_full[:10] if len(created_full) > 10 else created_full

h_df = data.get("hacks")
dep = data.get("deploys")
links = data.get("links_created")
fields = data.get("regions_created")

r1 = st.columns(4)
r1[0].metric("Agent", agent_name)
r1[1].metric("Faction", faction)
r1[2].metric("Level", level)
r1[3].metric("AP", ap)

r2 = st.columns(4)
r2[0].metric("Registered", created)
r2[1].metric("Hacks", f"{len(h_df):,}" if h_df is not None else "–")
r2[2].metric("Deploys", f"{len(dep):,}" if dep is not None else "–")

# extra: portal count
ports = data.get("portal_guids_visited")
r2[3].metric("Portals Visited", f"{ports['Unique_ID'].nunique():,}" if ports is not None and len(ports) > 0 else "–")

st.divider()
st.title("Overview")

# ── daily activity line ──
left, right = st.columns([3, 2])

with left:
    st.subheader("Daily Activity")
    source_options = {
        "Hacks": "hacks", "Deploys": "deploys", "Links": "links_created",
        "Fields": "regions_created", "Reso Kills": "resonators_destroyed",
        "Mods": "mods_deployed", "Neutralize": "portals_neutralized",
    }
    selected = st.multiselect("Actions to show", list(source_options.keys()),
                              default=["Hacks", "Deploys"], key="daily_src")
    colors_map = {
        "Hacks": "#4CAF50", "Deploys": "#2196F3", "Links": "#FF9800",
        "Fields": "#9C27B0", "Reso Kills": "#F44336",
        "Mods": "#00BCD4", "Neutralize": "#795548",
    }

    fig = go.Figure()
    has_data = False
    for label in selected:
        dk = source_options[label]
        df = data.get(dk)
        if df is not None and len(df) > 0:
            d = df.copy()
            d["Date"] = d["Time"].dt.date
            daily = d.groupby("Date").size().reset_index(name=label)
            daily["Date"] = pd.to_datetime(daily["Date"])
            daily = daily.sort_values("Date")
            fig.add_trace(go.Scatter(
                x=daily["Date"], y=daily[label],
                mode="lines", name=label,
                line=dict(color=colors_map.get(label, "#999"), width=1.2),
                hovertemplate=f"%{{x|%Y-%m-%d}}: %{{y}} {label}<extra></extra>",
            ))
            has_data = True
    if has_data:
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=5, b=5),
                          xaxis_title="", yaxis_title="Count",
                          legend=dict(orientation="h", y=1.1, font=dict(size=10)))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Select actions to display.")

# ── action breakdown ──
with right:
    st.subheader("Action Breakdown")
    behaviors = {
        "Hacks": "hacks", "Deploys": "deploys", "Links": "links_created",
        "Fields": "regions_created", "Reso Kills": "resonators_destroyed",
        "Mods": "mods_deployed", "Neutralize": "portals_neutralized",
    }
    counts = {}
    for label, key in behaviors.items():
        df = data.get(key)
        if df is not None and len(df) > 0:
            counts[label] = len(df)
    if counts:
        fig_pie = go.Figure(data=go.Pie(
            labels=list(counts.keys()), values=list(counts.values()),
            hole=0.4, marker=dict(colors=px.colors.qualitative.Set2),
            textinfo="label+percent",
            hovertemplate="%{label}: %{value:,}<extra></extra>",
        ))
        fig_pie.update_layout(height=280, margin=dict(l=10, r=10, t=5, b=5), showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No action data.")

# ── estimated AP progression ──
st.subheader("Estimated AP Progression")
st.caption("Estimated from action values: Hack=100, Deploy=125, Link=313, Field=1250, Reso kill=75")

if h_df is not None:
    h = h_df.copy()
    h["Date"] = h["Time"].dt.date
    date_range = pd.date_range(h["Date"].min(), h["Date"].max(), freq="D")
    cum = pd.Series(0.0, index=date_range)

    cum = cum.add(h.groupby("Date").size() * 100, fill_value=0)
    if dep is not None:
        dep_c = dep.copy(); dep_c["Date"] = dep_c["Time"].dt.date
        cum = cum.add(dep_c.groupby("Date").size() * 125, fill_value=0)
    if links is not None:
        links_c = links.copy(); links_c["Date"] = links_c["Time"].dt.date
        cum = cum.add(links_c.groupby("Date").size() * 313, fill_value=0)
    if fields is not None:
        fields_c = fields.copy(); fields_c["Date"] = fields_c["Time"].dt.date
        cum = cum.add(fields_c.groupby("Date").size() * 1250, fill_value=0)
    resos = data.get("resonators_destroyed")
    if resos is not None:
        resos = resos.copy(); resos["Date"] = resos["Time"].dt.date
        cum = cum.add(resos.groupby("Date")["Value"].sum() * 75, fill_value=0)

    ap_df = pd.DataFrame({"Date": date_range, "AP_M": cum.cumsum().values / 1_000_000})
    fig_ap = go.Figure()
    fig_ap.add_trace(go.Scatter(
        x=ap_df["Date"], y=ap_df["AP_M"], mode="lines", fill="tozeroy",
        line=dict(color="#4CAF50", width=1),
        hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}M AP<extra></extra>",
        name="Est. AP",
    ))
    fig_ap.update_layout(height=280, margin=dict(l=10, r=10, t=5, b=5), xaxis_title="", yaxis_title="Million AP")
    st.plotly_chart(fig_ap, use_container_width=True)
else:
    st.info("Not enough data for AP estimate.")
