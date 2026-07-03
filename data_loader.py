"""
Data loader: TSV/CSV parsing for Ingress GDPR data exports.

All server-side parsing stays in memory.
"""
from __future__ import annotations

import io
import os
import re
from collections.abc import Iterable

import pandas as pd
import streamlit as st

FileSource = str | bytes

# ── main parse entry ──────────────────────────────────────────

def parse_directory(dir_path: str, source_id: str) -> dict[str, pd.DataFrame]:
    """Parse an extracted directory into a dict of DataFrames."""
    return _parse_all(dir_path, source_id)


def parse_archive(files: dict[str, bytes], source_id: str) -> dict[str, pd.DataFrame]:
    """Parse ZIP members held in memory into a dict of DataFrames."""
    return _parse_archive_files(files, source_id)


def _parse_all(root: str, source_id: str) -> dict[str, pd.DataFrame]:
    """Walk root directory and parse every supported file."""
    all_files = _collect_files(root)
    data: dict[str, pd.DataFrame] = {}

    # player journey csvs
    pj_dir = os.path.join(root, "Player_Journey")
    has_pj = os.path.isdir(pj_dir)

    for key, path in all_files.items():
        try:
            df = _parse_file(key, path, has_pj)
            if df is not None and len(df) > 0:
                data[key] = df
        except Exception as e:
            st.warning(f"Failed to parse {key}: {e}")

    # agent profile
    prof = _parse_profile(root)
    if prof:
        data["_profile"] = pd.DataFrame(
            [{"key": k, "value": v} for k, v in prof.items()]
        )

    # player journey combined
    if has_pj:
        pj = _parse_player_journey(pj_dir)
        if pj is not None and len(pj) > 0:
            data["player_journey_actions"] = pj

    return data


def _parse_archive_files(files: dict[str, bytes], source_id: str) -> dict[str, pd.DataFrame]:
    """Parse supported files from an in-memory archive member map."""
    all_files = _collect_archive_files(files)
    player_journey_files = _collect_player_journey_archive_files(files)
    has_pj = bool(player_journey_files)
    data: dict[str, pd.DataFrame] = {}

    for key, source in all_files.items():
        try:
            df = _parse_file(key, source, has_pj)
            if df is not None and len(df) > 0:
                data[key] = df
        except Exception as e:
            st.warning(f"Failed to parse {key}: {e}")

    prof = _parse_profile_archive(files)
    if prof:
        data["_profile"] = pd.DataFrame(
            [{"key": k, "value": v} for k, v in prof.items()]
        )

    if has_pj:
        pj = _parse_player_journey_sources(player_journey_files.items())
        if pj is not None and len(pj) > 0:
            data["player_journey_actions"] = pj

    return data


# ── file discovery ────────────────────────────────────────────

