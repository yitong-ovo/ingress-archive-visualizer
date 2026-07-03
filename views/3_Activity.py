"""Activity — weekly trends, hour×day heatmaps, session durations."""
import streamlit as st

st.set_page_config(page_title="Activity", page_icon="📈", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import plotly.graph_objects as go
import pandas as pd

st.title("Activity Analysis")


def week_start(series: pd.Series) -> pd.Series:
    return series.dt.tz_convert(None).dt.to_period("W").dt.start_time

h_df = data.get("hacks")
dep = data.get("deploys")
links = data.get("links_created")
fields = data.get("regions_created")

# ── weekly trend ──
st.subheader("Weekly Activity Trend")
if h_df is not None and len(h_df) > 0:
    h = h_df.copy()
    h["Week"] = week_start(h["Time"])
    w = h.groupby("Week").size().reset_index(name="Hacks")
    for df_k, lbl in [(dep, "Deploys"), (links, "Links"), (fields, "Fields")]:
        if df_k is not None and len(df_k) > 0:
            df_k = df_k.copy()
            df_k["Week"] = week_start(df_k["Time"])
            w = w.merge(df_k.groupby("Week").size().reset_index(name=lbl), on="Week", how="outer")
    w = w.fillna(0).sort_values("Week")
    colors = {"Hacks": "#4CAF50", "Deploys": "#2196F3", "Links": "#FF9800", "Fields": "#9C27B0"}
    fig = go.Figure()
    for c in ["Hacks", "Deploys", "Links", "Fields"]:
        if c in w.columns:
            fig.add_trace(go.Scatter(
                x=w["Week"], y=w[c], mode="lines", name=c,
                line=dict(color=colors[c], width=1.5),
                hovertemplate="%{x|%Y-%m-%d}: %{y} " + c.lower() + "<extra></extra>",
            ))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=5, b=5),
                      legend=dict(orientation="h", y=1.1), xaxis_title="")
    st.plotly_chart(fig, width="stretch")
else:
    st.info("No hack data.")

# ── hour × day ──
c1, c2 = st.columns(2)
with c1:
    st.subheader("Hour × Day")
    sources = {"Hacks": "hacks", "Deploys": "deploys", "Links": "links_created", "Fields": "regions_created"}
    src_label = st.selectbox("Data source", list(sources.keys()), key="hour_day_src")
    src_df = data.get(sources[src_label])
    if src_df is not None and len(src_df) > 0:
        s = src_df.copy()
        s["Hour"] = s["Time"].dt.hour
        s["DOW"] = s["Time"].dt.dayofweek
        heat = s.groupby(["DOW", "Hour"]).size().unstack(fill_value=0)
        heat = heat.reindex(index=range(7), columns=range(24), fill_value=0)
        days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        fig2 = go.Figure(data=go.Heatmap(
            z=heat.values, x=[f"{hh}:00" for hh in range(24)], y=days,
            colorscale="Blues",
            hovertemplate="%{y} %{x}: %{z} " + src_label.lower() + "<extra></extra>",
        ))
        fig2.update_layout(height=300, margin=dict(l=10, r=10, t=5, b=5))
        st.plotly_chart(fig2, width="stretch")
    else:
        st.info(f"No {src_label} data.")

# ── session duration ──
with c2:
    st.subheader("Session Duration")
    st.caption("How long each login session lasted. One bar = one session.")
    logins = data.get("Logins")
    if logins is not None and len(logins) > 0:
        dur = logins["Duration"].dropna().clip(upper=240)
        if len(dur) > 0:
            avg_m = dur.mean()
            med_m = dur.median()
            def fmt_m(m):
                if m >= 60:
                    h = int(m // 60)
                    mins = int(m % 60)
                    return f"{h}h {mins}m" if mins > 0 else f"{h}h"
                return f"{int(m)}m"
            c_avg, c_med = st.columns(2)
            c_avg.metric("Average session", fmt_m(avg_m))
            c_med.metric("Median session", fmt_m(med_m))

            fig3 = go.Figure(data=go.Histogram(x=dur, nbinsx=40, marker_color="#4CAF50"))
            fig3.add_vline(x=dur.mean(), line_dash="dash", line_color="red",
                           annotation_text=f"Avg: {fmt_m(avg_m)}")
            fig3.update_layout(
                height=250, margin=dict(l=10, r=10, t=5, b=5),
                xaxis=dict(title="Minutes", tickmode="array",
                           tickvals=[0, 30, 60, 90, 120, 180, 240],
                           ticktext=["0", "30m", "1h", "1h30m", "2h", "3h", "4h"]),
                yaxis_title="Sessions", bargap=0.05,
            )
            st.plotly_chart(fig3, width="stretch")
        else:
            st.info("No session duration data.")
    else:
        st.info("No login data.")

# ── cumulative ──
st.subheader("Cumulative Hacks")
if h_df is not None and len(h_df) > 0:
    h = h_df.copy()
    h["Date"] = h["Time"].dt.date
    cum = h.groupby("Date").size().cumsum()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=cum.index, y=cum.values, mode="lines",
        line=dict(color="#4CAF50", width=1), name="Hacks",
        hovertemplate="%{x|%Y-%m-%d}: %{y:,} hacks<extra></extra>",
    ))
    fig4.update_layout(height=250, margin=dict(l=10, r=10, t=5, b=5))
    st.plotly_chart(fig4, width="stretch")
