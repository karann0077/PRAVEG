"""Feature engineering for hotspot and bottleneck prediction."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from shapely import wkt

from .config import (
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    PEAK_HOURS,
    ROAD_WIDTH_BY_CLASS_M,
    TARGET_COLUMNS,
    VEHICLE_TYPE_TO_CLASS,
)


PARKING_TERMS = (
    "PARKING",
    "NO PARKING",
    "WRONG PARKING",
    "DOUBLE PARKING",
    "FOOTPATH",
)


@dataclass(frozen=True)
class FeatureContext:
    """Data needed to create future feature rows consistently."""

    start_hour: pd.Timestamp
    end_hour: pd.Timestamp
    local_timezone: str
    grid_size_deg: float
    history_counts: pd.DataFrame
    segment_metadata: pd.DataFrame
    stats: dict[str, pd.DataFrame | float | int]
    category_levels: dict[str, list[str]]
    selected_segments: list[str]


def load_events(
    data_path: str | Path,
    local_timezone: str = "Asia/Kolkata",
    grid_size_deg: float = 0.001,
    parking_only: bool = True,
) -> pd.DataFrame:
    """Load raw violation rows and normalize them into modeling events."""

    usecols = [
        "id",
        "latitude",
        "longitude",
        "location",
        "vehicle_type",
        "updated_vehicle_type",
        "violation_type",
        "created_datetime",
        "police_station",
        "junction_name",
    ]
    events = pd.read_csv(data_path, usecols=lambda c: c in usecols)
    events = events.dropna(subset=["latitude", "longitude", "created_datetime"])
    events["created_datetime"] = pd.to_datetime(
        events["created_datetime"], errors="coerce", utc=True
    )
    events = events.dropna(subset=["created_datetime"])
    events["event_time"] = (
        events["created_datetime"]
        .dt.tz_convert(local_timezone)
        .dt.tz_localize(None)
    )
    events["event_hour"] = events["event_time"].dt.floor("h")

    updated = events.get("updated_vehicle_type")
    if updated is not None:
        chosen_vehicle = updated.where(updated.notna(), events["vehicle_type"])
    else:
        chosen_vehicle = events["vehicle_type"]
    events["vehicle_type_clean"] = chosen_vehicle.fillna("OTHERS").map(_clean_label)
    events["vehicle_class"] = events["vehicle_type_clean"].map(VEHICLE_TYPE_TO_CLASS)
    events["vehicle_class"] = events["vehicle_class"].fillna("other")

    events["violation_type"] = events["violation_type"].fillna("")
    if parking_only:
        parking_mask = events["violation_type"].str.upper().apply(
            lambda value: any(term in value for term in PARKING_TERMS)
        )
        events = events.loc[parking_mask].copy()

    lat_bin = np.floor(events["latitude"].astype(float) / grid_size_deg).astype("int64")
    lon_bin = np.floor(events["longitude"].astype(float) / grid_size_deg).astype("int64")
    events["lat_bin"] = lat_bin
    events["lon_bin"] = lon_bin
    events["segment_id"] = "grid_" + lat_bin.astype(str) + "_" + lon_bin.astype(str)
    events["map_matching_mode"] = "grid_fallback"
    events["police_station"] = events["police_station"].fillna("Unknown").map(_clean_text)
    events["junction_name"] = events["junction_name"].fillna("No Junction").map(_clean_text)
    events["location"] = events["location"].fillna("").map(_clean_text)
    events["junction_bucket"] = np.where(
        events["junction_name"].str.upper().eq("NO JUNCTION"),
        "No Junction",
        "Named Junction",
    )
    events["road_class"] = events.apply(infer_road_class, axis=1)
    events["road_width_m"] = events["road_class"].map(ROAD_WIDTH_BY_CLASS_M).fillna(6.0)
    return events


def select_active_segments(
    events: pd.DataFrame,
    min_segment_events: int = 20,
    max_segments: int | None = None,
) -> list[str]:
    """Return active segment IDs with enough history for forecasting."""

    counts = events["segment_id"].value_counts()
    counts = counts[counts >= min_segment_events]
    if max_segments:
        counts = counts.head(max_segments)
    return counts.index.astype(str).tolist()


def aggregate_hourly_counts(events: pd.DataFrame, selected_segments: Iterable[str]) -> pd.DataFrame:
    """Aggregate event rows into hourly multi-output targets."""

    selected = set(selected_segments)
    events = events.loc[events["segment_id"].isin(selected)].copy()
    grouped = (
        events.groupby(["segment_id", "event_hour", "vehicle_class"], observed=True)
        .size()
        .unstack("vehicle_class", fill_value=0)
        .reset_index()
        .rename(columns={"event_hour": "target_hour"})
    )

    class_to_col = {
        "two_wheeler": "count_two_wheeler",
        "car": "count_car",
        "auto": "count_auto",
        "light_commercial": "count_light_commercial",
        "heavy": "count_heavy",
        "other": "count_other",
    }
    grouped = grouped.rename(columns=class_to_col)
    for col in TARGET_COLUMNS:
        if col not in grouped.columns:
            grouped[col] = 0
    grouped = grouped[["segment_id", "target_hour", *TARGET_COLUMNS]]
    grouped["count_total"] = grouped[TARGET_COLUMNS].sum(axis=1)
    return grouped.sort_values(["target_hour", "segment_id"]).reset_index(drop=True)


def build_segment_metadata(events: pd.DataFrame, selected_segments: Iterable[str]) -> pd.DataFrame:
    """Create static segment attributes used by the model and GeoJSON output."""

    selected = set(selected_segments)
    src = events.loc[events["segment_id"].isin(selected)].copy()
    rows = []
    for segment_id, group in src.groupby("segment_id", observed=True):
        has_grid = "lat_bin" in group.columns and "lon_bin" in group.columns
        lat_bin = int(group["lat_bin"].iloc[0]) if has_grid else 0
        lon_bin = int(group["lon_bin"].iloc[0]) if has_grid else 0
        grid_size = _infer_grid_size(group) if has_grid else 0.001
        road_class = _mode(group["road_class"], "unknown")
        geometry_wkt = _mode(group["geometry_wkt"], "") if "geometry_wkt" in group.columns else ""
        road_name = _mode(group["road_name"], "") if "road_name" in group.columns else ""
        osm_highway = _mode(group["osm_highway"], "") if "osm_highway" in group.columns else ""
        if geometry_wkt:
            try:
                centroid = wkt.loads(geometry_wkt).centroid
                lat_center = float(centroid.y)
                lon_center = float(centroid.x)
            except Exception:
                lat_center = float(group["latitude"].mean())
                lon_center = float(group["longitude"].mean())
        else:
            lat_center = float((lat_bin + 0.5) * grid_size)
            lon_center = float((lon_bin + 0.5) * grid_size)
        rows.append(
            {
                "segment_id": str(segment_id),
                "lat_center": lat_center,
                "lon_center": lon_center,
                "lat_mean": float(group["latitude"].mean()),
                "lon_mean": float(group["longitude"].mean()),
                "lat_bin": lat_bin,
                "lon_bin": lon_bin,
                "police_station": _mode(group["police_station"], "Unknown"),
                "junction_name": _mode(group["junction_name"], "No Junction"),
                "junction_bucket": _mode(group["junction_bucket"], "No Junction"),
                "road_class": road_class,
                "road_width_m": float(ROAD_WIDTH_BY_CLASS_M.get(road_class, 6.0)),
                "event_count": int(len(group)),
                "map_matching_mode": _mode(group["map_matching_mode"], "grid_fallback"),
                "representative_location": _mode(group["location"], ""),
                "road_name": road_name,
                "osm_highway": osm_highway,
                "geometry_wkt": geometry_wkt,
            }
        )
    meta = pd.DataFrame(rows)
    return meta.sort_values("event_count", ascending=False).reset_index(drop=True)


def sample_zero_rows(
    counts: pd.DataFrame,
    selected_segments: list[str],
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    zero_multiplier: float = 1.5,
    random_state: int = 42,
) -> pd.DataFrame:
    """Sample segment-hours with no recorded violations as negative examples."""

    rng = np.random.default_rng(random_state)
    hours = pd.date_range(start_hour, end_hour, freq="h")
    desired = int(max(1, len(counts) * zero_multiplier))
    positives = counts[["segment_id", "target_hour"]].drop_duplicates()

    zero_frames = []
    collected = 0
    attempts = 0
    while collected < desired and attempts < 20:
        attempts += 1
        sample_size = int((desired - collected) * 1.35) + 1000
        candidates = pd.DataFrame(
            {
                "segment_id": rng.choice(selected_segments, size=sample_size),
                "target_hour": rng.choice(hours.to_numpy(), size=sample_size),
            }
        ).drop_duplicates()
        candidates["target_hour"] = pd.to_datetime(candidates["target_hour"])
        candidates = candidates.merge(
            positives.assign(_positive=1),
            on=["segment_id", "target_hour"],
            how="left",
        )
        candidates = candidates.loc[candidates["_positive"].isna(), ["segment_id", "target_hour"]]
        zero_frames.append(candidates)
        collected = len(pd.concat(zero_frames, ignore_index=True).drop_duplicates())

    zeros = pd.concat(zero_frames, ignore_index=True).drop_duplicates()
    zeros = zeros.head(desired).copy()
    for col in TARGET_COLUMNS:
        zeros[col] = 0
    zeros["count_total"] = 0
    return zeros


def make_training_frame(
    counts: pd.DataFrame,
    selected_segments: list[str],
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    zero_multiplier: float,
    random_state: int,
) -> pd.DataFrame:
    """Combine observed event-hours with sampled zero event-hours."""

    zeros = sample_zero_rows(
        counts,
        selected_segments,
        start_hour=start_hour,
        end_hour=end_hour,
        zero_multiplier=zero_multiplier,
        random_state=random_state,
    )
    frame = pd.concat([counts, zeros], ignore_index=True)
    frame = frame.drop_duplicates(["segment_id", "target_hour"], keep="first")
    return frame.sort_values(["target_hour", "segment_id"]).reset_index(drop=True)


def build_feature_context(
    counts: pd.DataFrame,
    segment_metadata: pd.DataFrame,
    selected_segments: list[str],
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    cutoff_hour: pd.Timestamp,
    local_timezone: str,
    grid_size_deg: float,
) -> FeatureContext:
    """Create reusable statistics from historical counts."""

    train_counts = counts.loc[counts["target_hour"] < cutoff_hour].copy()
    if train_counts.empty:
        train_counts = counts.copy()
    train_hours = max(1, int((cutoff_hour - start_hour) / pd.Timedelta(hours=1)))
    total_by_segment = (
        train_counts.groupby("segment_id", observed=True)["count_total"]
        .sum()
        .rename("segment_total_events")
        .reset_index()
    )
    total_by_segment["segment_event_rate"] = total_by_segment["segment_total_events"] / train_hours
    total_by_segment["segment_rank_pct"] = total_by_segment["segment_total_events"].rank(pct=True)

    tmp = train_counts.copy()
    tmp["hour"] = tmp["target_hour"].dt.hour
    tmp["day_of_week"] = tmp["target_hour"].dt.dayofweek
    days_observed = max(1.0, train_hours / 24.0)
    weeks_observed = max(1.0, train_hours / (24.0 * 7.0))

    segment_hour_mean = (
        tmp.groupby(["segment_id", "hour"], observed=True)["count_total"]
        .sum()
        .div(days_observed)
        .rename("segment_hour_mean")
        .reset_index()
    )
    segment_dow_hour_mean = (
        tmp.groupby(["segment_id", "day_of_week", "hour"], observed=True)["count_total"]
        .sum()
        .div(weeks_observed)
        .rename("segment_dow_hour_mean")
        .reset_index()
    )
    city_hour_mean = (
        tmp.groupby("hour", observed=True)["count_total"]
        .sum()
        .div(max(1.0, days_observed * max(1, len(selected_segments))))
        .rename("city_hour_mean")
        .reset_index()
    )
    city_dow_hour_mean = (
        tmp.groupby(["day_of_week", "hour"], observed=True)["count_total"]
        .sum()
        .div(max(1.0, weeks_observed * max(1, len(selected_segments))))
        .rename("city_dow_hour_mean")
        .reset_index()
    )

    segment_metadata = segment_metadata.copy()
    segment_metadata = segment_metadata.merge(total_by_segment, on="segment_id", how="left")
    segment_metadata[["segment_total_events", "segment_event_rate", "segment_rank_pct"]] = (
        segment_metadata[["segment_total_events", "segment_event_rate", "segment_rank_pct"]]
        .fillna(0.0)
        .astype(float)
    )

    category_levels = {}
    for col in CATEGORICAL_COLUMNS:
        levels = sorted(segment_metadata[col].fillna("Unknown").astype(str).unique().tolist())
        if "Unknown" not in levels:
            levels.append("Unknown")
        category_levels[col] = levels

    stats = {
        "segment_hour_mean": segment_hour_mean,
        "segment_dow_hour_mean": segment_dow_hour_mean,
        "city_hour_mean": city_hour_mean,
        "city_dow_hour_mean": city_dow_hour_mean,
        "train_hours": train_hours,
    }
    return FeatureContext(
        start_hour=start_hour,
        end_hour=end_hour,
        local_timezone=local_timezone,
        grid_size_deg=grid_size_deg,
        history_counts=counts.copy(),
        segment_metadata=segment_metadata,
        stats=stats,
        category_levels=category_levels,
        selected_segments=selected_segments,
    )


def add_features(base_rows: pd.DataFrame, context: FeatureContext) -> pd.DataFrame:
    """Attach static, calendar, historical, and lag features to rows."""

    frame = base_rows.copy()
    frame["target_hour"] = pd.to_datetime(frame["target_hour"])
    frame = frame.merge(context.segment_metadata, on="segment_id", how="left", suffixes=("", "_meta"))
    frame["police_station"] = frame["police_station"].fillna("Unknown")
    frame["junction_bucket"] = frame["junction_bucket"].fillna("No Junction")
    frame["road_class"] = frame["road_class"].fillna("unknown")
    frame["road_width_m"] = frame["road_width_m"].fillna(6.0)
    frame["lat_center"] = frame["lat_center"].fillna(frame.get("lat_mean", 0.0)).fillna(0.0)
    frame["lon_center"] = frame["lon_center"].fillna(frame.get("lon_mean", 0.0)).fillna(0.0)

    frame["hour"] = frame["target_hour"].dt.hour
    frame["day_of_week"] = frame["target_hour"].dt.dayofweek
    frame["month"] = frame["target_hour"].dt.month
    frame["day_of_year"] = frame["target_hour"].dt.dayofyear
    frame["is_weekend"] = frame["day_of_week"].isin([5, 6]).astype(int)
    frame["is_peak"] = frame["hour"].isin(PEAK_HOURS).astype(int)
    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour"] / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour"] / 24.0)
    frame["dow_sin"] = np.sin(2 * np.pi * frame["day_of_week"] / 7.0)
    frame["dow_cos"] = np.cos(2 * np.pi * frame["day_of_week"] / 7.0)
    frame["month_sin"] = np.sin(2 * np.pi * frame["month"] / 12.0)
    frame["month_cos"] = np.cos(2 * np.pi * frame["month"] / 12.0)
    frame["days_since_start"] = (
        (frame["target_hour"] - context.start_hour) / pd.Timedelta(days=1)
    ).astype(float)

    frame = frame.merge(
        context.stats["segment_hour_mean"],
        on=["segment_id", "hour"],
        how="left",
    )
    frame = frame.merge(
        context.stats["segment_dow_hour_mean"],
        on=["segment_id", "day_of_week", "hour"],
        how="left",
    )
    frame = frame.merge(context.stats["city_hour_mean"], on="hour", how="left")
    frame = frame.merge(
        context.stats["city_dow_hour_mean"],
        on=["day_of_week", "hour"],
        how="left",
    )
    for col in [
        "segment_hour_mean",
        "segment_dow_hour_mean",
        "city_hour_mean",
        "city_dow_hour_mean",
        "segment_total_events",
        "segment_event_rate",
        "segment_rank_pct",
    ]:
        frame[col] = frame[col].fillna(0.0)

    frame = _add_lag_features(frame, context.history_counts)
    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = 0.0
    frame = apply_category_levels(frame, context.category_levels)
    return frame


def apply_category_levels(frame: pd.DataFrame, levels: dict[str, list[str]]) -> pd.DataFrame:
    """Apply stable categorical levels expected by LightGBM."""

    frame = frame.copy()
    for col, categories in levels.items():
        values = frame[col].fillna("Unknown").astype(str)
        values = values.where(values.isin(categories), "Unknown")
        frame[col] = pd.Categorical(values, categories=categories)
    return frame


def create_future_rows(context: FeatureContext, target_hour: pd.Timestamp) -> pd.DataFrame:
    """Create one prediction row per selected segment."""

    return pd.DataFrame(
        {
            "segment_id": context.selected_segments,
            "target_hour": pd.Timestamp(target_hour).floor("h"),
        }
    )


def create_location_row(context: FeatureContext, target_hour: pd.Timestamp, lat: float, lon: float) -> pd.DataFrame:
    """Create one prediction row for the known segment nearest to a coordinate."""

    meta = context.segment_metadata
    distances = haversine_km(
        lat,
        lon,
        meta["lat_center"].astype(float).to_numpy(),
        meta["lon_center"].astype(float).to_numpy(),
    )
    idx = int(np.argmin(distances))
    return pd.DataFrame(
        {
            "segment_id": [meta.iloc[idx]["segment_id"]],
            "target_hour": [pd.Timestamp(target_hour).floor("h")],
            "query_latitude": [lat],
            "query_longitude": [lon],
            "nearest_segment_distance_km": [float(distances[idx])],
        }
    )


def haversine_km(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Vectorized haversine distance."""

    radius_km = 6371.0088
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = np.radians(lats.astype(float))
    lon2 = np.radians(lons.astype(float))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * radius_km * np.arcsin(np.sqrt(a))