_KNOWN_FILES: dict[str, str] = {
    "deploys": "deploys.tsv",
    "hacks": "hacks.tsv",
    "links_created": "links_created.tsv",
    "links_destroyed": "links_destroyed_corrected.tsv",
    "resonators_destroyed": "resonators_destroyed.tsv",
    "resonators_upgraded": "resonators_upgraded.tsv",
    "mods_deployed": "mods_deployed.tsv",
    "mods_destroyed": "mods_destroyed.tsv",
    "xm_collected": "xm_collected.tsv",
    "xm_recharged": "xm_recharged.tsv",
    "keys_hacked": "keys_hacked.tsv",
    "glyph_hack_attempts": "glyph_hack_attempts.tsv",
    "glyph_hack_points": "glyph_hack_points.tsv",
    "overclock_glyph_hack_points": "overclock_glyph_hack_points.tsv",
    "glyph_the_planet": "glyph_the_planet.tsv",
    "hack_streaks_completed": "hack_streaks_completed.tsv",
    "flip_cards_used": "flip_cards_used.tsv",
    "powercube_used": "powercube_used.tsv",
    "apex_mods_used": "apex_mods_used.tsv",
    "inventory_item_recycled": "inventory_item_recycled.tsv",
    "kinetic_capsules_completed": "kinetic_capsules_completed.tsv",
    "passcode_redeemed": "passcode_redeemed.tsv",
    "fully_deployed": "fully_deployed.tsv",
    "agent_ops_completed": "agent_ops_completed.tsv",
    "portal_guids_visited": "portal_guids_visited.tsv",
    "portal_guids_captured": "portal_guids_captured.tsv",
    "portals_neutralized": "portals_neutralized.tsv",
    "ports_owned": "portals_owned.tsv",
    "scout_controller_portal_guids": "scout_controller_portal_guids.tsv",
    "drone_hack_portal_guids": "drone_hack_portal_guids.tsv",
    "drone_visited_portal_guid": "drone_visited_portal_guid.tsv",
    "beacon_battles": "beacon_battles.tsv",
    "portal_powerups_used": "portal_powerups_used.tsv",
    "missions_completed": "missions_completed.tsv",
    "agents_recruited": "agents_recruited.tsv",
    "ar_videos_uploaded": "ar_videos_uploaded.tsv",
    "mind_units_controlled": "mind_units_controlled.tsv",
    "mind_units_controlled_active": "mind_units_controlled_active.tsv",
    "mind_units_destroyed": "mind_units_destroyed.tsv",
    "mind_units_times_days_held": "mind_units_times_days_held.tsv",
    "regions_created": "regions_created.tsv",
    "regions_destroyed": "regions_destroyed_corrected.tsv",
    "link_length_kilometers": "link_length_kilometers.tsv",
    "link_held_days": "link_held_days.tsv",
    "link_length_kilometers_times_days_held": "link_length_kilometers_times_days_held.tsv",
    "portal_held_days": "portal_held_days.tsv",
    "region_held_days": "region_held_days.tsv",
    "machina_portals_neutralized": "machina_portals_neutralized.tsv",
    "machina_portals_reclaimed_guids": "machina_portals_reclaimed_guids.tsv",
    "machina_links_destroyed": "machina_links_destroyed.tsv",
    "machina_resonators_destroyed": "machina_resonators_destroyed.tsv",
    "kilometers_walked": "kilometers_walked.tsv",
    "kilometers_walked_new": "kilometers_walked_new.tsv",
    "portal_history": "portal_history.tsv",
    "game_log": "game_log.tsv",
    "GameplayLocationHistory": "GameplayLocationHistory.tsv",
    "Logins": "Logins.tsv",
    "FitnessData": "FitnessData.tsv",
    "InAppPurchases": "InAppPurchases.tsv",
    "store_purchases": "store_purchases.tsv",
    "subscriptions_monthly": "subscriptions_monthly.tsv",
    "cargo_amounts_applied": "cargo_amounts_applied.tsv",
    "second_sunday_events": "second_sunday_events.tsv",
    "nl1331_meetup_points": "nl1331_meetup_points.tsv",
    "all_portals_approved": "all_portals_approved.tsv",
    "portals_approved": "portals_approved.tsv",
    "portals_approved_annex": "portals_approved_annex.tsv",
    "seer_portals": "seer_portals.tsv",
    "drone_range_km": "drone_range_km.tsv",
    "drones_sent_home": "drones_sent_home.tsv",
    "drone_forced_recalls": "drone_forced_recalls.tsv",
    "comm_mentions": "comm_mentions.tsv",
    "completed_all_daily_quests": "completed_all_daily_quests.tsv",
    # event & season files
    "event_alpha": "event_alpha.tsv",
    "event_bravo": "event_bravo.tsv",
    "event_delta": "event_delta.tsv",
    "event_echo": "event_echo.tsv",
    "event_foxtrot": "event_foxtrot.tsv",
    "event_golf": "event_golf.tsv",
    "event_india": "event_india.tsv",
    "event_juliet": "event_juliet.tsv",
    "event_kilo": "event_kilo.tsv",
    "event_mike": "event_mike.tsv",
    "event_november": "event_november.tsv",
    "event_oscar": "event_oscar.tsv",
    "plus_alpha_global_op_points": "plus_alpha_global_op_points.tsv",
    "plus_beta_season_points": "plus_beta_season_points.tsv",
    "plus_gamma_season_points": "plus_gamma_season_points.tsv",
    "plus_delta_season_points": "plus_delta_season_points.tsv",
    "plus_theta_season_points": "plus_theta_season_points.tsv",
    "orion_season_points": "orion_season_points.tsv",
    "operation_chronos_points": "operation_chronos_points.tsv",
    "buried_memories_event_points": "buried_memories_event_points.tsv",
    "buried_memories_anomaly_guids": "buried_memories_anomaly_guids.tsv",
    "cryptic_memories_points": "cryptic_memories_points.tsv",
    "cryptic_memories_anomaly_guids": "cryptic_memories_anomaly_guids.tsv",
    "erased_memories_global_op_points": "erased_memories_global_op_points.tsv",
    "erased_memories_anomaly_guids": "erased_memories_anomaly_guids.tsv",
    "shared_memories_event_points": "shared_memories_event_points.tsv",
    "shared_memories_anomaly_guids": "shared_memories_anomaly_guids.tsv",
    "ctrl_anomaly_guids_2023": "ctrl_anomaly_guids_2023.tsv",
    "discoverie_anomaly_guids_2023": "discoverie_anomaly_guids_2023.tsv",
    "echo_anomaly_guids_2023": "echo_anomaly_guids_2023.tsv",
    "plus_alpha_anomaly_guids": "plus_alpha_anomaly_guids.tsv",
    "orion_global_guids": "orion_global_guids.tsv",
    "eos_imprint_points": "eos_imprint_points.tsv",
    "field_test_dispatch_points": "field_test_dispatch_points.tsv",
    "mission_day_points": "mission_day_points.tsv",
    "courier_ap_gained": "courier_ap_gained.tsv",
    "darkxm_link_length": "darkxm_link_length.tsv",
    "poi_submissions": "poi_submissions.tsv",
    "poi_image_submissions": "poi_image_submissions.tsv",
}


