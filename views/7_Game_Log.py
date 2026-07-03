"""Game Log - action, session, detail, and rare item insights."""
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import decode_export_text_field
from time_utils import local_month_start, local_time_text, timezone_selector, to_local_time

st.set_page_config(page_title="Game Log", page_icon="🧾", layout="wide")

if not st.session_state.get("source_loaded"):
    st.switch_page("app.py")

data = st.session_state.data
log = data.get("game_log")

st.title("Game Log Insights")
tz_name = timezone_selector()
st.caption(f"Game log dates, hours, and session timestamps use display timezone: **{tz_name}**")

if log is None or len(log) == 0:
    st.warning("No game_log data available.")
    st.stop()

RARE_ITEM_PATTERNS = {
    "Aegis Shield": r"\baegis\b",
    "Very Rare Shield": r"\bvery rare shield\b|\bvr shield\b",
    "Very Rare Multi-hack": r"\bvery rare multi[- ]?hack\b|\bvr multi[- ]?hack\b",
    "Very Rare Heat Sink": r"\bvery rare heat ?sink\b|\bvr heat ?sink\b",
    "Very Rare Link Amp": r"\bvery rare link amp\b|\bvr link amp\b",
    "SoftBank Ultra Link": r"\bsoftbank\b|\bsbula\b|\bultra link\b",
    "ITO EN Transmuter +": r"\bito en transmuter \+|\bito\+|\bito en \+",
    "ITO EN Transmuter -": r"\bito en transmuter -|\bito-|\bito en -",
    "Quantum Capsule": r"\bquantum capsule\b|\bqcap\b",
    "Kinetic Capsule": r"\bkinetic capsule\b",
    "Apex": r"\bapex\b",
    "HyperCube": r"\bhypercube\b|\bhyper cube\b",
    "Jarvis Virus": r"\bjarvis\b",
    "ADA Refactor": r"\bada\b|\brefactor\b",
    "Fracker": r"\bfracker\b",
    "Beacon": r"\bbeacon\b",
    "Firework": r"\bfirework\b",
    "Battle Beacon": r"\bbattle beacon\b",
    "Portal Scan": r"\bportal scan\b",
}

ITEM_EVENT_PATTERNS = {
    "Hacked": r"\bhack|disbursed|created .*portal hack|created boosted power cube|created interest capsule",
    "Used": r"\buse(d)?\b|\bactivate|\bfire|\bflip|\bconsume|player consumed",
    "Deployed": r"\bdeploy|\binstall|added powerup",
    "Acquired": r"\bacquir|\bobtain|\breceiv|\breward|\bpick(ed)? up|\bcreated|\bcomplete|generated",
    "Recycled": r"\brecycl",
    "Dropped": r"\bdrop(ped)?\b",
}
FUTURE_CUTOFF = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
PREPARE_VERSION = 4


def prepare_game_log(df: pd.DataFrame, source_id: str, tz_name: str) -> pd.DataFrame:
    out = df.copy()
    raw_rows = len(out)
    out["Time"] = pd.to_datetime(out["Time"], errors="coerce", utc=True)
    invalid_time_rows = int(out["Time"].isna().sum())
    out["Lat"] = pd.to_numeric(out["Lat"], errors="coerce")
    out["Lon"] = pd.to_numeric(out["Lon"], errors="coerce")
    out["Action"] = out["Action"].fillna("").astype(str)
    out["Detail"] = out["Detail"].fillna("").astype(str).map(decode_export_text_field)
    out = out.dropna(subset=["Time"])
    out.attrs["raw_rows"] = raw_rows
    out.attrs["invalid_time_rows"] = invalid_time_rows
    out.attrs["future_rows"] = int((out["Time"] >= FUTURE_CUTOFF).sum())
    local_time = to_local_time(out["Time"], tz_name)
    out["LocalTime"] = local_time
    out["Date"] = local_time.dt.date
    out["Month"] = local_month_start(out["Time"], tz_name)
    out["Hour"] = local_time.dt.hour
    out["DOW"] = local_time.dt.day_name()
    out["DetailShort"] = out["Detail"].str.slice(0, 240)
    out = out.sort_values("Time").reset_index(drop=True)

    gap_min = out["Time"].diff().dt.total_seconds().div(60)
    out["SessionID"] = (gap_min.isna() | (gap_min > 30)).cumsum()
    out["ItemName"] = out.apply(match_item, axis=1)
    out["ItemEvent"] = out.apply(classify_item_event, axis=1)
    out["ResourceType"] = out["Detail"].apply(extract_resource_type)
    out["RewardStatus"] = out["Detail"].apply(extract_reward_status)
    out["RpcEndpoint"] = out["Detail"].apply(extract_rpc_endpoint)
    out["PowerupDesignation"] = out["Detail"].apply(extract_powerup_designation)
    return out


