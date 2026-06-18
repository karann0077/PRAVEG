"""Event-calendar context features for Bengaluru parking predictions."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_EVENT_HUBS_PATH = DATA_DIR / "bengaluru_event_hubs.csv"
DEFAULT_EVENT_CALENDAR_PATH = DATA_DIR / "bengaluru_event_calendar.csv"

EARTH_RADIUS_M = 6_371_008.8
EVENT_DECAY_DISTANCE_M = 1_000.0
NO_ACTIVE_EVENT_DISTANCE_M = 1_000_000.0

DISTANCE_COLUMN = "distance_to_active_event_m"
IMPACT_COLUMN = "event_impact_score"


def load_event_hubs(path: str | Path | None = None) -> pd.DataFrame:
    """Load the venue seed table used to locate scheduled event hubs."""

    source = Path(path) if path is not None else DEFAULT_EVENT_HUBS_PATH
    return _coerce_event_hubs(pd.read_csv(source))


def load_event_calendar(
    path: str | Path | None = None,
    local_timezone: str = "Asia/Kolkata",
) -> pd.DataFrame:
    """Load scheduled or historical events and normalize timestamps to local time."""

    source = Path(path) if path is not None else DEFAULT_EVENT_CALENDAR_PATH
    return _coerce_event_calendar(pd.read_csv(source), local_timezone=local_timezone)


def add_event_context(
    segment_hours: pd.DataFrame,
    event_hubs: pd.DataFrame | str | Path | None = None,
    event_calendar: pd.DataFrame | str | Path | None = None,
    *,
    local_timezone: str = "Asia/Kolkata",
    lat_col: str = "lat_center",
    lon_col: str = "lon_center",
    hour_col: str = "target_hour",
    no_event_distance_m: float = NO_ACTIVE_EVENT_DISTANCE_M,
) -> pd.DataFrame:
    """Attach nearest-active-event distance and decayed impact for each segment-hour.

    An event is active for a row when its event interval overlaps the row's hourly
    bucket: ``event_start < target_hour + 1h`` and ``event_end > target_hour``.
    Rows with no active event receive a large finite distance and a zero impact.
    """

    _require_columns(segment_hours, {lat_col, lon_col, hour_col}, "segment_hours")
    hubs = _load_hub_source(event_hubs)
    calendar = _load_calendar_source(event_calendar, local_timezone)

    frame = segment_hours.copy()
    row_count = len(frame)
    distances = np.full(row_count, float(no_event_distance_m), dtype=float)
    impacts = np.zeros(row_count, dtype=float)
    active_counts = np.zeros(row_count, dtype=int)
    nearest_venues = np.full(row_count, "", dtype=object)
    nearest_labels = np.full(row_count, "", dtype=object)

    if row_count == 0:
        return _assign_event_columns(frame, distances, impacts, active_counts, nearest_venues, nearest_labels)

    events = calendar.merge(
        hubs[["venue", "latitude", "longitude"]],
        on="venue",
        how="left",
        validate="many_to_one",
    )
    missing_coords = events["latitude"].isna() | events["longitude"].isna()
    if missing_coords.any():
        missing = sorted(events.loc[missing_coords, "venue"].astype(str).unique().tolist())
        raise ValueError(f"Event calendar references venues without coordinates: {missing}")

    if events.empty:
        return _assign_event_columns(frame, distances, impacts, active_counts, nearest_venues, nearest_labels)

    target_hours = _normalize_timestamp_series(frame[hour_col], local_timezone).dt.floor("h")
    target_hours = pd.Series(target_hours.to_numpy(), index=np.arange(row_count))
    lats = pd.to_numeric(frame[lat_col], errors="coerce").to_numpy(dtype=float)
    lons = pd.to_numeric(frame[lon_col], errors="coerce").to_numpy(dtype=float)

    for target_hour, positions in target_hours.groupby(target_hours, dropna=True).groups.items():
        hour_start = pd.Timestamp(target_hour)
        hour_end = hour_start + pd.Timedelta(hours=1)
        active = events.loc[(events["start_ts"] < hour_end) & (events["end_ts"] > hour_start)]
        if active.empty:
            continue

        positions = np.asarray(list(positions), dtype=int)
        active_counts[positions] = len(active)

        valid_position_mask = np.isfinite(lats[positions]) & np.isfinite(lons[positions])
        if not valid_position_mask.any():
            continue

        valid_positions = positions[valid_position_mask]
        active_lats = active["latitude"].to_numpy(dtype=float)
        active_lons = active["longitude"].to_numpy(dtype=float)
        distance_matrix = haversine_distance_m(
            lats[valid_positions, np.newaxis],
            lons[valid_positions, np.newaxis],
            active_lats[np.newaxis, :],
            active_lons[np.newaxis, :],
        )
        nearest_idx = np.argmin(distance_matrix, axis=1)
        nearest_distances = distance_matrix[np.arange(len(valid_positions)), nearest_idx]

        distances[valid_positions] = nearest_distances
        impacts[valid_positions] = event_impact_score(nearest_distances)
        nearest_venues[valid_positions] = active["venue"].to_numpy(dtype=object)[nearest_idx]
        nearest_labels[valid_positions] = active["label"].fillna("").to_numpy(dtype=object)[nearest_idx]

    impacts[active_counts == 0] = 0.0
    return _assign_event_columns(frame, distances, impacts, active_counts, nearest_venues, nearest_labels)


def distance_to_active_event_m(
    segment_hours: pd.DataFrame,
    event_hubs: pd.DataFrame | str | Path | None = None,
    event_calendar: pd.DataFrame | str | Path | None = None,
    *,
    local_timezone: str = "Asia/Kolkata",
    lat_col: str = "lat_center",
    lon_col: str = "lon_center",
    hour_col: str = "target_hour",
    no_event_distance_m: float = NO_ACTIVE_EVENT_DISTANCE_M,
) -> pd.Series:
    """Return nearest active-event distance in meters for each segment-hour row."""

    return add_event_context(
        segment_hours,
        event_hubs=event_hubs,
        event_calendar=event_calendar,
        local_timezone=local_timezone,
        lat_col=lat_col,
        lon_col=lon_col,
        hour_col=hour_col,
        no_event_distance_m=no_event_distance_m,
    )[DISTANCE_COLUMN]


def event_impact_score(distance_m: Iterable[float] | float) -> np.ndarray | float:
    """Compute the event impact decay score: exp(-distance_m / 1000)."""

    distance = np.asarray(distance_m, dtype=float)
    scores = np.exp(-np.clip(distance, 0.0, None) / EVENT_DECAY_DISTANCE_M)
    scores = np.where(np.isfinite(distance), scores, 0.0)
    if np.isscalar(distance_m):
        return float(scores)
    return scores


def haversine_distance_m(
    lat1: Iterable[float] | float,
    lon1: Iterable[float] | float,
    lat2: Iterable[float] | float,
    lon2: Iterable[float] | float,
) -> np.ndarray:
    """Vectorized haversine distance in meters with numpy broadcasting."""

    lat1_rad = np.radians(np.asarray(lat1, dtype=float))
    lon1_rad = np.radians(np.asarray(lon1, dtype=float))
    lat2_rad = np.radians(np.asarray(lat2, dtype=float))
    lon2_rad = np.radians(np.asarray(lon2, dtype=float))

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _assign_event_columns(
    frame: pd.DataFrame,
    distances: np.ndarray,
    impacts: np.ndarray,
    active_counts: np.ndarray,
    nearest_venues: np.ndarray,
    nearest_labels: np.ndarray,
) -> pd.DataFrame:
    frame[DISTANCE_COLUMN] = distances
    frame[IMPACT_COLUMN] = impacts
    frame["active_event_count"] = active_counts
    frame["nearest_active_event_venue"] = nearest_venues
    frame["nearest_active_event_label"] = nearest_labels
    return frame


def _load_hub_source(source: pd.DataFrame | str | Path | None) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return _coerce_event_hubs(source)
    return load_event_hubs(source)


def _load_calendar_source(
    source: pd.DataFrame | str | Path | None,
    local_timezone: str,
) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        return _coerce_event_calendar(source, local_timezone=local_timezone)
    return load_event_calendar(source, local_timezone=local_timezone)


def _coerce_event_hubs(hubs: pd.DataFrame) -> pd.DataFrame:
    _require_columns(hubs, {"venue", "latitude", "longitude"}, "event_hubs")
    frame = hubs.copy()
    frame["venue"] = frame["venue"].astype(str).str.strip()
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")

    if frame["venue"].eq("").any():
        raise ValueError("event_hubs contains blank venue values")
    if frame["venue"].duplicated().any():
        duplicates = sorted(frame.loc[frame["venue"].duplicated(), "venue"].unique().tolist())
        raise ValueError(f"event_hubs contains duplicate venues: {duplicates}")
    if frame[["latitude", "longitude"]].isna().any().any():
        raise ValueError("event_hubs contains non-numeric latitude or longitude values")
    return frame.reset_index(drop=True)


def _coerce_event_calendar(calendar: pd.DataFrame, local_timezone: str) -> pd.DataFrame:
    _require_columns(calendar, {"venue", "start_ts", "end_ts"}, "event_calendar")
    frame = calendar.copy()
    if "label" not in frame.columns:
        frame["label"] = ""

    frame["venue"] = frame["venue"].astype(str).str.strip()
    frame["label"] = frame["label"].fillna("").astype(str)
    frame["start_ts"] = _normalize_timestamp_series(frame["start_ts"], local_timezone)
    frame["end_ts"] = _normalize_timestamp_series(frame["end_ts"], local_timezone)

    if frame["venue"].eq("").any():
        raise ValueError("event_calendar contains blank venue values")
    if frame[["start_ts", "end_ts"]].isna().any().any():
        raise ValueError("event_calendar contains invalid start_ts or end_ts values")
    invalid_window = frame["end_ts"] <= frame["start_ts"]
    if invalid_window.any():
        invalid_ids = frame.loc[invalid_window, "event_id"].astype(str).tolist() if "event_id" in frame else []
        detail = f": {invalid_ids}" if invalid_ids else ""
        raise ValueError(f"event_calendar contains events where end_ts is not after start_ts{detail}")
    return frame.reset_index(drop=True)


def _normalize_timestamp_series(values: Iterable[object], local_timezone: str) -> pd.Series:
    return pd.Series([_normalize_timestamp(value, local_timezone) for value in values])


def _normalize_timestamp(value: object, local_timezone: str) -> pd.Timestamp:
    if pd.isna(value):
        return pd.NaT
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return pd.NaT
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(None)
    return timestamp.tz_convert(local_timezone).tz_localize(None)


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")