def _collect_files(root: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, fname in _KNOWN_FILES.items():
        path = os.path.join(root, fname)
        if os.path.isfile(path):
            found[key] = path
    return found


def _normalize_archive_name(name: str) -> str:
    norm = name.replace("\\", "/").lstrip("/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _archive_basename_index(files: dict[str, bytes]) -> dict[str, bytes]:
    indexed: dict[str, tuple[str, bytes]] = {}
    for name, content in files.items():
        norm = _normalize_archive_name(name)
        if not norm or norm.endswith("/"):
            continue
        basename = norm.rsplit("/", 1)[-1]
        current = indexed.get(basename)
        if current is None or norm.count("/") < current[0].count("/"):
            indexed[basename] = (norm, content)
    return {basename: content for basename, (_, content) in indexed.items()}


def _collect_archive_files(files: dict[str, bytes]) -> dict[str, bytes]:
    by_basename = _archive_basename_index(files)
    return {
        key: by_basename[fname]
        for key, fname in _KNOWN_FILES.items()
        if fname in by_basename
    }


def _collect_player_journey_archive_files(files: dict[str, bytes]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for name, content in files.items():
        norm = _normalize_archive_name(name)
        parts = norm.split("/")
        if len(parts) >= 2 and parts[-2] == "Player_Journey" and parts[-1].endswith(".csv"):
            found[parts[-1]] = content
    return found


def _read_text_lines(source: FileSource) -> list[str]:
    def split_physical_lines(text: str) -> list[str]:
        return [line.removesuffix("\r") for line in text.split("\n")]

    if isinstance(source, bytes):
        return split_physical_lines(source.decode("utf-8"))
    with open(source, "r", encoding="utf-8") as f:
        return split_physical_lines(f.read())


def _source_size(source: FileSource) -> int:
    if isinstance(source, bytes):
        return len(source)
    return os.path.getsize(source)


def _read_csv(source: FileSource, *args, **kwargs) -> pd.DataFrame:
    csv_source = io.BytesIO(source) if isinstance(source, bytes) else source
    return pd.read_csv(csv_source, *args, **kwargs)


def decode_export_text_field(value: str) -> str:
    """Decode fields stored as UTF-8 text after an earlier Latin-1 misdecode."""
    if not isinstance(value, str) or not value:
        return value
    if not any(marker in value for marker in ("Ã", "Â", "å", "æ", "ç", "è", "é", "ä", "ï", "ð")):
        return value
    try:
        return value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


# ── file parsers ──────────────────────────────────────────────

_TIME_VAL_COLS = ["Time", "Value"]
_TIME_UID_COLS = ["Time", "Unique_ID"]


def _parse_file(key: str, path: FileSource, has_pj: bool) -> pd.DataFrame | None:
    if key == "game_log":
        return _parse_game_log(path)
    if key == "GameplayLocationHistory":
        return _parse_location_history(path)
    if key == "Logins":
        return _parse_logins(path)
    if key == "FitnessData":
        return _parse_fitness(path)
    if key == "InAppPurchases":
        return _parse_iap(path)
    if key == "store_purchases":
        return _parse_store(path)
    if key == "subscriptions_monthly":
        return _parse_simple_tsv(path, ["Time", "Value"], date_col="Time")
    if key == "portal_history":
        return _parse_portal_history(path)
    if key == "comm_mentions":
        return _parse_simple_tsv(path, ["Time", "Message"], date_col="Time")
    if key == "poi_submissions":
        return _parse_poi_submissions(path)
    if key == "cargo_amounts_applied":
        return _parse_simple_tsv(path, ["Time", "Value"], date_col="Time")
    if key == "completed_all_daily_quests":
        return _parse_simple_tsv(path, ["Time", "Value"], date_col="Time")
    if key == "eos_imprint_points":
        return None  # empty
    # generic time/value or time/unique_id
    return _parse_generic_tsv(key, path, has_pj)


def _parse_generic_tsv(key: str, path: FileSource, has_pj: bool) -> pd.DataFrame | None:
    """Try to auto-detect column format."""
    try:
        lines = _read_text_lines(path)
        header = lines[0].strip() if lines else ""
    except Exception:
        return None

    parts = [h.strip() for h in header.split("\t")]

    # skip files that are just headers with no data rows
    file_size = _source_size(path)
    if file_size < 50:
        return None

    if len(parts) >= 2:
        if "Unique" in parts[1] or "GUID" in parts[1] or "ID" in parts[1] or "guid" in header.lower():
            return _parse_simple_tsv(path, _TIME_UID_COLS, date_col="Time")
        if "Value" in parts[1] or "value" in parts[1].lower() or "points" in header.lower():
            return _parse_simple_tsv(path, _TIME_VAL_COLS, date_col="Time")
        # default: assume time + value
        return _parse_simple_tsv(path, _TIME_VAL_COLS, date_col="Time")
    return None


def _parse_simple_tsv(
    path: FileSource, col_names: list[str], date_col: str | None = "Time"
) -> pd.DataFrame | None:
    try:
        df = _read_csv(
            path, sep="\t", encoding="utf-8", on_bad_lines="skip",
            names=col_names, header=0, low_memory=False,
        )
        if date_col and date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        if "Value" in df.columns:
            df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(1.0)
        return df
    except Exception:
        return None


def _parse_game_log(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 5:
            ts = parts[0]
            lat = parts[1]
            lon = parts[2]
            action = parts[3]
            detail = "\t".join(parts[4:])
            rows.append([ts, lat, lon, action, detail])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Time", "Lat", "Lon", "Action", "Detail"])
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    df["Detail"] = df["Detail"].map(decode_export_text_field)
    return df


def _parse_location_history(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        ts = parts[0] if len(parts) >= 1 else ""
        lat = parts[1] if len(parts) >= 2 else ""
        lon = parts[2] if len(parts) >= 3 else ""
        rows.append([ts, lat, lon])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Time", "Lat", "Lon"])
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    return df.dropna(subset=["Lat", "Lon"])


def _parse_logins(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        ts = parts[0]
        val = parts[1] if len(parts) > 1 else ""
        if "Force" in val or "Quit" in val:
            rows.append([ts, None, val])
        else:
            try:
                mins = float(val)
                rows.append([ts, mins, "session"])
            except ValueError:
                rows.append([ts, None, val])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Time", "Duration", "Type"])
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    df["Duration"] = pd.to_numeric(df["Duration"], errors="coerce")
    return df


def _parse_fitness(path: FileSource) -> pd.DataFrame | None:
    try:
        df = _read_csv(path, sep="\t", encoding="utf-8", on_bad_lines="skip")
        ts_col = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
        if ts_col:
            df["Time"] = pd.to_datetime(df[ts_col[0]], errors="coerce", utc=True)
        return df
    except Exception:
        return None


def _parse_iap(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        rows.append({
            "Time": parts[0],
            "Type": parts[1] if len(parts) > 1 else "",
            "Item": parts[2] if len(parts) > 2 else "",
            "Money": parts[3] if len(parts) > 3 else "",
            "Currency": parts[4] if len(parts) > 4 else "",
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    return df


def _parse_store(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        rows.append({
            "Time": parts[0],
            "TransactionType": parts[1] if len(parts) > 1 else "",
            "Item": parts[2] if len(parts) > 2 else "",
            "NewCMUBalance": parts[3] if len(parts) > 3 else "",
            "Description": "\t".join(parts[4:]) if len(parts) > 4 else "",
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    df["NewCMUBalance"] = pd.to_numeric(df["NewCMUBalance"], errors="coerce")
    return df


def _parse_portal_history(path: FileSource) -> pd.DataFrame | None:
    try:
        df = _read_csv(path, sep="\t", encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except Exception:
        return None
    if len(df) == 0 or len(df.columns) < 3:
        return None

    col_by_lower = {str(c).lower(): c for c in df.columns}
    rename: dict[str, str] = {}
    if "lat" in col_by_lower:
        rename[col_by_lower["lat"]] = "Lat"
    elif "Lat" not in df.columns:
        rename[df.columns[1]] = "Lat"
    if "lon" in col_by_lower:
        rename[col_by_lower["lon"]] = "Lon"
    elif "lng" in col_by_lower:
        rename[col_by_lower["lng"]] = "Lon"
    elif "longitude" in col_by_lower:
        rename[col_by_lower["longitude"]] = "Lon"
    elif "Lon" not in df.columns:
        rename[df.columns[2]] = "Lon"
    if "type" in col_by_lower:
        rename[col_by_lower["type"]] = "Type"
    elif "Type" not in df.columns:
        rename[df.columns[0]] = "Type"
    if rename:
        df = df.rename(columns=rename)

    if "Lat" not in df.columns or "Lon" not in df.columns:
        return None

    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    return df.dropna(subset=["Lat", "Lon"])


def _parse_poi_submissions(path: FileSource) -> pd.DataFrame | None:
    rows = []
    for line in _read_text_lines(path)[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        lat_lon = parts[1] if len(parts) > 1 else ""
        title = parts[2] if len(parts) > 2 else ""
        lon_val = ""
        lat_val = ""
        if "," in lat_lon:
            coords = lat_lon.split(",")
            lat_val = coords[0].strip()
            lon_val = coords[1].strip()
        rows.append({
            "Time": parts[0],
            "Lat": lat_val,
            "Lon": lon_val,
            "Title": title,
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce", utc=True, format="mixed")
    df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
    return df


# ── profile parser ────────────────────────────────────────────

def _parse_profile(root: str) -> dict:
    path = os.path.join(root, "profile.txt")
    if not os.path.isfile(path):
        return {}
    return _parse_profile_source(path)


def _parse_profile_archive(files: dict[str, bytes]) -> dict:
    by_basename = _archive_basename_index(files)
    source = by_basename.get("profile.txt")
    if source is None:
        return {}
    return _parse_profile_source(source)


def _parse_profile_source(source: FileSource) -> dict:
    prof: dict = {}
    for line in _read_text_lines(source):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.+?):\s*(.*)", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            prof[key] = val
    return prof


# ── player journey ────────────────────────────────────────────

def _parse_player_journey(pj_dir: str) -> pd.DataFrame | None:
    sources = []
    for fname in os.listdir(pj_dir):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(pj_dir, fname)
        sources.append((fname, path))
    return _parse_player_journey_sources(sources)


def _parse_player_journey_sources(sources: Iterable[tuple[str, FileSource]]) -> pd.DataFrame | None:
    frames = []
    for fname, source in sources:
        try:
            df = _read_csv(source, encoding="utf-8", low_memory=False)
            if "Latitude" in df.columns and "Longitude" in df.columns:
                df.rename(columns={"Latitude": "Lat", "Longitude": "Lon"}, inplace=True)
            if "Timestamp" in df.columns:
                df["Time"] = pd.to_datetime(df["Timestamp"], errors="coerce", utc=True)
                df.drop(columns=["Timestamp"], inplace=True)
            if "Lat" in df.columns and "Lon" in df.columns and "Time" in df.columns:
                df["Lat"] = pd.to_numeric(df["Lat"], errors="coerce")
                df["Lon"] = pd.to_numeric(df["Lon"], errors="coerce")
                action = fname.replace(".csv", "").replace("_", " ").strip()
                df["Action"] = action
                sub = df[["Time", "Lat", "Lon", "Action"]].dropna(subset=["Lat", "Lon"])
                if len(sub) > 0:
                    frames.append(sub)
        except Exception:
            pass
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)
