"""Map - WebGL activity map with bounded aggregation and dot rendering."""
import streamlit as st

st.set_page_config(page_title="Map", page_icon="🗺️", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data

import numpy as np
import pandas as pd
import pydeck as pdk

st.title("Portal Activity Map")

MAP_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
SOURCE_COLORS = {
    "Game Log": [76, 175, 80, 135],
    "Location History": [33, 150, 243, 110],
    "Player Journey": [255, 152, 0, 130],
    "Portal History": [156, 39, 176, 120],
}
LAYER_TITLES = {
    "density-cells": "Density cell",
    "grid-cells": "Grid cell",
    "activity-dots": "Activity point",
    "portal-history": "Portal",
}
MAX_DETAIL_CHARS = 180
MAX_CACHE_ENTRIES = 24


def _cache_key(prefix: str, *parts) -> tuple:
    return (st.session_state.get("source_id", ""), prefix, *parts)


def _map_cache() -> dict:
    cache = st.session_state.get("_map_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state["_map_cache"] = cache
    return cache


def _cache_get_or_set(key: tuple, factory):
    cache = _map_cache()
    if key in cache:
        return cache[key]
    value = factory()
    cache[key] = value
    while len(cache) > MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))
    return value


def _as_utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _collect_location_data(source_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    source_names = {
        "game_log": "Game Log",
        "GameplayLocationHistory": "Location History",
        "player_journey_actions": "Player Journey",
    }

    for src_key, src_name in source_names.items():
        df = source_data.get(src_key)
        if df is None or len(df) == 0:
            continue
        required = {"Time", "Lat", "Lon"}
        if not required.issubset(df.columns):
            continue

        keep_cols = ["Time", "Lat", "Lon"]
        for optional_col in ["Action", "Detail", "Type"]:
            if optional_col in df.columns:
                keep_cols.append(optional_col)
        sub = df[keep_cols].copy()
        sub["Lat"] = pd.to_numeric(sub["Lat"], errors="coerce")
        sub["Lon"] = pd.to_numeric(sub["Lon"], errors="coerce")
        sub["Time"] = pd.to_datetime(sub["Time"], errors="coerce", utc=True)
        sub = sub.dropna(subset=["Time", "Lat", "Lon"])
        sub = sub[sub["Lat"].between(-85, 85) & sub["Lon"].between(-180, 180)]
        sub = sub[(sub["Lat"].abs() > 0.1) | (sub["Lon"].abs() > 0.1)]
        if len(sub) == 0:
            continue
        sub["Source"] = src_name
        for optional_col in ["Action", "Detail", "Type"]:
            if optional_col not in sub.columns:
                sub[optional_col] = ""
        sub["Source"] = sub["Source"].astype("category")
        frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=["Time", "Lat", "Lon", "Source", "Action", "Detail", "Type"])

    combined = pd.concat(frames, ignore_index=True)
    combined["Action"] = combined["Action"].fillna("").astype(str)
    combined["Detail"] = combined["Detail"].fillna("").astype(str).str.slice(0, MAX_DETAIL_CHARS)
    combined["Type"] = combined["Type"].fillna("").astype(str)
    return combined


def _view_state(points: pd.DataFrame) -> pdk.ViewState:
    center_lat = float(points["Lat"].median())
    center_lon = float(points["Lon"].median())
    lat_span = float(points["Lat"].max() - points["Lat"].min())
    lon_span = float(points["Lon"].max() - points["Lon"].min())
    span = max(lat_span, lon_span, 0.001)
    zoom = float(np.clip(8 - np.log2(span), 2, 13))
    return pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=0)


def _color_for_count(count: int, max_log: float) -> list[int]:
    intensity = np.log1p(count) / max_log if max_log > 0 else 0
    if intensity < 0.25:
        return [198, 219, 239, 95]
    if intensity < 0.50:
        return [107, 174, 214, 130]
    if intensity < 0.75:
        return [33, 113, 181, 165]
    return [8, 48, 107, 205]


