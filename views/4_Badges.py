"""Badges — medal progress bars and tier tracking."""
import streamlit as st

st.set_page_config(page_title="Badges", page_icon="🏅", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import pandas as pd
from badge_config import BADGES, get_tier, get_tier_color, BADGE_TIERS, TIER_COLORS

st.title("Badge Progress")
st.caption("Tier thresholds from ingress.plus/badges. Data keys aligned with export file mapping.")

rows = []
for b in BADGES:
    dkey = b["data_key"]
    df = data.get(dkey)
    val = 0.0
    if df is not None and len(df) > 0:
        agg = b["agg"]
        try:
            if agg == "count":
                val = float(len(df))
            elif agg == "sum":
                val = float(df["Value"].sum()) if "Value" in df.columns else 0.0
            elif agg == "nunique":
                col = "Unique_ID" if "Unique_ID" in df.columns else "Value"
                val = float(df[col].nunique())
            elif agg == "max":
                val = float(df["Value"].max()) if "Value" in df.columns else 0.0
        except Exception:
            pass

    tier, next_t = get_tier(val, b["threshold"])
    onyx_t = b["threshold"][-1]
    mult = val / onyx_t if onyx_t > 0 else 1.0
    pct = min(val / next_t, 1.0) if next_t else 1.0

    rows.append({
        "name": b["name"], "name_zh": b["name_zh"], "value": val,
        "tier": tier, "next_thresh": next_t, "progress": pct,
        "category": b["category"], "multiplier": mult, "note": b.get("note", ""),
    })

badge_df = pd.DataFrame(rows)
badge_df["done"] = badge_df["tier"] == "Onyx"
badge_df = badge_df.sort_values(["done", "progress"], ascending=[True, False])

cats = sorted(badge_df["category"].unique().tolist())
sel_cat = st.selectbox("Category", ["All"] + cats, key="badge_filter")
if sel_cat != "All":
    badge_df = badge_df[badge_df["category"] == sel_cat]

st.divider()

for _, row in badge_df.iterrows():
    c1, c2, c3, c4 = st.columns([3, 4, 1.2, 1.8])
    with c1:
        st.write(f"**{row['name']}**")
        if row.get("note"):
            st.caption(row["note"])
    with c2:
        color = get_tier_color(row["tier"])
        if row["tier"] == "Onyx" and row["multiplier"] > 1.0:
            val_str = f"{row['value']:,.0f} — {row['multiplier']:.1f}× Onyx"
            bar_color = "#FF3333"
        elif row["tier"] == "Onyx":
            val_str = f"{row['value']:,.0f} — maxed"
            bar_color = "#FF3333"
        else:
            val_str = f"{row['value']:,.0f}" if row["value"] < 100000 else f"{row['value']/1000:.1f}K"
            bar_color = color
        pct = max(min(row["progress"], 1.0), 0.001)
        st.markdown(f"""
        <div style="background:#1a1a2e;border-radius:6px;height:22px;overflow:hidden;border:1px solid #333;">
            <div style="background:{bar_color};height:100%;width:{pct*100:.1f}%;display:flex;align-items:center;padding-left:8px;font-size:12px;color:white;font-weight:600;">
                {val_str}
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"<span style='color:{color};font-weight:600'>{row['tier']}</span>", unsafe_allow_html=True)
    with c4:
        if row["tier"] == "Onyx":
            if row["multiplier"] > 1.0:
                st.write(f"× {row['multiplier']:.1f}")
            else:
                st.write("✓ Max")
        elif row["next_thresh"] is not None:
            diff = row["next_thresh"] - row["value"]
            st.write(f"→ {row['next_thresh']:,}" if diff > 1000 else f"→ {row['next_thresh']:.0f}")
        else:
            st.write("✓")

st.divider()
st.markdown("Color legend: " + " | ".join(
    f"<span style='color:{TIER_COLORS[t]};font-weight:600'>{t}</span>" for t in BADGE_TIERS
), unsafe_allow_html=True)
