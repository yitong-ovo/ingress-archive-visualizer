"""Shared display-time helpers for Streamlit pages."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st


COMMON_TIMEZONES = [
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Asia/Seoul",
    "UTC",
    "America/Los_Angeles",
    "America/New_York",
    "Europe/London",
    "Europe/Paris",
    "Australia/Sydney",
]


def get_timezone_name(default: str = "Asia/Singapore") -> str:
    tz_name = st.session_state.get("display_timezone", default)
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = default
        st.session_state["display_timezone"] = tz_name
    return tz_name


def timezone_selector(default: str = "Asia/Singapore") -> str:
    current = get_timezone_name(default)
    options = COMMON_TIMEZONES + ["Custom"]
    index = COMMON_TIMEZONES.index(current) if current in COMMON_TIMEZONES else len(options) - 1
    choice = st.sidebar.selectbox("Display timezone", options, index=index, key="display_timezone_choice")
    if choice == "Custom":
        custom = st.sidebar.text_input("IANA timezone", value=current, key="display_timezone_custom")
        try:
            ZoneInfo(custom)
            st.session_state["display_timezone"] = custom
        except ZoneInfoNotFoundError:
            st.sidebar.warning("Invalid timezone. Example: Asia/Singapore")
            st.session_state["display_timezone"] = current
    else:
        st.session_state["display_timezone"] = choice
    return st.session_state["display_timezone"]


def to_local_time(series: pd.Series, tz_name: str) -> pd.Series:
    time = pd.to_datetime(series, errors="coerce", utc=True)
    return time.dt.tz_convert(tz_name)


def local_date(series: pd.Series, tz_name: str) -> pd.Series:
    return to_local_time(series, tz_name).dt.date


def local_month_start(series: pd.Series, tz_name: str) -> pd.Series:
    return to_local_time(series, tz_name).dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()


def local_week_start(series: pd.Series, tz_name: str) -> pd.Series:
    return to_local_time(series, tz_name).dt.tz_localize(None).dt.to_period("W").dt.start_time


def local_time_text(series: pd.Series, tz_name: str, fmt: str = "%Y-%m-%d %H:%M") -> pd.Series:
    return to_local_time(series, tz_name).dt.strftime(fmt)
