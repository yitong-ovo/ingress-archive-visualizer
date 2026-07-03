"""History - generic long-form interpretation for Ingress exports."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
from time_utils import local_date, local_time_text, timezone_selector, to_local_time

st.set_page_config(page_title="History", page_icon="📚", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

st.title("Historical Review")
st.caption(
    "A generic archive-style readout. Sections appear when the export contains the required files; "
    "numbers are computed from the loaded export, not hard-coded."
)


FUTURE_CUTOFF = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
VALID_LAT_RANGE = (-85, 85)
VALID_LON_RANGE = (-180, 180)
MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
LOCATION_SOURCE_COLORS = {
    "Game Log": [76, 175, 80, 135],
    "Location History": [33, 150, 243, 120],
    "Player Journey": [255, 152, 0, 135],
    "Portal History": [156, 39, 176, 125],
    "POI Submissions": [96, 125, 139, 150],
}
HISTORY_CACHE_VERSION = 1


def fmt_int(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except Exception:
        return "0"


def fmt_num(value, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return "0"


def data_frame(key: str) -> pd.DataFrame | None:
    df = data.get(key)
    if df is None or len(df) == 0:
        return None
    return df


def _history_cache_key(name: str, *parts) -> tuple:
    return (st.session_state.get("source_id", ""), name, HISTORY_CACHE_VERSION, *parts)


def with_time(df: pd.DataFrame | None, exclude_future: bool = True) -> pd.DataFrame | None:
    if df is None or "Time" not in df.columns:
        return None
    out = df.copy()
    out["Time"] = pd.to_datetime(out["Time"], errors="coerce", utc=True)
    out = out.dropna(subset=["Time"])
    if exclude_future:
        out = out[out["Time"] < FUTURE_CUTOFF]
    return out


def value_sum(df: pd.DataFrame | None, col: str = "Value") -> float:
    if df is None or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def unique_count(df: pd.DataFrame | None, col: str = "Unique_ID") -> int:
    if df is None or col not in df.columns:
        return 0
    return int(df[col].dropna().nunique())


def aggregate_value(df: pd.DataFrame | None, mode: str) -> float:
    if df is None:
        return 0.0
    if mode == "sum":
        return value_sum(df)
    if mode == "nunique":
        col = "Unique_ID" if "Unique_ID" in df.columns else "Value"
        return unique_count(df, col)
    if mode == "max":
        if "Value" not in df.columns:
            return 0.0
        return float(pd.to_numeric(df["Value"], errors="coerce").max())
    return float(len(df))


def daily_metric(key: str, mode: str = "count") -> pd.DataFrame:
    cache = st.session_state.setdefault("_history_daily_cache", {})
    cache_key = _history_cache_key("daily", key, mode, exclude_future, tz_name)
    if cache_key in cache:
        return cache[cache_key]

    df = with_time(data_frame(key), exclude_future)
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["Date", "Value"])
    work = df.copy()
    work["Date"] = local_date(work["Time"], tz_name)
    if mode == "sum" and "Value" in work.columns:
        out = work.groupby("Date")["Value"].sum().reset_index(name="Value")
    elif mode == "nunique" and "Unique_ID" in work.columns:
        out = work.groupby("Date")["Unique_ID"].nunique().reset_index(name="Value")
    else:
        out = work.groupby("Date").size().reset_index(name="Value")
    out["Date"] = pd.to_datetime(out["Date"])
    out = out.sort_values("Date")
    cache[cache_key] = out
    return out


def top_daily_records(records: list[dict], n: int = 20) -> pd.DataFrame:
    rows = []
    for rec in records:
        daily = daily_metric(rec["key"], rec.get("mode", "count"))
        if len(daily) == 0:
            continue
        top = daily.nlargest(1, "Value").iloc[0]
        rows.append({
            "Record": rec["label"],
            "Date": top["Date"].strftime("%Y-%m-%d"),
            "Value": top["Value"],
            "Unit": rec.get("unit", "events"),
            "Source": rec["key"],
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Value", ascending=False).head(n)


def metric_series(sources: list[dict], exclude_future: bool) -> pd.DataFrame:
    frames = []
    for src in sources:
        df = with_time(data_frame(src["key"]), exclude_future)
        if df is None or len(df) == 0:
            continue
        work = df[["Time"]].copy()
        work["Category"] = src["category"]
        work["Signal"] = src["label"]
        work["Weight"] = 1.0
        frames.append(work)
    if not frames:
        return pd.DataFrame(columns=["Time", "Category", "Signal", "Weight"])
    return pd.concat(frames, ignore_index=True).dropna(subset=["Time"])


def location_points(exclude_zero: bool, exclude_future: bool) -> pd.DataFrame:
    frames = []
    specs = [
        ("game_log", "Game Log"),
        ("GameplayLocationHistory", "Location History"),
        ("player_journey_actions", "Player Journey"),
        ("portal_history", "Portal History"),
        ("poi_submissions", "POI Submissions"),
    ]
    for key, label in specs:
        df = data_frame(key)
        if df is None or not {"Lat", "Lon"}.issubset(df.columns):
            continue
        keep = [c for c in ["Time", "Lat", "Lon", "Type", "Action", "Title"] if c in df.columns]
        sub = df[keep].copy()
        sub["Lat"] = pd.to_numeric(sub["Lat"], errors="coerce")
        sub["Lon"] = pd.to_numeric(sub["Lon"], errors="coerce")
        sub = sub.dropna(subset=["Lat", "Lon"])
        sub = sub[
            sub["Lat"].between(*VALID_LAT_RANGE)
            & sub["Lon"].between(*VALID_LON_RANGE)
        ]
        if "Time" in sub.columns:
            sub["Time"] = pd.to_datetime(sub["Time"], errors="coerce", utc=True)
            if exclude_future:
                sub = sub[sub["Time"].isna() | (sub["Time"] < FUTURE_CUTOFF)]
        if exclude_zero:
            sub = sub[(sub["Lat"].abs() > 0.1) | (sub["Lon"].abs() > 0.1)]
        if len(sub) == 0:
            continue
        sub["Source"] = label
        frames.append(sub)
    if not frames:
        return pd.DataFrame(columns=["Lat", "Lon", "Source"])
    return pd.concat(frames, ignore_index=True)


def cached_location_points(exclude_zero: bool, exclude_future: bool) -> pd.DataFrame:
    cache = st.session_state.setdefault("_history_location_cache", {})
    cache_key = _history_cache_key("location-points", exclude_zero, exclude_future)
    if cache_key not in cache:
        cache[cache_key] = location_points(exclude_zero, exclude_future)
    return cache[cache_key]


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    radius = 6371.0
    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return radius * 2 * np.arcsin(np.sqrt(a))


def map_view_state(points: pd.DataFrame) -> pdk.ViewState:
    center_lat = float(points["Lat"].median())
    center_lon = float(points["Lon"].median())
    span = max(float(points["Lat"].max() - points["Lat"].min()), float(points["Lon"].max() - points["Lon"].min()), 0.001)
    zoom = float(np.clip(8 - np.log2(span), 2, 13))
    return pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)


def source_color(source: str) -> list[int]:
    return LOCATION_SOURCE_COLORS.get(str(source), [90, 90, 90, 120])


def prepare_location_points(points: pd.DataFrame, max_points: int, tz_name: str) -> pd.DataFrame:
    if len(points) > max_points:
        points = points.sample(max_points, random_state=42)
    out = points[[c for c in ["Time", "Lat", "Lon", "Source", "Action", "Type", "Title"] if c in points.columns]].copy()
    if "Time" in out.columns:
        out["TimeText"] = local_time_text(out["Time"], tz_name)
    else:
        out["TimeText"] = ""
    for col in ["Action", "Type", "Title"]:
        if col not in out.columns:
            out[col] = ""
    out["color"] = out["Source"].map(source_color)
    out["TooltipTitle"] = out["Source"].astype(str)
    out["TooltipDetail"] = out["TimeText"].fillna("")
    out.loc[out["Action"].astype(str).str.len() > 0, "TooltipDetail"] += " | " + out["Action"].astype(str)
    out.loc[out["Type"].astype(str).str.len() > 0, "TooltipDetail"] += " | " + out["Type"].astype(str)
    out.loc[out["Title"].astype(str).str.len() > 0, "TooltipDetail"] += " | " + out["Title"].astype(str).str.slice(0, 80)
    return out


def aggregate_location_cells(points: pd.DataFrame, cell_m: int, max_cells: int) -> pd.DataFrame:
    center_lat = float(points["Lat"].median())
    lat_step = cell_m / 111_000.0
    lon_step = cell_m / (111_000.0 * max(np.cos(np.deg2rad(center_lat)), 0.2))
    work = points[["Lat", "Lon", "Source"]].copy()
    work["lat_cell"] = np.floor(work["Lat"].to_numpy() / lat_step) * lat_step
    work["lon_cell"] = np.floor(work["Lon"].to_numpy() / lon_step) * lon_step
    grouped = (
        work.groupby(["lat_cell", "lon_cell"])
        .agg(Points=("Source", "size"), Sources=("Source", lambda s: ", ".join(sorted(set(s)))))
        .reset_index()
    )
    grouped = grouped.sort_values("Points", ascending=False).head(max_cells).copy()
    grouped["Lat"] = grouped["lat_cell"] + lat_step / 2
    grouped["Lon"] = grouped["lon_cell"] + lon_step / 2
    max_log = float(np.log1p(grouped["Points"]).max()) if len(grouped) else 1.0
    grouped["radius"] = np.clip(cell_m * (0.8 + np.log1p(grouped["Points"]) / max_log), cell_m * 0.8, cell_m * 2.3)
    grouped["color"] = grouped["Points"].map(lambda c: [33, 113, 181, int(85 + min(np.log1p(c) / max_log, 1) * 130)])
    grouped["TooltipTitle"] = grouped["Points"].map(lambda c: f"{int(c):,} points")
    grouped["TooltipDetail"] = grouped["Sources"]
    return grouped


def build_geo_clusters(points: pd.DataFrame, cluster_size: float, tz_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = points.copy()
    work["Lat bin"] = (work["Lat"] / cluster_size).round() * cluster_size
    work["Lon bin"] = (work["Lon"] / cluster_size).round() * cluster_size
    work["Cluster"] = work["Lat bin"].map(lambda v: f"{v:.3f}") + ", " + work["Lon bin"].map(lambda v: f"{v:.3f}")
    if "Time" in work.columns:
        work["LocalTime"] = to_local_time(work["Time"], tz_name)
        work["Year"] = work["LocalTime"].dt.year
        work["LocalDate"] = work["LocalTime"].dt.date
    else:
        work["Year"] = np.nan
        work["LocalDate"] = np.nan

    source_counts = work.groupby(["Cluster", "Source"]).size().reset_index(name="SourcePoints")
    dominant = source_counts.sort_values(["Cluster", "SourcePoints"], ascending=[True, False]).drop_duplicates("Cluster")

    summary = (
        work.groupby("Cluster")
        .agg(
            Lat=("Lat", "median"),
            Lon=("Lon", "median"),
            Points=("Source", "size"),
            First=("LocalTime", "min"),
            Last=("LocalTime", "max"),
            ActiveDays=("LocalDate", "nunique"),
            ActiveYears=("Year", "nunique"),
            Sources=("Source", lambda s: ", ".join(sorted(set(s)))),
        )
        .reset_index()
        .merge(dominant[["Cluster", "Source", "SourcePoints"]], on="Cluster", how="left")
        .rename(columns={"Source": "Dominant source"})
    )
    summary["Dominant share"] = summary["SourcePoints"] / summary["Points"]
    summary["Rank"] = summary["Points"].rank(method="first", ascending=False).astype(int)
    summary["Place"] = "#" + summary["Rank"].astype(str) + " " + summary["Cluster"]
    max_log = float(np.log1p(summary["Points"]).max()) if len(summary) else 1.0
    summary["radius"] = np.clip(350 * (0.8 + np.log1p(summary["Points"]) / max_log), 250, 1600)
    summary["color"] = summary["Dominant source"].map(source_color)
    summary["FirstText"] = summary["First"].dt.strftime("%Y-%m-%d").fillna("unknown")
    summary["LastText"] = summary["Last"].dt.strftime("%Y-%m-%d").fillna("unknown")
    summary["TooltipTitle"] = summary["Place"]
    summary["TooltipDetail"] = (
        summary["Points"].map(lambda v: f"{int(v):,} points")
        + " | " + summary["Dominant source"].fillna("unknown")
        + " | " + summary["FirstText"] + " -> " + summary["LastText"]
    )
    work = work.merge(summary[["Cluster", "Place", "Rank"]], on="Cluster", how="left")
    return summary.sort_values("Points", ascending=False), work


def cached_geo_clusters(
    points: pd.DataFrame,
    cluster_size: float,
    tz_name: str,
    exclude_zero: bool,
    exclude_future: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache = st.session_state.setdefault("_history_geo_cluster_cache", {})
    cache_key = _history_cache_key(
        "geo-clusters",
        round(float(cluster_size), 6),
        tz_name,
        exclude_zero,
        exclude_future,
    )
    if cache_key not in cache:
        cache.clear()
        cache[cache_key] = build_geo_clusters(points, cluster_size, tz_name)
    return cache[cache_key]


def yearly_marker_layers(timed_points: pd.DataFrame, places: pd.DataFrame, mode: str) -> tuple[list[pdk.Layer], pd.DataFrame]:
    if len(timed_points) == 0 or "Year" not in timed_points.columns:
        return [], pd.DataFrame()
    timed = timed_points.dropna(subset=["Year"]).copy()
    timed["Year"] = timed["Year"].astype(int)

    if mode == "Dominant place per year":
        year_place = (
            timed.groupby(["Year", "Place"])
            .size()
            .reset_index(name="Points")
            .sort_values(["Year", "Points"], ascending=[True, False])
            .drop_duplicates("Year")
        )
        centers = year_place.merge(
            places[["Place", "Lat", "Lon", "Sources", "Dominant source"]],
            on="Place",
            how="left",
        ).sort_values("Year")
        centers["Marker"] = centers["Place"]
        centers["TooltipDetail"] = (
            centers["Marker"]
            + " | " + centers["Points"].map(lambda v: f"{int(v):,} points")
            + " | " + centers["Dominant source"].fillna("unknown")
        )
    else:
        year_place = (
            timed.groupby(["Year", "Place"])
            .size()
            .reset_index(name="Points")
            .merge(places[["Place", "Lat", "Lon"]], on="Place", how="left")
            .dropna(subset=["Lat", "Lon"])
        )
        centers = (
            year_place.groupby("Year")
            .apply(lambda g: pd.Series({
                "Lat": np.average(g["Lat"], weights=g["Points"]),
                "Lon": np.average(g["Lon"], weights=g["Points"]),
                "Points": g["Points"].sum(),
                "Marker": f"{len(g):,} active places",
            }), include_groups=False)
            .reset_index()
            .sort_values("Year")
        )
        centers["TooltipDetail"] = centers["Marker"] + " | " + centers["Points"].map(lambda v: f"{int(v):,} points")

    if len(centers) == 0:
        return [], centers
    centers["TooltipTitle"] = centers["Year"].astype(str)
    centers["YearText"] = centers["Year"].astype(str)
    centers["color"] = [[30, 30, 30, 230]] * len(centers)
    centers["radius"] = np.clip(280 + np.log1p(centers["Points"]) * 70, 380, 1300)
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            id="yearly-centers",
            data=centers,
            get_position="[Lon, Lat]",
            get_fill_color="color",
            get_radius="radius",
            radius_min_pixels=3,
            radius_max_pixels=12,
            pickable=True,
            auto_highlight=True,
        )
    ]
    layers.append(pdk.Layer(
        "TextLayer",
        id="year-labels",
        data=centers,
        get_position="[Lon, Lat]",
        get_text="YearText",
        get_color=[0, 0, 0, 230],
        get_size=15,
        get_alignment_baseline="'bottom'",
        get_pixel_offset=[0, -12],
        pickable=False,
    ))
    if len(centers) > 1:
        segments = pd.DataFrame({
            "from_lon": centers["Lon"].iloc[:-1].to_numpy(),
            "from_lat": centers["Lat"].iloc[:-1].to_numpy(),
            "to_lon": centers["Lon"].iloc[1:].to_numpy(),
            "to_lat": centers["Lat"].iloc[1:].to_numpy(),
            "From": centers["Year"].iloc[:-1].to_numpy(),
            "To": centers["Year"].iloc[1:].to_numpy(),
        })
        segments["TooltipTitle"] = segments["From"].astype(str) + " -> " + segments["To"].astype(str)
        segments["TooltipDetail"] = mode
        layers.insert(0, pdk.Layer(
            "LineLayer",
            id="center-shift",
            data=segments,
            get_source_position="[from_lon, from_lat]",
            get_target_position="[to_lon, to_lat]",
            get_color=[20, 20, 20, 170],
            get_width=3,
            width_min_pixels=2,
            pickable=True,
        ))
    return layers, centers


def source_inventory() -> pd.DataFrame:
    rows = []
    for key, df in sorted(data.items()):
        if key.startswith("_") or df is None:
            continue
        rows.append({
            "Data source": key,
            "Rows": len(df),
            "Columns": ", ".join(map(str, df.columns[:8])),
            "Has time": "Time" in df.columns,
            "Has location": {"Lat", "Lon"}.issubset(df.columns),
            "Has unique id": "Unique_ID" in df.columns,
        })
    return pd.DataFrame(rows).sort_values("Rows", ascending=False)


exclude_future = st.sidebar.checkbox("Exclude future-dated rows", value=True)
exclude_zero = st.sidebar.checkbox("Exclude near-zero coordinates", value=True)
tz_name = timezone_selector()
st.sidebar.caption(f"Future cutoff: {FUTURE_CUTOFF.strftime('%Y-%m-%d')} UTC")
st.caption(f"Dates, records, and session timestamps use display timezone: **{tz_name}**")

profile = data_frame("_profile")
created = None
agent_name = "Unknown"
if profile is not None:
    pmap = dict(zip(profile["key"], profile["value"]))
    agent_name = pmap.get("Agent name", agent_name)
    created = pd.to_datetime(pmap.get("Creation Time", ""), errors="coerce", utc=True)

playstyle_sources = [
    {"category": "Explore", "label": "Visited portals", "key": "portal_guids_visited"},
    {"category": "Explore", "label": "Walking records", "key": "kilometers_walked_new"},
    {"category": "Explore", "label": "Drone visits", "key": "drone_visited_portal_guid"},
    {"category": "Supply", "label": "Hacks", "key": "hacks"},
    {"category": "Supply", "label": "Glyph attempts", "key": "glyph_hack_attempts"},
    {"category": "Supply", "label": "Keys hacked", "key": "keys_hacked"},
    {"category": "Supply", "label": "Passcodes", "key": "passcode_redeemed"},
    {"category": "Build", "label": "Deploys", "key": "deploys"},
    {"category": "Build", "label": "Mods deployed", "key": "mods_deployed"},
    {"category": "Build", "label": "Upgrades", "key": "resonators_upgraded"},
    {"category": "Build", "label": "Recharges", "key": "xm_recharged"},
    {"category": "Combat", "label": "Resonators destroyed", "key": "resonators_destroyed"},
    {"category": "Combat", "label": "Portals neutralized", "key": "portals_neutralized"},
    {"category": "Combat", "label": "Links destroyed", "key": "links_destroyed"},
    {"category": "Combat", "label": "Fields destroyed", "key": "regions_destroyed"},
    {"category": "Combat", "label": "Machina portals", "key": "machina_portals_neutralized"},
    {"category": "Link/Field", "label": "Links created", "key": "links_created"},
    {"category": "Link/Field", "label": "Fields created", "key": "regions_created"},
    {"category": "Missions/Events", "label": "Missions", "key": "missions_completed"},
    {"category": "Missions/Events", "label": "Second Sunday", "key": "second_sunday_events"},
    {"category": "Missions/Events", "label": "Agent ops", "key": "agent_ops_completed"},
]

activity = metric_series(playstyle_sources, exclude_future)

tab_life, tab_records, tab_geo, tab_portal, tab_fields, tab_special, tab_quality = st.tabs([
    "Lifecycle",
    "Records",
    "Geography",
    "Portal & POI",
    "Links & Fields",
    "Events & Economy",
    "Data Quality",
])

with tab_life:
    st.subheader("Lifecycle")
    if len(activity) == 0:
        st.info("No time-based activity sources available.")
    else:
        activity["Date"] = local_date(activity["Time"], tz_name)
        activity["Year"] = to_local_time(activity["Time"], tz_name).dt.year
        annual = (
            activity.groupby("Year")
            .agg(Signals=("Signal", "size"), ActiveDays=("Date", "nunique"), Categories=("Category", "nunique"))
            .reset_index()
            .sort_values("Year")
        )
        first = activity["Time"].min()
        last = activity["Time"].max()
        active_days = activity["Date"].nunique()
        peak_year = annual.loc[annual["Signals"].idxmax()]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Agent", agent_name)
        c2.metric("Observed span", f"{first:%Y-%m-%d} to {last:%Y-%m-%d}")
        c3.metric("Active days", fmt_int(active_days))
        c4.metric("Peak year", f"{int(peak_year['Year'])} ({fmt_int(peak_year['Signals'])})")

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=annual["Year"],
            y=annual["Signals"],
            name="Activity signals",
            marker_color="#4CAF50",
            hovertemplate="%{x}: %{y:,} signals<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=annual["Year"],
            y=annual["ActiveDays"],
            name="Active days",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color="#FF9800", width=2),
            hovertemplate="%{x}: %{y:,} active days<extra></extra>",
        ))
        fig.update_layout(
            height=340,
            margin=dict(l=10, r=10, t=20, b=30),
            yaxis=dict(title="Signals"),
            yaxis2=dict(title="Active days", overlaying="y", side="right"),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, width="stretch")

        st.subheader("Playstyle by Year")
        mix = activity.groupby(["Year", "Category"]).size().reset_index(name="Signals")
        total = mix.groupby("Year")["Signals"].transform("sum")
        mix["Share"] = mix["Signals"] / total
        fig_mix = go.Figure()
        for cat in ["Explore", "Supply", "Build", "Combat", "Link/Field", "Missions/Events"]:
            sub = mix[mix["Category"] == cat]
            if len(sub):
                fig_mix.add_trace(go.Bar(
                    x=sub["Year"],
                    y=sub["Share"] * 100,
                    name=cat,
                    customdata=sub["Signals"],
                    hovertemplate="%{x}<br>" + cat + ": %{y:.1f}% (%{customdata:,})<extra></extra>",
                ))
        fig_mix.update_layout(
            barmode="stack",
            height=360,
            margin=dict(l=10, r=10, t=20, b=30),
            yaxis_title="Share of activity signals",
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig_mix, width="stretch")

        st.subheader("Long Inactivity Gaps")
        dates = pd.Series(sorted(pd.to_datetime(list(set(activity["Date"])))))
        if len(dates) > 1:
            gaps = pd.DataFrame({"Previous active day": dates.shift(1), "Return day": dates})
            gaps["Gap days"] = (gaps["Return day"] - gaps["Previous active day"]).dt.days
            gaps = gaps.dropna().sort_values("Gap days", ascending=False).head(15)
            gaps["Previous active day"] = gaps["Previous active day"].dt.strftime("%Y-%m-%d")
            gaps["Return day"] = gaps["Return day"].dt.strftime("%Y-%m-%d")
            st.dataframe(gaps, width="stretch", hide_index=True)
        else:
            st.info("Not enough active days to calculate gaps.")

with tab_records:
    st.subheader("Personal Records")
    record_specs = [
        {"label": "Most hacks in a day", "key": "hacks"},
        {"label": "Most deploys in a day", "key": "deploys"},
        {"label": "Most resonators destroyed in a day", "key": "resonators_destroyed", "mode": "sum", "unit": "resonators"},
        {"label": "Most portals neutralized in a day", "key": "portals_neutralized", "mode": "nunique", "unit": "portals"},
        {"label": "Most links created in a day", "key": "links_created"},
        {"label": "Most fields created in a day", "key": "regions_created"},
        {"label": "Most MU in a day", "key": "mind_units_controlled", "mode": "sum", "unit": "MU"},
        {"label": "Most recharge XM in a day", "key": "xm_recharged", "mode": "sum", "unit": "XM"},
        {"label": "Most link distance in a day", "key": "link_length_kilometers", "mode": "sum", "unit": "km"},
        {"label": "Most glyph points in a day", "key": "glyph_hack_points", "mode": "sum", "unit": "points"},
        {"label": "Most Machina portals neutralized in a day", "key": "machina_portals_neutralized"},
    ]
    records = top_daily_records(record_specs)
    if len(records):
        records["Value"] = records["Value"].map(lambda v: fmt_num(v, 1) if abs(float(v)) % 1 else fmt_int(v))
        st.dataframe(records, width="stretch", hide_index=True)
    else:
        st.info("No daily record sources available.")

    st.subheader("Top Game Log Sessions")
    log = with_time(data_frame("game_log"), exclude_future)
    if log is not None and len(log):
        log = log.sort_values("Time").copy()
        log["LocalTime"] = to_local_time(log["Time"], tz_name)
        log["Action"] = log.get("Action", "").fillna("").astype(str)
        gap_min = log["Time"].diff().dt.total_seconds().div(60)
        log["SessionID"] = (gap_min.isna() | (gap_min > 30)).cumsum()
        sessions = (
            log.groupby("SessionID")
            .agg(Start=("Time", "min"), End=("Time", "max"), Events=("Time", "size"),
                 Actions=("Action", lambda s: ", ".join(s.value_counts().head(4).index.astype(str))))
            .reset_index()
        )
        sessions["Minutes"] = (sessions["End"] - sessions["Start"]).dt.total_seconds().div(60).round(1)
        s1, s2, s3 = st.columns(3)
        s1.metric("Sessions", fmt_int(len(sessions)))
        s2.metric("Median length", f"{fmt_num(sessions['Minutes'].median(), 1)}m")
        s3.metric("Most events/session", fmt_int(sessions["Events"].max()))
        show = sessions.sort_values(["Events", "Minutes"], ascending=False).head(25).copy()
        show["Start"] = local_time_text(show["Start"], tz_name)
        show["End"] = local_time_text(show["End"], tz_name)
        st.dataframe(show[["Start", "End", "Minutes", "Events", "Actions"]], width="stretch", hide_index=True)
    else:
        st.info("No game_log data available for session records.")

with tab_geo:
    st.subheader("Geographic Journey")
    loc = cached_location_points(exclude_zero, exclude_future)
    if len(loc) == 0:
        st.info("No location-bearing sources available.")
    else:
        source_counts = loc["Source"].value_counts()
        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Location points", fmt_int(len(loc)))
        g2.metric("Sources", fmt_int(loc["Source"].nunique()))
        g3.metric("Latitude span", fmt_num(loc["Lat"].max() - loc["Lat"].min(), 3))
        g4.metric("Longitude span", fmt_num(loc["Lon"].max() - loc["Lon"].min(), 3))

        geo_cluster_size = st.slider(
            "Place clustering granularity",
            0.005,
            0.100,
            0.020,
            0.005,
            help="Controls how nearby coordinates are merged into one place. Smaller values split neighborhoods; larger values merge city districts or nearby towns.",
        )
        approx_ns_km = geo_cluster_size * 111
        approx_ew_km = geo_cluster_size * 111 * max(np.cos(np.deg2rad(float(loc["Lat"].median()))), 0.2)
        st.caption(
            f"Current cluster cell is roughly {approx_ns_km:.1f} km north-south by {approx_ew_km:.1f} km east-west near your median latitude. "
            "Use 0.005-0.010 for neighborhood-level review, 0.020 for district-level history, and 0.050+ for city/travel-level summaries."
        )
        places, tagged_loc = cached_geo_clusters(loc, geo_cluster_size, tz_name, exclude_zero, exclude_future)

        left, right = st.columns([2, 3])
        with left:
            st.caption("Source coverage")
            st.dataframe(
                source_counts.rename_axis("Source").reset_index(name="Points"),
                width="stretch",
                hide_index=True,
            )
        with right:
            timed_loc = tagged_loc.dropna(subset=["Year"]).copy()
            if len(timed_loc):
                place_first_year = timed_loc.groupby("Place")["Year"].min().rename("FirstYear")
                yearly_places = timed_loc[["Year", "Place"]].drop_duplicates().merge(place_first_year, on="Place")
                yearly_places["Place type"] = np.where(yearly_places["Year"] == yearly_places["FirstYear"], "New places", "Returning places")
                yearly_counts = yearly_places.groupby(["Year", "Place type"]).size().reset_index(name="Places")
                fig = go.Figure()
                for label, color in [("New places", "#FF9800"), ("Returning places", "#4CAF50")]:
                    sub = yearly_counts[yearly_counts["Place type"] == label]
                    fig.add_trace(go.Bar(
                        x=sub["Year"],
                        y=sub["Places"],
                        name=label,
                        marker_color=color,
                        hovertemplate="%{x}: %{y:,} places<extra></extra>",
                    ))
                fig.update_layout(
                    barmode="stack",
                    height=280,
                    margin=dict(l=10, r=10, t=20, b=35),
                    yaxis_title="Distinct places",
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("No timed location rows for new/returning place analysis.")

        st.subheader("Place History Map")
        st.caption("Colored circles are place clusters, sized by activity volume and colored by dominant source. Black markers summarize year-by-year movement.")
        top_place_count = st.select_slider(
            "Colored place clusters to render",
            options=[25, 50, 100, 200, 500, 1000],
            value=200,
            key="history_geo_place_count",
            help="Controls only the colored place clusters. Annual black markers and trajectory are calculated from all timed places.",
        )
        marker_mode = st.radio(
            "Annual black marker",
            ["Dominant place per year", "Weighted center of active places"],
            horizontal=True,
            key="history_geo_marker_mode",
            help=(
                "Dominant place marks the most active place cluster in each year, so it lands on a real cluster. "
                "Weighted center summarizes all active clusters in a year, but can land between real places."
            ),
        )
        render_places = places.head(top_place_count).copy()
        center_layers, yearly_centers = yearly_marker_layers(tagged_loc.dropna(subset=["Year"]).copy(), places, marker_mode)
        place_layer = pdk.Layer(
            "ScatterplotLayer",
            id="places",
            data=render_places,
            get_position="[Lon, Lat]",
            get_fill_color="color",
            get_radius="radius",
            radius_min_pixels=3,
            radius_max_pixels=22,
            pickable=True,
            auto_highlight=True,
        )
        layers = [place_layer] + center_layers
        deck = pdk.Deck(
            map_style=MAP_STYLE,
            initial_view_state=map_view_state(loc),
            layers=layers,
            tooltip={"text": "{TooltipTitle}\n{TooltipDetail}"},
        )
        st.pydeck_chart(deck, width="stretch", height=520)
        st.caption(
            f"Rendered {len(render_places):,} place clusters from {len(loc):,} cleaned location points. "
            f"Black marker mode: {marker_mode}. Annual markers use all timed places, independent of the colored-place limit."
        )

        st.subheader("Place Timeline Map")
        timed_loc = tagged_loc.dropna(subset=["Year"]).copy()
        if len(timed_loc):
            years = sorted(timed_loc["Year"].astype(int).unique().tolist())
            selected_year = st.select_slider("Timeline year", options=years, value=years[-1], key="history_geo_timeline_year")
            first_year = timed_loc.groupby("Place")["Year"].min().rename("FirstYear")
            year_places = (
                timed_loc[timed_loc["Year"].astype(int) == selected_year]
                .groupby("Place")
                .agg(Points=("Source", "size"), Sources=("Source", lambda s: ", ".join(sorted(set(s)))))
                .reset_index()
                .merge(first_year, on="Place", how="left")
                .merge(places[["Place", "Lat", "Lon", "Dominant source"]], on="Place", how="left")
            )
            year_places["Status"] = np.where(year_places["FirstYear"].astype(int) == selected_year, "New this year", "Returning")
            year_places["color"] = year_places["Status"].map({
                "New this year": [255, 152, 0, 190],
                "Returning": [76, 175, 80, 165],
            })
            year_places["radius"] = np.clip(250 + np.log1p(year_places["Points"]) * 110, 350, 1800)
            year_places["TooltipTitle"] = year_places["Status"] + " | " + year_places["Place"]
            year_places["TooltipDetail"] = year_places["Points"].map(lambda v: f"{int(v):,} points") + " | " + year_places["Sources"]
            year_places["Label"] = year_places["Status"].map({"New this year": "new", "Returning": ""})
            timeline_layers = [
                pdk.Layer(
                    "ScatterplotLayer",
                    id="timeline-places",
                    data=year_places,
                    get_position="[Lon, Lat]",
                    get_fill_color="color",
                    get_radius="radius",
                    radius_min_pixels=3,
                    radius_max_pixels=20,
                    pickable=True,
                    auto_highlight=True,
                ),
                pdk.Layer(
                    "TextLayer",
                    id="timeline-labels",
                    data=year_places[year_places["Label"] != ""],
                    get_position="[Lon, Lat]",
                    get_text="Label",
                    get_color=[150, 75, 0, 230],
                    get_size=13,
                    get_pixel_offset=[0, -12],
                    pickable=False,
                ),
            ]
            st.pydeck_chart(
                pdk.Deck(
                    map_style=MAP_STYLE,
                    initial_view_state=map_view_state(year_places if len(year_places) else loc),
                    layers=timeline_layers,
                    tooltip={"text": "{TooltipTitle}\n{TooltipDetail}"},
                ),
                width="stretch",
                height=430,
            )
            y1, y2, y3 = st.columns(3)
            y1.metric("Active places", fmt_int(len(year_places)))
            y2.metric("New places", fmt_int((year_places["Status"] == "New this year").sum()))
            y3.metric("Returning places", fmt_int((year_places["Status"] == "Returning").sum()))
        else:
            st.info("No timed rows for place timeline mapping.")

        st.subheader("Place Role Map")
        role_source = st.selectbox(
            "Source role to highlight",
            sorted(tagged_loc["Source"].dropna().unique().tolist()),
            key="history_geo_role_source",
        )
        role_counts = (
            tagged_loc[tagged_loc["Source"] == role_source]
            .groupby("Place")
            .size()
            .reset_index(name="RolePoints")
            .merge(places[["Place", "Lat", "Lon", "Points", "Dominant source", "Sources"]], on="Place", how="left")
            .dropna(subset=["Lat", "Lon"])
        )
        if len(role_counts):
            role_counts["Role share"] = role_counts["RolePoints"] / role_counts["Points"]
            role_counts["color"] = np.where(
                role_counts["Dominant source"].eq(role_source).to_numpy()[:, None],
                [33, 150, 243, 190],
                [120, 120, 120, 120],
            ).tolist()
            role_counts["radius"] = np.clip(250 + np.log1p(role_counts["RolePoints"]) * 120, 320, 1700)
            role_counts["TooltipTitle"] = role_source + " | " + role_counts["Place"]
            role_counts["TooltipDetail"] = (
                role_counts["RolePoints"].map(lambda v: f"{int(v):,} source points")
                + " | share " + role_counts["Role share"].map(lambda v: f"{v:.0%}")
                + " | dominant " + role_counts["Dominant source"].fillna("unknown")
            )
            st.pydeck_chart(
                pdk.Deck(
                    map_style=MAP_STYLE,
                    initial_view_state=map_view_state(role_counts),
                    layers=[pdk.Layer(
                        "ScatterplotLayer",
                        id="role-places",
                        data=role_counts,
                        get_position="[Lon, Lat]",
                        get_fill_color="color",
                        get_radius="radius",
                        radius_min_pixels=3,
                        radius_max_pixels=20,
                        pickable=True,
                        auto_highlight=True,
                    )],
                    tooltip={"text": "{TooltipTitle}\n{TooltipDetail}"},
                ),
                width="stretch",
                height=430,
            )
        else:
            st.info(f"No places for {role_source}.")

        st.subheader("Top Places Map")
        top_n = st.select_slider("Top places to label", options=[10, 20, 50, 100], value=20, key="history_geo_top_n")
        top_map = places.head(top_n).copy()
        top_map["Label"] = top_map["Rank"].map(lambda r: f"#{int(r)}")
        st.pydeck_chart(
            pdk.Deck(
                map_style=MAP_STYLE,
                initial_view_state=map_view_state(top_map),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        id="top-places",
                        data=top_map,
                        get_position="[Lon, Lat]",
                        get_fill_color="color",
                        get_radius="radius",
                        radius_min_pixels=4,
                        radius_max_pixels=24,
                        pickable=True,
                        auto_highlight=True,
                    ),
                    pdk.Layer(
                        "TextLayer",
                        id="top-place-labels",
                        data=top_map,
                        get_position="[Lon, Lat]",
                        get_text="Label",
                        get_color=[0, 0, 0, 230],
                        get_size=14,
                        get_pixel_offset=[0, -13],
                        pickable=False,
                    ),
                ],
                tooltip={"text": "{TooltipTitle}\n{TooltipDetail}"},
            ),
            width="stretch",
            height=430,
        )
        show_places = top_map.copy()
        show_places["Dominant share"] = show_places["Dominant share"].map(lambda v: f"{v:.1%}")
        st.dataframe(
            show_places[[
                "Label", "Place", "Points", "ActiveDays", "ActiveYears", "FirstText", "LastText",
                "Dominant source", "Dominant share", "Sources",
            ]],
            width="stretch",
            hide_index=True,
        )

        st.subheader("Farthest Places Map")
        center_lat = float(loc["Lat"].median())
        center_lon = float(loc["Lon"].median())
        far_places = places.copy()
        far_places["Distance from activity center (km)"] = haversine_km(
            center_lat, center_lon, far_places["Lat"].to_numpy(), far_places["Lon"].to_numpy()
        )
        far_places = far_places.sort_values("Distance from activity center (km)", ascending=False).head(20).copy()
        far_places["DistanceText"] = far_places["Distance from activity center (km)"].map(lambda v: f"{v:,.1f} km")
        far_places["Label"] = far_places["DistanceText"]
        far_places["color"] = [[244, 67, 54, 175]] * len(far_places)
        far_places["TooltipTitle"] = far_places["DistanceText"] + " | " + far_places["Place"]
        far_places["TooltipDetail"] = far_places["Points"].map(lambda v: f"{int(v):,} points") + " | " + far_places["FirstText"] + " -> " + far_places["LastText"]
        center_df = pd.DataFrame([{
            "Lat": center_lat,
            "Lon": center_lon,
            "TooltipTitle": "Activity center",
            "TooltipDetail": "Median of cleaned location points",
            "color": [0, 0, 0, 230],
            "radius": 900,
            "Label": "center",
        }])
        st.pydeck_chart(
            pdk.Deck(
                map_style=MAP_STYLE,
                initial_view_state=map_view_state(pd.concat([far_places[["Lat", "Lon"]], center_df[["Lat", "Lon"]]], ignore_index=True)),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        id="far-center",
                        data=center_df,
                        get_position="[Lon, Lat]",
                        get_fill_color="color",
                        get_radius="radius",
                        radius_min_pixels=5,
                        radius_max_pixels=10,
                        pickable=True,
                    ),
                    pdk.Layer(
                        "ScatterplotLayer",
                        id="far-places",
                        data=far_places,
                        get_position="[Lon, Lat]",
                        get_fill_color="color",
                        get_radius="radius",
                        radius_min_pixels=4,
                        radius_max_pixels=18,
                        pickable=True,
                        auto_highlight=True,
                    ),
                    pdk.Layer(
                        "TextLayer",
                        id="far-labels",
                        data=far_places,
                        get_position="[Lon, Lat]",
                        get_text="Label",
                        get_color=[120, 0, 0, 230],
                        get_size=12,
                        get_pixel_offset=[0, -13],
                        pickable=False,
                    ),
                ],
                tooltip={"text": "{TooltipTitle}\n{TooltipDetail}"},
            ),
            width="stretch",
            height=430,
        )
        far_show = far_places.copy()
        far_show["Distance from activity center (km)"] = far_show["Distance from activity center (km)"].round(1)
        st.dataframe(
            far_show[["Distance from activity center (km)", "Place", "Points", "FirstText", "LastText", "Dominant source", "Sources"]],
            width="stretch",
            hide_index=True,
        )

with tab_portal:
    st.subheader("Portal Relationship")
    portal_sets = {}
    for label, key in [
        ("Visited", "portal_guids_visited"),
        ("Captured", "portal_guids_captured"),
        ("Neutralized", "portals_neutralized"),
        ("Scout Controller", "scout_controller_portal_guids"),
        ("Drone hacked", "drone_hack_portal_guids"),
        ("Machina reclaimed", "machina_portals_reclaimed_guids"),
        ("Approved", "all_portals_approved"),
    ]:
        df = with_time(data_frame(key), exclude_future)
        if df is not None and "Unique_ID" in df.columns:
            portal_sets[label] = set(df["Unique_ID"].dropna().astype(str))

    if portal_sets:
        rows = []
        visited = portal_sets.get("Visited", set())
        for label, values in portal_sets.items():
            overlap = len(values & visited) if visited and label != "Visited" else len(values)
            rows.append({
                "Relationship": label,
                "Unique portals": len(values),
                "Also visited": overlap,
                "Share also visited": overlap / len(values) if values else 0,
            })
        rel = pd.DataFrame(rows).sort_values("Unique portals", ascending=False)
        rel["Share also visited"] = rel["Share also visited"].map(lambda v: f"{v:.1%}")
        st.dataframe(rel, width="stretch", hide_index=True)
    else:
        st.info("No portal GUID relationship files available.")

    st.subheader("Wayfarer / POI Contribution")
    poi_keys = [
        ("Portal submissions", "poi_submissions"),
        ("Image submissions", "poi_image_submissions"),
        ("Video submissions", "poi_video_submissions"),
        ("Location edits", "poi_location_update_submissions"),
        ("Text metadata edits", "poi_text_metadata_update_submission"),
        ("Takedown requests", "poi_takedown_request_submissions"),
        ("Approved portals", "all_portals_approved"),
        ("Seer portals", "seer_portals"),
    ]
    poi_rows = []
    poi_timeline = []
    for label, key in poi_keys:
        df = with_time(data_frame(key), exclude_future)
        if df is not None:
            poi_rows.append({"Contribution": label, "Rows": len(df), "Unique IDs": unique_count(df)})
            if "Time" in df.columns:
                work = df[["Time"]].copy()
                work["Month"] = pd.to_datetime(local_date(work["Time"], tz_name)).dt.to_period("M").dt.to_timestamp()
                work["Contribution"] = label
                poi_timeline.append(work)
    if poi_rows:
        st.dataframe(pd.DataFrame(poi_rows), width="stretch", hide_index=True)
        if poi_timeline:
            poi_monthly = (
                pd.concat(poi_timeline, ignore_index=True)
                .groupby(["Month", "Contribution"])
                .size()
                .reset_index(name="Rows")
            )
            fig = go.Figure()
            for label in poi_monthly["Contribution"].unique():
                sub = poi_monthly[poi_monthly["Contribution"] == label]
                fig.add_trace(go.Bar(
                    x=sub["Month"],
                    y=sub["Rows"],
                    name=label,
                    hovertemplate="%{x|%Y-%m}: %{y:,}<extra></extra>",
                ))
            fig.update_layout(
                barmode="stack",
                height=320,
                margin=dict(l=10, r=10, t=20, b=40),
                xaxis_title="",
                yaxis_title="Contribution rows",
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, width="stretch")
    else:
        st.info("No POI contribution sources available.")

with tab_fields:
    st.subheader("Link / Field / MU Quality")
    links = with_time(data_frame("links_created"), exclude_future)
    fields = with_time(data_frame("regions_created"), exclude_future)
    link_len = with_time(data_frame("link_length_kilometers"), exclude_future)
    mu = with_time(data_frame("mind_units_controlled"), exclude_future)
    link_days = with_time(data_frame("link_held_days"), exclude_future)
    mu_days = with_time(data_frame("mind_units_times_days_held"), exclude_future)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Links created", fmt_int(len(links) if links is not None else 0))
    c2.metric("Fields created", fmt_int(len(fields) if fields is not None else 0))
    c3.metric("Total MU", fmt_int(value_sum(mu)))
    c4.metric("Total link km", fmt_num(value_sum(link_len), 1))

    quality_rows = []
    if fields is not None and len(fields):
        quality_rows.append({"Metric": "Average MU per field", "Value": value_sum(mu) / len(fields), "Unit": "MU"})
    if links is not None and len(links):
        quality_rows.append({"Metric": "Average link length", "Value": value_sum(link_len) / len(links), "Unit": "km"})
    if link_days is not None and len(link_days):
        quality_rows.append({"Metric": "Average link held days", "Value": value_sum(link_days) / len(link_days), "Unit": "days"})
    if mu_days is not None and len(mu_days):
        quality_rows.append({"Metric": "Average MU-days entry", "Value": value_sum(mu_days) / len(mu_days), "Unit": "MU-days"})
    if quality_rows:
        qdf = pd.DataFrame(quality_rows)
        qdf["Value"] = qdf["Value"].map(lambda v: fmt_num(v, 2))
        st.dataframe(qdf, width="stretch", hide_index=True)

    dist_cols = st.columns(2)
    for col, df, label, unit in [
        (dist_cols[0], link_len, "Link length distribution", "km"),
        (dist_cols[1], mu, "Field MU distribution", "MU"),
    ]:
        with col:
            if df is not None and "Value" in df.columns:
                vals = pd.to_numeric(df["Value"], errors="coerce").dropna()
                if len(vals):
                    capped = vals.clip(upper=vals.quantile(0.99))
                    fig = go.Figure(data=go.Histogram(x=capped, nbinsx=40, marker_color="#4CAF50"))
                    fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=30), title=label, xaxis_title=unit)
                    st.plotly_chart(fig, width="stretch")
            else:
                st.info(f"No data for {label}.")

    st.subheader("Machina")
    machina_specs = [
        ("Machina portals neutralized", "machina_portals_neutralized", "count"),
        ("Machina resonators destroyed", "machina_resonators_destroyed", "sum"),
        ("Machina links destroyed", "machina_links_destroyed", "sum"),
        ("Machina portals reclaimed", "machina_portals_reclaimed_guids", "nunique"),
    ]
    machina_rows = []
    for label, key, mode in machina_specs:
        df = with_time(data_frame(key), exclude_future)
        if df is not None:
            machina_rows.append({"Metric": label, "Value": aggregate_value(df, mode), "Source": key})
    if machina_rows:
        mdf = pd.DataFrame(machina_rows)
        mdf["Value"] = mdf["Value"].map(fmt_int)
        st.dataframe(mdf, width="stretch", hide_index=True)
    else:
        st.info("No Machina files available.")

with tab_special:
    st.subheader("Event Passport")
    event_specs = [
        ("Alpha", "event_alpha", "sum"),
        ("Bravo", "event_bravo", "sum"),
        ("Delta", "event_delta", "sum"),
        ("Echo", "event_echo", "sum"),
        ("Foxtrot", "event_foxtrot", "sum"),
        ("Golf", "event_golf", "sum"),
        ("India", "event_india", "sum"),
        ("Juliet", "event_juliet", "sum"),
        ("Kilo", "event_kilo", "sum"),
        ("Mike", "event_mike", "sum"),
        ("November", "event_november", "sum"),
        ("Oscar", "event_oscar", "sum"),
        ("+Alpha Op", "plus_alpha_global_op_points", "sum"),
        ("+Beta", "plus_beta_season_points", "sum"),
        ("+Gamma", "plus_gamma_season_points", "sum"),
        ("+Delta", "plus_delta_season_points", "sum"),
        ("+Theta", "plus_theta_season_points", "sum"),
        ("Orion", "orion_season_points", "sum"),
        ("Chronos", "operation_chronos_points", "sum"),
        ("Buried Memories", "buried_memories_event_points", "sum"),
        ("Cryptic Memories", "cryptic_memories_points", "sum"),
        ("Erased Memories", "erased_memories_global_op_points", "sum"),
        ("Shared Memories", "shared_memories_event_points", "sum"),
        ("Second Sunday", "second_sunday_events", "nunique"),
        ("Mission Day", "mission_day_points", "sum"),
        ("NL-1331", "nl1331_meetup_points", "sum"),
    ]
    event_rows = []
    for label, key, mode in event_specs:
        df = with_time(data_frame(key), exclude_future)
        if df is not None and len(df):
            event_rows.append({"Event": label, "Value": aggregate_value(df, mode), "Rows": len(df), "Source": key})
    if event_rows:
        events_df = pd.DataFrame(event_rows).sort_values("Value", ascending=False)
        show = events_df.copy()
        show["Value"] = show["Value"].map(fmt_int)
        st.dataframe(show, width="stretch", hide_index=True)
    else:
        st.info("No event or season sources available.")

    st.subheader("Economy / Inventory Flow")
    econ_rows = []
    for label, key in [
        ("Store transactions", "store_purchases"),
        ("In-app purchases", "InAppPurchases"),
        ("Monthly subscriptions", "subscriptions_monthly"),
        ("Passcodes redeemed", "passcode_redeemed"),
        ("Free SKUs", "free_skus_purchased"),
        ("Power cubes used", "powercube_used"),
        ("Apex mods used", "apex_mods_used"),
        ("Kinetic capsules completed", "kinetic_capsules_completed"),
        ("Inventory recycled", "inventory_item_recycled"),
        ("CARGO applied", "cargo_amounts_applied"),
    ]:
        df = with_time(data_frame(key), exclude_future)
        if df is not None:
            econ_rows.append({"Flow": label, "Rows": len(df), "Value sum": value_sum(df) if "Value" in df.columns else np.nan})
    if econ_rows:
        econ = pd.DataFrame(econ_rows)
        econ["Value sum"] = econ["Value sum"].map(lambda v: "" if pd.isna(v) else fmt_int(v))
        st.dataframe(econ, width="stretch", hide_index=True)
    else:
        st.info("No economy or inventory sources available.")

    st.subheader("Comm / Social Trace")
    log = with_time(data_frame("game_log"), exclude_future)
    comm_rows = []
    if log is not None and "Action" in log.columns:
        sent = log[log["Action"].fillna("").astype(str).eq("send comm message")].copy()
        if len(sent):
            sent["Detail"] = sent.get("Detail", "").fillna("").astype(str)
            mentions = sent["Detail"].str.findall(r"@([A-Za-z0-9_.-]+)").explode().dropna()
            comm_rows.append({"Metric": "Sent comm messages", "Value": len(sent)})
            comm_rows.append({"Metric": "Days with sent comm", "Value": local_date(sent["Time"], tz_name).nunique()})
            comm_rows.append({"Metric": "Mentioned agents in sent comm", "Value": mentions.nunique() if len(mentions) else 0})
    mentions_df = with_time(data_frame("comm_mentions"), exclude_future)
    if mentions_df is not None:
        comm_rows.append({"Metric": "Incoming mention rows", "Value": len(mentions_df)})
    if comm_rows:
        st.dataframe(pd.DataFrame(comm_rows), width="stretch", hide_index=True)
    else:
        st.info("No comm traces available.")

with tab_quality:
    st.subheader("Data Availability")
    inv = source_inventory()
    if len(inv):
        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Parsed sources", fmt_int(len(inv)))
        i2.metric("Rows parsed", fmt_int(inv["Rows"].sum()))
        i3.metric("Time sources", fmt_int(inv["Has time"].sum()))
        i4.metric("Location sources", fmt_int(inv["Has location"].sum()))
        st.dataframe(inv.head(80), width="stretch", hide_index=True)

    st.subheader("Future-dated Rows")
    future_rows = []
    for key, df in sorted(data.items()):
        if key.startswith("_") or df is None or "Time" not in df.columns:
            continue
        t = pd.to_datetime(df["Time"], errors="coerce", utc=True)
        n = int((t >= FUTURE_CUTOFF).sum())
        if n:
            future_rows.append({
                "Source": key,
                "Rows": n,
                "Share": n / len(df),
                "Earliest": t[t >= FUTURE_CUTOFF].min(),
                "Latest": t[t >= FUTURE_CUTOFF].max(),
            })
    if future_rows:
        future = pd.DataFrame(future_rows).sort_values("Rows", ascending=False)
        future["Share"] = future["Share"].map(lambda v: f"{v:.2%}")
        future["Earliest"] = local_time_text(future["Earliest"], tz_name)
        future["Latest"] = local_time_text(future["Latest"], tz_name)
        st.dataframe(future, width="stretch", hide_index=True)
    else:
        st.info("No future-dated rows relative to the runtime cutoff.")

    st.subheader("Near-zero Coordinates")
    zero_rows = []
    for key in ["game_log", "GameplayLocationHistory", "player_journey_actions", "portal_history", "poi_submissions"]:
        df = data_frame(key)
        if df is None or not {"Lat", "Lon"}.issubset(df.columns):
            continue
        lat = pd.to_numeric(df["Lat"], errors="coerce")
        lon = pd.to_numeric(df["Lon"], errors="coerce")
        valid = lat.notna() & lon.notna() & lat.between(*VALID_LAT_RANGE) & lon.between(*VALID_LON_RANGE)
        near_zero = valid & (lat.abs() <= 0.1) & (lon.abs() <= 0.1)
        zero_rows.append({
            "Source": key,
            "Rows": len(df),
            "Valid coordinates": int(valid.sum()),
            "Near-zero coordinates": int(near_zero.sum()),
            "Near-zero share": int(near_zero.sum()) / int(valid.sum()) if int(valid.sum()) else 0,
        })
    if zero_rows:
        zdf = pd.DataFrame(zero_rows)
        zdf["Near-zero share"] = zdf["Near-zero share"].map(lambda v: f"{v:.2%}")
        st.dataframe(zdf, width="stretch", hide_index=True)