def get_prepared_game_log(df: pd.DataFrame, tz_name: str) -> pd.DataFrame:
    source_id = st.session_state.get("source_id", "")
    key = (source_id, "game-log-prepared", PREPARE_VERSION, tz_name)
    cache = st.session_state.setdefault("_game_log_cache", {})
    if key not in cache:
        cache.clear()
        cache[key] = prepare_game_log(df, source_id, tz_name)
    return cache[key]


def match_item(row: pd.Series) -> str:
    text = f"{row.get('Action', '')} {row.get('Detail', '')}".lower()
    for name, pattern in RARE_ITEM_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return name
    return ""


def classify_item_event(row: pd.Series) -> str:
    if not row.get("ItemName"):
        return ""
    text = f"{row.get('Action', '')} {row.get('Detail', '')}".lower()
    for label, pattern in ITEM_EVENT_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return "Mentioned"


def extract_resource_type(detail: str) -> str:
    text = str(detail)
    patterns = [
        r"Resource of type:\s*([A-Z0-9_]+)",
        r"Dropped\s+([A-Za-z0-9 -]*PortalLinkKey)",
        r"Dropped\s+(Portal Mod)",
        r"Dropped\s+(Media Item)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_reward_status(detail: str) -> str:
    text = str(detail).strip()
    if not text:
        return "blank"
    known = {
        "Redeemed Portal Mod",
        "generated",
        "success",
        "player",
        "reached player redemption limit",
        "reached global redemption limit",
        "invalid passcode",
    }
    if text in known:
        return text
    return "other"


def extract_rpc_endpoint(detail: str) -> str:
    text = str(detail).strip()
    if text.startswith("uri: "):
        return text[5:]
    return ""


def extract_powerup_designation(detail: str) -> str:
    text = str(detail)
    patterns = [
        r"designation\s+([A-Z0-9_-]+)",
        r"Designation:\s*([A-Z0-9_-]+)",
        r"active designation\s+([A-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".")
    return ""


def metric_value(value: int | float) -> str:
    return f"{value:,.0f}"


def simple_bar(labels, values, title: str, color: str = "#4CAF50") -> go.Figure:
    fig = go.Figure(data=go.Bar(x=labels, y=values, marker_color=color))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=80), title=title, xaxis=dict(tickangle=-35))
    return fig


df = get_prepared_game_log(log, tz_name)

action_options = sorted([a for a in df["Action"].dropna().unique().tolist() if a])
with st.sidebar:
    st.subheader("Game Log Filters")
    selected_actions = st.multiselect("Action", action_options, default=[], key="glog_actions")
    query = st.text_input("Detail contains", key="glog_query")
    item_only = st.checkbox("Rare item events only", value=False, key="glog_item_only")

filtered = df
if selected_actions:
    filtered = filtered[filtered["Action"].isin(selected_actions)]
if query:
    filtered = filtered[filtered["Detail"].str.contains(query, case=False, na=False, regex=False)]
if item_only:
    filtered = filtered[filtered["ItemName"] != ""]

if len(filtered) == 0:
    st.info("No log entries match the current filters.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Events", metric_value(len(filtered)))
c2.metric("Actions", metric_value(filtered["Action"].nunique()))
c3.metric("Sessions", metric_value(filtered["SessionID"].nunique()))
c4.metric("Rare item events", metric_value((filtered["ItemName"] != "").sum()))

tab_actions, tab_comm, tab_items, tab_rewards, tab_system, tab_sessions, tab_quality, tab_explorer = st.tabs([
    "Actions",
    "Comm",
    "Rare Items",
    "Rewards & Drops",
    "RPC & Powerups",
    "Sessions",
    "Quality",
    "Explorer",
])