def _aggregate_cells(points: pd.DataFrame, cell_m: int, max_cells: int) -> pd.DataFrame:
    if len(points) == 0:
        return pd.DataFrame()

    center_lat = float(points["Lat"].median())
    lat_step = cell_m / 111_000.0
    lon_step = cell_m / (111_000.0 * max(np.cos(np.deg2rad(center_lat)), 0.2))

    lat_cell = np.floor(points["Lat"].to_numpy() / lat_step) * lat_step
    lon_cell = np.floor(points["Lon"].to_numpy() / lon_step) * lon_step
    work = pd.DataFrame({
        "lat_cell": lat_cell,
        "lon_cell": lon_cell,
        "Source": points["Source"].to_numpy(),
    })
    grouped = (
        work.groupby(["lat_cell", "lon_cell"], observed=True)
        .agg(count=("Source", "size"), sources=("Source", lambda s: ", ".join(sorted(set(s)))))
        .reset_index()
    )
    grouped["Lat"] = grouped["lat_cell"] + lat_step / 2
    grouped["Lon"] = grouped["lon_cell"] + lon_step / 2
    grouped["log_count"] = np.log1p(grouped["count"])

    if len(grouped) > max_cells:
        grouped = grouped.nlargest(max_cells, "count").copy()

    max_log = float(grouped["log_count"].max()) if len(grouped) else 1.0
    grouped["radius"] = np.clip(cell_m * (0.75 + grouped["log_count"] / max_log), cell_m * 0.75, cell_m * 2.0)
    grouped["color"] = grouped["count"].apply(lambda c: _color_for_count(int(c), max_log))
    grouped["cell_m"] = cell_m
    grouped["lat_step"] = lat_step
    grouped["lon_step"] = lon_step
    grouped["lat_min"] = grouped["lat_cell"]
    grouped["lat_max"] = grouped["lat_cell"] + lat_step
    grouped["lon_min"] = grouped["lon_cell"]
    grouped["lon_max"] = grouped["lon_cell"] + lon_step
    grouped["TooltipTitle"] = grouped["count"].map(lambda c: f"{int(c):,} points")
    grouped["TooltipDetail"] = grouped["sources"] + " | " + grouped["cell_m"].map(lambda m: f"{int(m):,}m cell")

    lat0 = grouped["lat_cell"]
    lon0 = grouped["lon_cell"]
    lat1 = lat0 + lat_step
    lon1 = lon0 + lon_step
    return grouped


def _polygonize_cells(cells: pd.DataFrame) -> pd.DataFrame:
    cells = cells.copy()
    lat0 = cells["lat_cell"]
    lon0 = cells["lon_cell"]
    lat1 = cells["lat_max"]
    lon1 = cells["lon_max"]
    cells["polygon"] = [
        [[float(a), float(b)], [float(c), float(b)], [float(c), float(d)], [float(a), float(d)]]
        for a, b, c, d in zip(lon0, lat0, lon1, lat1)
    ]
    return cells


