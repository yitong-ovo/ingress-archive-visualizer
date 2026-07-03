"""Economy — C.O.R.E. subscription overview & CMU balance."""
import streamlit as st

st.set_page_config(page_title="Economy", page_icon="💰", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import plotly.graph_objects as go
import pandas as pd
import numpy as np

st.title("Economy & Subscriptions")

# ── C.O.R.E. subscription intervals ──
st.subheader("C.O.R.E. Subscription")
subs = data.get("subscriptions_monthly")

if subs is not None and len(subs) > 0:
    subs = subs.sort_values("Time").copy()
    # Merge consecutive months within 35 days into periods
    subs["Diff"] = subs["Time"].diff().dt.days.fillna(0)
    subs["Period"] = (subs["Diff"] > 35).cumsum()
    periods = subs.groupby("Period")["Time"].agg(["min", "max", "count"]).reset_index()
    periods["End"] = periods["max"] + pd.Timedelta(days=30)

    # Account lifecycle for X axis
    prof = data.get("_profile")
    acct_created = None
    if prof is not None:
        pmap = dict(zip(prof["key"], prof["value"]))
        created_str = pmap.get("Creation Time", "")
        if created_str:
            acct_created = pd.to_datetime(created_str, errors="coerce", utc=True)

    x_min = acct_created if acct_created is not None else periods["min"].min() - pd.Timedelta(days=30)
    x_max = periods["End"].max() + pd.Timedelta(days=30)

    fig_sub = go.Figure()
    for i, (_, p) in enumerate(periods.iterrows()):
        fig_sub.add_trace(go.Scatter(
            x=[p["min"], p["End"]], y=[1, 1],
            mode="lines", line=dict(color="#4CAF50", width=24),
            hovertemplate=f"Subscription #{i+1}<br>Start: {p['min'].strftime('%Y-%m-%d')}<br>End: {p['End'].strftime('%Y-%m-%d')}<br>{p['count']} months<extra></extra>",
            name=f"Sub {i+1}",
        ))
    fig_sub.update_layout(
        height=180, margin=dict(l=10, r=10, t=5, b=5),
        xaxis=dict(range=[x_min, x_max], title=""),
        yaxis=dict(showticklabels=False, showgrid=False, range=[0, 2]),
        showlegend=False,
    )
    st.plotly_chart(fig_sub, width="stretch")
    st.caption(f"**{len(subs)}** monthly renewals across **{len(periods)}** subscription period(s). "
               f"Periods more than 35 days apart are shown as separate bars.")
else:
    st.info("No subscription data.")

# ── CMU balance ──
c1, c2 = st.columns([3, 2])

with c1:
    st.subheader("CMU Balance Over Time")
    store = data.get("store_purchases")
    if store is not None and len(store) > 0:
        store = store.sort_values("Time")
        valid = store[store["NewCMUBalance"].notna()].copy()
        if len(valid) > 0:
            fig_cmu = go.Figure()
            fig_cmu.add_trace(go.Scatter(
                x=valid["Time"], y=valid["NewCMUBalance"],
                mode="lines+markers", line=dict(color="#FF9800", width=1),
                marker=dict(size=3), name="CMU Balance",
                hovertemplate="%{x|%Y-%m-%d}: %{y} CMU<extra></extra>",
            ))
            fig_cmu.update_layout(height=300, margin=dict(l=10, r=10, t=5, b=5), yaxis_title="CMU")
            st.plotly_chart(fig_cmu, width="stretch")

with c2:
    st.subheader("CMU Spending")
    if store is not None and len(store) > 0:
        store = store.sort_values("Time").copy()
        store["Spent"] = -store["NewCMUBalance"].diff()
        spends = store[store["Spent"] > 0].copy()
        if len(spends) > 0:
            type_col = "TransactionType" if "TransactionType" in store.columns else "Item"
            sp_grp = spends.groupby(type_col)["Spent"].sum().sort_values(ascending=False)
            if len(sp_grp) > 0:
                fig_sp = go.Figure(data=go.Pie(
                    labels=sp_grp.index.tolist(), values=sp_grp.values.tolist(),
                    hole=0.4, textinfo="label+percent",
                    hovertemplate="%{label}: %{value:.0f} CMU<extra></extra>",
                ))
                fig_sp.update_layout(height=300, margin=dict(l=10, r=10, t=5, b=5), showlegend=False)
                st.plotly_chart(fig_sp, width="stretch")

st.subheader("Recent Transactions")
if store is not None:
    cols = [c for c in ["Time", "TransactionType", "Item", "NewCMUBalance"] if c in store.columns]
    st.dataframe(store[cols].tail(30), width="stretch", hide_index=True)