with tab_actions:
    left, right = st.columns([2, 3])
    with left:
        st.subheader("Top Actions")
        action_counts = filtered["Action"].replace("", pd.NA).dropna().value_counts().head(20)
        if len(action_counts):
            st.plotly_chart(simple_bar(action_counts.index.tolist(), action_counts.values.tolist(), "Top actions"), width="stretch")
        else:
            st.info("No action labels.")
    with right:
        st.subheader("Daily Volume")
        daily = filtered.groupby("Date").size().reset_index(name="Events")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(daily["Date"]),
            y=daily["Events"],
            mode="lines",
            fill="tozeroy",
            line=dict(color="#2196F3", width=1.5),
            hovertemplate="%{x|%Y-%m-%d}: %{y:,} events<extra></extra>",
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=30), xaxis_title="", yaxis_title="Events")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Hour x Day")
    heat = filtered.groupby(["DOW", "Hour"]).size().unstack(fill_value=0)
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heat = heat.reindex(index=day_order, columns=range(24), fill_value=0)
    fig_heat = go.Figure(data=go.Heatmap(
        z=heat.values,
        x=[f"{h}:00" for h in range(24)],
        y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        colorscale="Viridis",
        hovertemplate="%{y} %{x}: %{z:,} events<extra></extra>",
    ))
    fig_heat.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=30))
    st.plotly_chart(fig_heat, width="stretch")

with tab_comm:
    comm = filtered[filtered["Action"].eq("send comm message")].copy()
    if len(comm) == 0:
        st.info("No sent comm messages match the current filters.")
    else:
        comm["MessageLength"] = comm["Detail"].str.len()
        mentions = comm["Detail"].str.findall(r"@([A-Za-z0-9_.-]+)").explode().dropna()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Messages", metric_value(len(comm)))
        m2.metric("Days active", metric_value(comm["Date"].nunique()))
        m3.metric("Avg length", metric_value(comm["MessageLength"].mean()))
        m4.metric("Mentioned agents", metric_value(mentions.nunique() if len(mentions) else 0))

        left, right = st.columns([3, 2])
        with left:
            daily_comm = comm.groupby("Date").size().reset_index(name="Messages")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(daily_comm["Date"]),
                y=daily_comm["Messages"],
                mode="lines",
                fill="tozeroy",
                line=dict(color="#00A676", width=1.5),
                hovertemplate="%{x|%Y-%m-%d}: %{y:,} messages<extra></extra>",
            ))
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=30), xaxis_title="", yaxis_title="Messages")
            st.plotly_chart(fig, width="stretch")
        with right:
            if len(mentions):
                mention_counts = mentions.value_counts().head(20)
                st.plotly_chart(
                    simple_bar(mention_counts.index.tolist(), mention_counts.values.tolist(), "Top @mentions", "#607D8B"),
                    width="stretch",
                )
            else:
                st.info("No @mentions in matching comm messages.")

        left, right = st.columns(2)
        with left:
            bins = [0, 20, 50, 100, 200, 500, 1000, float("inf")]
            labels = ["0-20", "21-50", "51-100", "101-200", "201-500", "501-1000", "1000+"]
            length_bucket = pd.cut(comm["MessageLength"], bins=bins, labels=labels, include_lowest=True)
            length_counts = length_bucket.value_counts().reindex(labels, fill_value=0)
            st.plotly_chart(
                simple_bar(length_counts.index.tolist(), length_counts.values.tolist(), "Message length", "#795548"),
                width="stretch",
            )
        with right:
            hour_counts = comm.groupby("Hour").size().reindex(range(24), fill_value=0)
            st.plotly_chart(
                simple_bar([f"{h}:00" for h in range(24)], hour_counts.values.tolist(), "Messages by hour", "#3F51B5"),
                width="stretch",
            )

        st.subheader("Recent Comm Messages")
        recent_comm = comm.sort_values("Time", ascending=False).copy()
        recent_comm["TimeText"] = local_time_text(recent_comm["Time"], tz_name)
        st.dataframe(
            recent_comm[["TimeText", "DetailShort", "MessageLength", "Lat", "Lon"]].head(500),
            width="stretch",
            hide_index=True,
        )