def infer_road_class(row: pd.Series) -> str:
    """Impute road class from available text when OSM road class is unavailable."""

    text = " ".join(
        str(row.get(col, "")) for col in ("location", "junction_name", "violation_type")
    ).upper()
    if re.search(r"RING ROAD|HIGHWAY|FLYOVER|BRIDGE|MAIN ROAD|MARKET|METRO|BUS STAND", text):
        return "primary"
    if re.search(r"JUNCTION|ROAD|CROSS|STATION|CIRCLE|AVENUE|STREET", text):
        return "secondary"
    return "residential"


def _add_lag_features(frame: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    counts = counts[["segment_id", "target_hour", "count_total", *TARGET_COLUMNS]].copy()
    lag_specs = [1, 2, 3, 24, 168]
    for lag in lag_specs:
        shifted = counts.copy()
        shifted["target_hour"] = shifted["target_hour"] + pd.Timedelta(hours=lag)
        shifted = shifted.rename(columns={"count_total": f"lag_{lag}h_total"})
        keep_cols = ["segment_id", "target_hour", f"lag_{lag}h_total"]
        if lag == 1:
            rename = {
                "count_two_wheeler": "lag_1h_two_wheeler",
                "count_car": "lag_1h_car",
                "count_auto": "lag_1h_auto",
                "count_light_commercial": "lag_1h_light_commercial",
                "count_heavy": "lag_1h_heavy",
                "count_other": "lag_1h_other",
            }
            shifted = shifted.rename(columns=rename)
            keep_cols.extend(rename.values())
        frame = frame.merge(shifted[keep_cols], on=["segment_id", "target_hour"], how="left")

    lag_cols = [col for col in frame.columns if col.startswith("lag_")]
    frame[lag_cols] = frame[lag_cols].fillna(0.0)
    return frame


def _clean_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().upper())


def _clean_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if text else "Unknown"


def _mode(values: pd.Series, default: str) -> str:
    values = values.dropna().astype(str)
    if values.empty:
        return default
    return values.value_counts().index[0]


def _infer_grid_size(group: pd.DataFrame) -> float:
    lat = group["latitude"].astype(float)
    lat_bin = group["lat_bin"].astype(float)
    diffs = (lat / lat_bin.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    if diffs.empty:
        return 0.001
    # All rows were produced by a fixed grid; round to avoid floating noise.
    return float(round(diffs.median(), 6))