def _sample_points(points: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(points) > max_points:
        points = points.sample(max_points, random_state=42)
    sample = points[["Time", "Lat", "Lon", "Source", "Action", "Detail", "Type"]].copy()
    sample["TimeText"] = sample["Time"].dt.strftime("%Y-%m-%d %H:%M")
    sample["color"] = sample["Source"].map(SOURCE_COLORS).apply(lambda v: v if isinstance(v, list) else [76, 175, 80, 120])
    sample["TooltipTitle"] = sample["Source"]
    sample["TooltipDetail"] = sample["TimeText"]
    sample.loc[sample["Action"].astype(str).str.len() > 0, "TooltipDetail"] += " | " + sample["Action"].astype(str)
    sample["LatText"] = sample["Lat"].map(lambda v: f"{v:.6f}")
    sample["LonText"] = sample["Lon"].map(lambda v: f"{v:.6f}")
    return sample[[
        "Lat", "Lon", "LatText", "LonText", "Source", "Action", "Detail", "Type",
        "TimeText", "TooltipTitle", "TooltipDetail", "color",
    ]]


def _get_locations(source_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    key = _cache_key("locations")
    return _cache_get_or_set(key, lambda: _collect_location_data(source_data))


def _get_filtered(points: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    key = _cache_key("filtered", start.isoformat(), end.isoformat())
    return _cache_get_or_set(key, lambda: points[(points["Time"] >= start) & (points["Time"] <= end)])


def _get_cells(points: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, cell_m: int, max_cells: int) -> pd.DataFrame:
    key = _cache_key("cells", start.isoformat(), end.isoformat(), cell_m, max_cells)
    return _cache_get_or_set(key, lambda: _aggregate_cells(points, cell_m, max_cells))


def _get_sampled_points(points: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, max_points: int) -> pd.DataFrame:
    key = _cache_key("dots", start.isoformat(), end.isoformat(), max_points)
    return _cache_get_or_set(key, lambda: _sample_points(points, max_points))


def _get_portal_overlay(portal_history: pd.DataFrame | None, max_portals: int = 2500) -> pd.DataFrame:
    if portal_history is None:
        return pd.DataFrame()
    key = _cache_key("portal-overlay", max_portals)
    return _cache_get_or_set(key, lambda: _prepare_portals(portal_history, max_portals=max_portals))


def _get_portal_frame(portal_history: pd.DataFrame | None) -> pd.DataFrame:
    key = _cache_key("portal-frame")
    return _cache_get_or_set(key, lambda: _portal_frame(portal_history))


def _clean_value(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _prepare_portals(portal_history: pd.DataFrame, max_portals: int = 2500) -> pd.DataFrame:
    portals = portal_history.copy()
    portals["Lat"] = pd.to_numeric(portals["Lat"], errors="coerce")
    portals["Lon"] = pd.to_numeric(portals["Lon"], errors="coerce")
    portals = portals.dropna(subset=["Lat", "Lon"])
    portals = portals[portals["Lat"].between(-85, 85) & portals["Lon"].between(-180, 180)]
    if len(portals) > max_portals:
        portals = portals.sample(max_portals, random_state=1)

    portals = portals.copy()
    portals["LatText"] = portals["Lat"].map(lambda v: f"{v:.6f}")
    portals["LonText"] = portals["Lon"].map(lambda v: f"{v:.6f}")
    portals["Source"] = "Portal History"
    portals["TooltipTitle"] = portals.apply(_portal_title, axis=1)
    portals["TooltipDetail"] = portals.apply(_portal_detail, axis=1)
    portals["color"] = [SOURCE_COLORS["Portal History"]] * len(portals)

    # Keep tooltip and click payload small while preserving useful portal metadata.
    preferred = [
        "Source", "Type", "Title", "Name", "Portal", "PortalName", "Guid", "GUID",
        "Address", "Lat", "Lon", "LatText", "LonText", "TooltipTitle", "TooltipDetail", "color",
    ]
    available = [c for c in preferred if c in portals.columns]
    extras = [c for c in portals.columns if c not in available]
    serializable_cols = available + extras[:8]
    return portals[serializable_cols]


def _portal_title(row: pd.Series) -> str:
    for col in ["Title", "Name", "Portal", "PortalName", "Type"]:
        value = _case_value(row, col)
        if value:
            return value
    return "Portal"


def _portal_detail(row: pd.Series) -> str:
    parts = []
    for col in ["Address", "Guid", "GUID"]:
        value = _case_value(row, col)
        if value:
            parts.append(value)
    parts.append(f"{float(row['Lat']):.6f}, {float(row['Lon']):.6f}")
    return " | ".join(parts)


def _case_value(row: pd.Series, name: str) -> str:
    target = name.lower()
    for col in row.index:
        if str(col).lower() == target:
            return _clean_value(row.get(col))
    return ""


def _selected_object(chart_state) -> tuple[str, dict] | tuple[None, None]:
    selection = getattr(chart_state, "selection", {}) or {}
    objects = selection.get("objects", {}) if isinstance(selection, dict) else {}
    for layer_id, selected in objects.items():
        if selected:
            return layer_id, selected[0]
    return None, None


def _portal_frame(portal_history: pd.DataFrame | None) -> pd.DataFrame:
    if portal_history is None or len(portal_history) == 0 or not {"Lat", "Lon"}.issubset(portal_history.columns):
        return pd.DataFrame()
    portals = portal_history.copy()
    portals["Lat"] = pd.to_numeric(portals["Lat"], errors="coerce")
    portals["Lon"] = pd.to_numeric(portals["Lon"], errors="coerce")
    portals = portals.dropna(subset=["Lat", "Lon"])
    portals = portals[portals["Lat"].between(-85, 85) & portals["Lon"].between(-180, 180)]
    return portals


def _cell_activity(points: pd.DataFrame, obj: dict) -> pd.DataFrame:
    required = ["lat_min", "lat_max", "lon_min", "lon_max"]
    if not all(k in obj for k in required):
        return pd.DataFrame()
    lat_min, lat_max = float(obj["lat_min"]), float(obj["lat_max"])
    lon_min, lon_max = float(obj["lon_min"]), float(obj["lon_max"])
    return points[
        points["Lat"].between(lat_min, lat_max, inclusive="left")
        & points["Lon"].between(lon_min, lon_max, inclusive="left")
    ].copy()


def _cell_portals(portals: pd.DataFrame, obj: dict) -> pd.DataFrame:
    required = ["lat_min", "lat_max", "lon_min", "lon_max"]
    if len(portals) == 0 or not all(k in obj for k in required):
        return pd.DataFrame()
    lat_min, lat_max = float(obj["lat_min"]), float(obj["lat_max"])
    lon_min, lon_max = float(obj["lon_min"]), float(obj["lon_max"])
    return portals[
        portals["Lat"].between(lat_min, lat_max, inclusive="left")
        & portals["Lon"].between(lon_min, lon_max, inclusive="left")
    ].copy()


def _distance_m(lat1: float, lon1: float, lat2: pd.Series, lon2: pd.Series) -> pd.Series:
    lat_scale = 111_000.0
    lon_scale = 111_000.0 * max(np.cos(np.deg2rad(lat1)), 0.2)
    return np.sqrt(((lat2 - lat1) * lat_scale) ** 2 + ((lon2 - lon1) * lon_scale) ** 2)


def _nearby_portals(portals: pd.DataFrame, lat: float, lon: float, limit: int = 5) -> pd.DataFrame:
    if len(portals) == 0:
        return pd.DataFrame()
    portals = portals.copy()
    portals["DistanceM"] = _distance_m(lat, lon, portals["Lat"], portals["Lon"])
    return portals.nsmallest(limit, "DistanceM")


def _display_frame(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
    show_cols = [c for c in columns if c in df.columns]
    if not show_cols:
        show_cols = df.columns[:8].tolist()
    st.dataframe(df[show_cols].head(limit), width="stretch", hide_index=True)


def _show_cell_drilldown(points: pd.DataFrame, portals: pd.DataFrame, obj: dict) -> None:
    cell_points = _cell_activity(points, obj)
    cell_portals = _cell_portals(portals, obj)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Activity in cell", f"{len(cell_points):,}")
    c2.metric("Portals in cell", f"{len(cell_portals):,}" if len(cell_portals) else "0")
    if len(cell_points):
        c3.metric("First activity", cell_points["Time"].min().strftime("%Y-%m-%d"))
        c4.metric("Last activity", cell_points["Time"].max().strftime("%Y-%m-%d"))
    else:
        c3.metric("First activity", "-")
        c4.metric("Last activity", "-")

    if len(cell_points):
        left, right = st.columns(2)
        with left:
            st.caption("Source breakdown")
            st.dataframe(
                cell_points["Source"].value_counts().rename_axis("Source").reset_index(name="Count"),
                width="stretch",
                hide_index=True,
            )
        with right:
            action_counts = cell_points["Action"].replace("", pd.NA).dropna().value_counts()
            if len(action_counts):
                st.caption("Action breakdown")
                st.dataframe(action_counts.rename_axis("Action").reset_index(name="Count"), width="stretch", hide_index=True)
            else:
                st.caption("Action breakdown")
                st.write("No action labels in this cell.")

        st.caption("Recent activity in this cell")
        recent = cell_points.sort_values("Time", ascending=False).copy()
        recent["TimeText"] = recent["Time"].dt.strftime("%Y-%m-%d %H:%M")
        _display_frame(recent, ["TimeText", "Source", "Action", "Type", "Detail", "Lat", "Lon"], limit=100)

    if len(cell_portals):
        st.caption("Portals in this cell")
        _display_frame(
            cell_portals,
            ["Title", "Name", "Portal", "PortalName", "Type", "Guid", "GUID", "Address", "Lat", "Lon"],
            limit=100,
        )


def _show_point_context(portals: pd.DataFrame, obj: dict) -> None:
    if "Lat" not in obj or "Lon" not in obj:
        return
    nearby = _nearby_portals(portals, float(obj["Lat"]), float(obj["Lon"]))
    if len(nearby) == 0:
        return
    nearby = nearby.copy()
    nearby["DistanceM"] = nearby["DistanceM"].round(1)
    st.caption("Nearest portals")
    _display_frame(
        nearby,
        ["DistanceM", "Title", "Name", "Portal", "PortalName", "Type", "Guid", "GUID", "Address", "Lat", "Lon"],
        limit=5,
    )


def _show_selected_details(
    layer_id: str | None,
    obj: dict | None,
    points: pd.DataFrame,
    portals: pd.DataFrame,
) -> None:
    if not layer_id or not obj:
        st.info("Click a rendered point, cell, or portal overlay marker to inspect it.")
        return

    st.subheader(LAYER_TITLES.get(layer_id, "Selected object"))
    ignore = {"color", "polygon", "log_count", "radius", "lat_step", "lon_step"}
    display_order = [
        "Source", "TimeText", "Action", "Detail", "Type", "count", "sources", "cell_m",
        "Title", "Name", "Portal", "PortalName", "Guid", "GUID", "Address",
        "LatText", "LonText", "lat_min", "lat_max", "lon_min", "lon_max",
    ]
    rows = []
    seen = set()
    for key in display_order + sorted(obj.keys()):
        if key in seen or key in ignore or key not in obj:
            continue
        seen.add(key)
        value = _clean_value(obj.get(key))
        if value:
            rows.append({"Field": key, "Value": value})

    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.write(obj)

    if layer_id in {"density-cells", "grid-cells"}:
        _show_cell_drilldown(points, portals, obj)
    elif layer_id == "activity-dots":
        _show_point_context(portals, obj)


locs = _get_locations(data)
if len(locs) == 0:
    st.warning("No location data available.")
    st.stop()

t_min = locs["Time"].min().to_pydatetime()
t_max = locs["Time"].max().to_pydatetime()

with st.sidebar:
    st.subheader("Map Controls")
    mode = st.radio(
        "Visualization",
        ["Density Heat", "Grid Cells", "Dot Scatter"],
        horizontal=False,
        key="map_mode",
    )
    t1, t2 = st.slider("Time range", value=(t_min, t_max), format="YYYY-MM-DD", key="map_ts")

    if mode in ("Density Heat", "Grid Cells"):
        cell_m = st.select_slider(
            "Cell size",
            options=[100, 200, 500, 1000, 2000, 5000, 10000],
            value=500 if mode == "Density Heat" else 1000,
            format_func=lambda m: f"{m}m" if m < 1000 else f"{m // 1000}km",
            key="map_cell_size",
        )
        max_cells = st.select_slider(
            "Max cells",
            options=[1000, 2500, 5000, 10000, 20000],
            value=5000,
            key="map_max_cells",
        )
    else:
        max_dots = st.select_slider(
            "Max dots",
            options=[5000, 10000, 20000, 50000, 100000],
            value=20000,
            key="map_max_dots",
        )
        dot_radius = st.select_slider(
            "Dot radius",
            options=[20, 40, 75, 120, 200],
            value=40,
            format_func=lambda m: f"{m}m",
            key="map_dot_radius",
        )

    show_portals = st.checkbox("Portal history overlay", value=False, key="map_portals")

start = _as_utc(t1)
end = _as_utc(t2)
filtered = _get_filtered(locs, start, end)

if len(filtered) == 0:
    st.info("No points in range.")
    st.stop()

layers = []
tooltip = {"text": "{TooltipTitle}\n{TooltipDetail}"}

if mode == "Dot Scatter":
    render_points = _get_sampled_points(filtered, start, end, max_dots)
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            id="activity-dots",
            data=render_points,
            get_position="[Lon, Lat]",
            get_fill_color="color",
            get_radius=dot_radius,
            radius_min_pixels=1,
            radius_max_pixels=8,
            pickable=True,
            auto_highlight=True,
        )
    )
    rendered = len(render_points)
else:
    cells = _get_cells(filtered, start, end, cell_m, max_cells)
    if len(cells) == 0:
        st.info("No cells in range.")
        st.stop()

    if mode == "Grid Cells":
        cells = _polygonize_cells(cells)
        layers.append(
            pdk.Layer(
                "PolygonLayer",
                id="grid-cells",
                data=cells,
                get_polygon="polygon",
                get_fill_color="color",
                get_line_color=[30, 30, 30, 55],
                line_width_min_pixels=0.25,
                pickable=True,
                auto_highlight=True,
            )
        )
    else:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                id="density-cells",
                data=cells,
                get_position="[Lon, Lat]",
                get_fill_color="color",
                get_radius="radius",
                radius_min_pixels=2,
                radius_max_pixels=45,
                pickable=True,
                auto_highlight=True,
            )
        )
    rendered = len(cells)

if show_portals:
    ph = data.get("portal_history")
    if ph is not None and len(ph) > 0 and {"Lat", "Lon"}.issubset(ph.columns):
        portals = _get_portal_overlay(ph)
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                id="portal-history",
                data=portals,
                get_position="[Lon, Lat]",
                get_fill_color="color",
                get_radius=25,
                radius_min_pixels=1,
                radius_max_pixels=4,
                pickable=True,
                auto_highlight=True,
            )
        )

deck = pdk.Deck(
    map_style=MAP_STYLE,
    initial_view_state=_view_state(filtered),
    layers=layers,
    tooltip=tooltip,
)

c1, c2, c3 = st.columns(3)
c1.metric("Total points", f"{len(locs):,}")
c2.metric("In range", f"{len(filtered):,}")
c3.metric("Rendered", f"{rendered:,}")

chart_state = st.pydeck_chart(
    deck,
    width="stretch",
    height=640,
    on_select="rerun",
    selection_mode="single-object",
    key="map_chart",
)

layer_id, selected = _selected_object(chart_state)
portal_frame = _get_portal_frame(data.get("portal_history"))
_show_selected_details(layer_id, selected, filtered, portal_frame)

if mode != "Dot Scatter":
    st.caption(
        f"{mode} renders aggregated {cell_m:,}m cells and caps the draw set at {max_cells:,} cells. "
        "Use Dot Scatter for individual sampled points."
    )
else:
    st.caption(
        f"Dot Scatter samples to at most {max_dots:,} points and renders with WebGL. "
        "Increase the cap only when the browser remains responsive."
    )