with tab_items:
    item_events = filtered[filtered["ItemName"] != ""].copy()
    if len(item_events) == 0:
        st.info("No rare item patterns matched the current filters.")
    else:
        left, right = st.columns(2)
        with left:
            item_counts = item_events["ItemName"].value_counts().head(20)
            st.plotly_chart(simple_bar(item_counts.index.tolist(), item_counts.values.tolist(), "Rare item mentions", "#9C27B0"), width="stretch")
        with right:
            event_counts = item_events.groupby(["ItemName", "ItemEvent"]).size().reset_index(name="Count")
            fig = go.Figure()
            for event_type in event_counts["ItemEvent"].unique():
                sub = event_counts[event_counts["ItemEvent"] == event_type]
                fig.add_trace(go.Bar(x=sub["ItemName"], y=sub["Count"], name=event_type))
            fig.update_layout(
                barmode="stack", height=320, margin=dict(l=10, r=10, t=30, b=80),
                title="Item event types", xaxis=dict(tickangle=-35),
            )
            st.plotly_chart(fig, width="stretch")

        st.subheader("Rare Item Log")
        show = item_events.sort_values("Time", ascending=False).copy()
        show["TimeText"] = local_time_text(show["Time"], tz_name)
        st.dataframe(
            show[["TimeText", "ItemName", "ItemEvent", "Action", "DetailShort", "Lat", "Lon"]].head(500),
            width="stretch",
            hide_index=True,
        )

        st.subheader("Rare Timeline")
        timeline_events = ["Hacked", "Used", "Deployed", "Acquired", "Recycled", "Dropped", "Mentioned"]
        timeline = (
            item_events[item_events["ItemEvent"].isin(timeline_events)]
            .groupby(["Month", "ItemName", "ItemEvent"])
            .size()
            .reset_index(name="Count")
        )
        selected_items = st.multiselect(
            "Timeline items",
            sorted(item_events["ItemName"].unique().tolist()),
            default=sorted(item_events["ItemName"].value_counts().head(5).index.tolist()),
            key="glog_timeline_items",
        )
        if selected_items:
            timeline = timeline[timeline["ItemName"].isin(selected_items)]
        if len(timeline):
            fig = go.Figure()
            for (item_name, event_type), sub in timeline.groupby(["ItemName", "ItemEvent"]):
                dash = "solid" if event_type in {"Used", "Hacked"} else "dot"
                fig.add_trace(go.Scatter(
                    x=sub["Month"],
                    y=sub["Count"],
                    mode="lines+markers",
                    name=f"{item_name} · {event_type}",
                    line=dict(width=2 if event_type in {"Used", "Hacked"} else 1, dash=dash),
                    hovertemplate="%{x|%Y-%m}: %{y:,}<extra></extra>",
                ))
            fig.update_layout(
                height=420,
                margin=dict(l=10, r=10, t=30, b=40),
                title="Rare item timeline by event type",
                legend=dict(orientation="h", y=-0.2),
                xaxis_title="",
                yaxis_title="Events",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No timeline data for the selected items.")

with tab_rewards:
    st.subheader("Reward Flow")
    reward_actions = [
        "attempt to claim item reward",
        "claimed item reward",
        "claimed AP reward",
        "claimed XM reward",
    ]
    rewards = filtered[filtered["Action"].isin(reward_actions)].copy()
    if len(rewards):
        left, right = st.columns(2)
        with left:
            reward_counts = rewards["Action"].value_counts()
            st.plotly_chart(
                simple_bar(reward_counts.index.tolist(), reward_counts.values.tolist(), "Reward actions", "#607D8B"),
                width="stretch",
            )
        with right:
            status_counts = rewards["RewardStatus"].value_counts().head(20)
            st.plotly_chart(
                simple_bar(status_counts.index.tolist(), status_counts.values.tolist(), "Reward statuses", "#795548"),
                width="stretch",
            )
        recent_rewards = rewards.sort_values("Time", ascending=False).copy()
        recent_rewards["TimeText"] = local_time_text(recent_rewards["Time"], tz_name)
        st.dataframe(
            recent_rewards[["TimeText", "Action", "RewardStatus", "DetailShort", "Lat", "Lon"]].head(300),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No reward actions match the current filters.")

    st.subheader("Dropped Item Breakdown")
    dropped = filtered[filtered["Action"].eq("dropped item")].copy()
    if len(dropped):
        dropped["DropType"] = dropped["ResourceType"].replace("", "other")
        drop_counts = dropped["DropType"].value_counts().head(30)
        st.plotly_chart(
            simple_bar(drop_counts.index.tolist(), drop_counts.values.tolist(), "Dropped item types", "#FF9800"),
            width="stretch",
        )
        media = dropped[dropped["DropType"].eq("Media Item")].sort_values("Time", ascending=False).copy()
        if len(media):
            media["TimeText"] = local_time_text(media["Time"], tz_name)
            st.caption("Recent media drops")
            st.dataframe(media[["TimeText", "DetailShort", "Lat", "Lon"]].head(100), width="stretch", hide_index=True)
    else:
        st.info("No dropped-item rows match the current filters.")

with tab_system:
    left, right = st.columns(2)
    with left:
        st.subheader("Client RPC")
        rpc = filtered[filtered["RpcEndpoint"] != ""].copy()
        if len(rpc):
            rpc_counts = rpc["RpcEndpoint"].value_counts().head(30)
            st.plotly_chart(
                simple_bar(rpc_counts.index.tolist(), rpc_counts.values.tolist(), "RPC endpoints", "#3F51B5"),
                width="stretch",
            )
        else:
            st.info("No client RPC rows match the current filters.")
    with right:
        st.subheader("Powerup Designations")
        powerups = filtered[filtered["PowerupDesignation"] != ""].copy()
        if len(powerups):
            power_counts = powerups["PowerupDesignation"].value_counts().head(30)
            st.plotly_chart(
                simple_bar(power_counts.index.tolist(), power_counts.values.tolist(), "Powerup designations", "#009688"),
                width="stretch",
            )
        else:
            st.info("No powerup designation rows match the current filters.")

    st.subheader("System-ish Rare Events")
    rare_actions = filtered["Action"].replace("", pd.NA).dropna().value_counts()
    rare_actions = rare_actions[rare_actions <= 10].rename_axis("Action").reset_index(name="Count")
    if len(rare_actions):
        st.dataframe(rare_actions, width="stretch", hide_index=True)
    else:
        st.info("No rare actions under the current filters.")

with tab_sessions:
    sessions = (
        filtered.groupby("SessionID")
        .agg(
            Start=("Time", "min"),
            End=("Time", "max"),
            Events=("Time", "size"),
            Actions=("Action", lambda s: ", ".join(s.value_counts().head(4).index.astype(str))),
            RareItems=("ItemName", lambda s: int((s != "").sum())),
            Lat=("Lat", "median"),
            Lon=("Lon", "median"),
        )
        .reset_index()
    )
    sessions["Minutes"] = (sessions["End"] - sessions["Start"]).dt.total_seconds().div(60).round(1)
    sessions["StartText"] = local_time_text(sessions["Start"], tz_name)
    sessions["EndText"] = local_time_text(sessions["End"], tz_name)

    c1, c2, c3 = st.columns(3)
    c1.metric("Avg session", f"{sessions['Minutes'].mean():.1f}m")
    c2.metric("Longest session", f"{sessions['Minutes'].max():.1f}m")
    c3.metric("Most events/session", metric_value(sessions["Events"].max()))

    st.subheader("Top Sessions")
    top_sessions = sessions.sort_values(["Events", "Minutes"], ascending=False).head(100)
    st.dataframe(
        top_sessions[["SessionID", "StartText", "EndText", "Minutes", "Events", "RareItems", "Actions", "Lat", "Lon"]],
        width="stretch",
        hide_index=True,
    )

with tab_quality:
    st.subheader("Data Quality")
    raw_rows = int(df.attrs.get("raw_rows", len(df)))
    invalid_rows = int(df.attrs.get("invalid_time_rows", 0))
    future_rows = int((filtered["Time"] >= FUTURE_CUTOFF).sum())
    blank_actions = int((filtered["Action"] == "").sum())
    garbled = filtered["Detail"].str.contains("Ã|æ|è|ð", regex=True, na=False)

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Raw rows", metric_value(raw_rows))
    q2.metric("Invalid time rows", metric_value(invalid_rows))
    q3.metric("Future rows", metric_value(future_rows))
    q4.metric("Blank actions", metric_value(blank_actions))

    if future_rows:
        st.caption(f"Future cutoff: {FUTURE_CUTOFF.strftime('%Y-%m-%d %H:%M %Z')}")
        future = filtered[filtered["Time"] >= FUTURE_CUTOFF].sort_values("Time").copy()
        future["TimeText"] = local_time_text(future["Time"], tz_name)
        st.dataframe(
            future[["TimeText", "Action", "DetailShort", "Lat", "Lon"]].head(200),
            width="stretch",
            hide_index=True,
        )
    if garbled.any():
        st.caption("Possible mojibake / garbled text")
        bad = filtered[garbled].sort_values("Time", ascending=False).copy()
        bad["TimeText"] = local_time_text(bad["Time"], tz_name)
        st.dataframe(bad[["TimeText", "Action", "DetailShort"]].head(100), width="stretch", hide_index=True)

with tab_explorer:
    st.subheader("Detail Explorer")
    detail_counts = (
        filtered["DetailShort"]
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .head(50)
        .rename_axis("Detail")
        .reset_index(name="Count")
    )
    if len(detail_counts):
        st.dataframe(detail_counts, width="stretch", hide_index=True)

    st.subheader("Raw Log")
    raw = filtered.sort_values("Time", ascending=False).copy()
    raw["TimeText"] = local_time_text(raw["Time"], tz_name)
    st.dataframe(
        raw[["TimeText", "Action", "DetailShort", "ItemName", "ItemEvent", "Lat", "Lon"]].head(1000),
        width="stretch",
        hide_index=True,
    )
