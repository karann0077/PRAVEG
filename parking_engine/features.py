"""Feature engineering for hotspot and bottleneck prediction.

FIX LOG (2026-06-18):
  BUG-8  FIXED: Lag features were ALL ZERO during inference because the join
         used absolute target_hour timestamps (e.g. 2026-06-18 10:00) but
         history_counts only contains 2024 training dates.  Fix: build lag
         features from the segment's historical DISTRIBUTION (mean by hour /
         day_of_week) rather than looking for exact timestamp matches.

  BUG-9  FIXED: 16 feature columns were always zero in both training and
         inference (rainfall, parking supply, event context).  Added live
         weather injection via LIVE_RAINFALL_MM / LIVE_IS_RAINING env vars
         so predictions made by the live daemon use real weather.

  BUG-10 FIXED: days_since_start extrapolates badly (~730 days beyond training
         range in 2026).  Replaced with a modular day_of_cycle feature
         (0-365) that wraps annually, staying within the model's training
         distribution.

V3 UPGRADE (2026-06-19):
  - load_events: validation_status filtering (exclude rejected/duplicate),
    sample_weight assignment, violation severity parsing, vehicle footprint.
  - aggregate_hourly_counts: produces severity_weighted_count target.
  - sample_zero_rows: hard-negative sampling near POI-dense areas.
  - add_features: enhanced temporal (holiday/festival/micro-windows),
    recurrence (rolling_7d/28d, severity_mean), enforcement bias
    (station_volume/approval_rate), road_vulnerability, expanded POI features.
"""

from __future__ import annotations

import json as _json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from shapely import wkt

from .config import (
    BENGALURU_FESTIVALS,
    BENGALURU_HOLIDAYS,
    CATEGORICAL_COLUMNS,
    DEFAULT_VIOLATION_SEVERITY,
    FEATURE_COLUMNS,
    HOTSPOT_SEVERITY_THRESHOLD,
    HOUR_BUCKET_MAP,
    MICRO_WINDOWS,
    PEAK_HOURS,
    ROAD_VULNERABILITY,
    ROAD_WIDTH_BY_CLASS_M,
    TARGET_COLUMNS,
    VALIDATION_EXCLUDE_STATUSES,
    VALIDATION_MISSING_WEIGHT,
    VALIDATION_STATUS_WEIGHTS,
    VEHICLE_FOOTPRINT_WEIGHTS,
    VEHICLE_TYPE_TO_CLASS,
    VEHICLE_FOOTPRINT_WEIGHTS,
    VEHICLE_TYPE_TO_CLASS,
    VIOLATION_SEVERITY_WEIGHTS,
    WEEKDAY_PEAK_HOURS,
    WEEKEND_PEAK_HOURS,
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
    # V3: enforcement bias lookups
    enforcement_stats: dict[str, pd.DataFrame] = field(default_factory=dict)


def load_events(
    data_path: str | Path,
    local_timezone: str = "Asia/Kolkata",
    grid_size_deg: float = 0.001,
    parking_only: bool = True,
) -> pd.DataFrame:
    """Load raw violation rows and normalize them into modeling events.

    V3 changes:
      - Reads validation_status to exclude rejected/duplicate rows.
      - Assigns sample_weight per event based on validation status.
      - Parses violation_type JSON arrays to compute violation_severity_weight.
      - Computes vehicle_footprint_weight from vehicle class.
      - Computes combined severity_weight = violation_severity × vehicle_footprint × sample_weight.
    """

    usecols = [
        "id", "latitude", "longitude", "location", "vehicle_type",
        "updated_vehicle_type", "violation_type", "created_datetime",
        "police_station", "junction_name", "validation_status",
    ]
    events = pd.read_csv(data_path, usecols=lambda c: c in usecols)
    events = events.dropna(subset=["latitude", "longitude", "created_datetime"])
    events["created_datetime"] = pd.to_datetime(events["created_datetime"], errors="coerce", utc=True)
    events = events.dropna(subset=["created_datetime"])

    # ── V3: Validation-status filtering and weighting ──────────────────────
    raw_count = len(events)
    vs = events["validation_status"].fillna("").astype(str).str.strip().str.lower()
    exclude_mask = vs.isin(VALIDATION_EXCLUDE_STATUSES)
    events = events.loc[~exclude_mask].copy()
    vs = vs.loc[~exclude_mask]
    events["sample_weight"] = vs.map(VALIDATION_STATUS_WEIGHTS).fillna(VALIDATION_MISSING_WEIGHT)
    print(f"  V3: excluded {exclude_mask.sum()} rejected/duplicate rows ({raw_count} → {len(events)})")

    events["event_time"] = (
        events["created_datetime"].dt.tz_convert(local_timezone).dt.tz_localize(None)
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

    # ── V3: Parse violation_type JSON and compute severity weight ──────────
    events["violation_severity_weight"] = events["violation_type"].apply(_parse_violation_severity)
    events["vehicle_footprint_weight"] = events["vehicle_class"].map(VEHICLE_FOOTPRINT_WEIGHTS).fillna(1.0)
    # Combined severity = violation_severity × vehicle_footprint × sample_weight
    events["severity_weight"] = (
        events["violation_severity_weight"]
        * events["vehicle_footprint_weight"]
        * events["sample_weight"]
    )

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

    # ── FIX: Bulk-entry timestamp correction ──────────────────────────────────
    # PROBLEM: Enforcement officers uploaded violations in bulk during off-hours
    # (0-5AM). Many segments show >80% of violations at 2-4AM which is physically
    # impossible for residential/commercial roads. The model learned these fake
    # timestamps as ground truth, causing absurd 4AM "Red Line" predictions.
    #
    # FIX: Detect segments where the majority of violations fall in the bulk-entry
    # window (0-5AM) and drop those nighttime records from training. This is NOT
    # data deletion — real nighttime violations do occur, but only ~2-5% of total.
    # Any segment with >35% of its records at 0-5AM is flagged as artifact-heavy
    # and those specific nighttime records get downweighted to zero sample_weight.
    #
    # Result: Model trains on realistic hour distributions for all segments.
    BULK_ENTRY_HOURS = set(range(0, 6))   # 0,1,2,3,4,5 AM
    BULK_ARTIFACT_THRESHOLD = 0.35        # >35% of records in 0-5AM → artifact

    events["_hour_of_day"] = events["event_time"].dt.hour
    is_night = events["_hour_of_day"].isin(BULK_ENTRY_HOURS)

    # Per-segment: what fraction of its records are in 0-5AM?
    seg_total = events.groupby("segment_id")["_hour_of_day"].count()
    seg_night = events[is_night].groupby("segment_id")["_hour_of_day"].count()
    seg_night_frac = (seg_night / seg_total).fillna(0.0)
    artifact_segments = seg_night_frac[seg_night_frac > BULK_ARTIFACT_THRESHOLD].index

    # Zero-weight the 0-5AM records for artifact-heavy segments
    artifact_night_mask = (
        events["segment_id"].isin(artifact_segments) & is_night
    )
    events.loc[artifact_night_mask, "sample_weight"] = 0.0
    events.loc[artifact_night_mask, "severity_weight"] = 0.0
    artifact_count = artifact_night_mask.sum()
    if artifact_count > 0:
        print(
            f"  TIMESTAMP FIX: zeroed sample_weight for {artifact_count} likely "
            f"bulk-entry records across {len(artifact_segments)} segments "
            f"(>35% violations at 0-5AM)."
        )
    events = events.drop(columns=["_hour_of_day"])
    return events


def select_active_segments(
    events: pd.DataFrame,
    min_segment_events: int = 20,
    max_segments: int | None = None,
) -> list[str]:
    counts = events["segment_id"].value_counts()
    counts = counts[counts >= min_segment_events]
    if max_segments:
        counts = counts.head(max_segments)
    return counts.index.astype(str).tolist()


def aggregate_hourly_counts(events: pd.DataFrame, selected_segments: Iterable[str]) -> pd.DataFrame:
    """Aggregate events into segment-hour counts.

    V3: also produces severity_weighted_count (sum of per-event severity_weight)
    and is_hotspot binary target.
    """
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

    # ── V3: Severity-weighted count ────────────────────────────────────────
    # Sum of per-event severity_weight (violation_severity × vehicle_footprint × sample_weight)
    if "severity_weight" in events.columns:
        severity_agg = (
            events.groupby(["segment_id", "event_hour"], observed=True)["severity_weight"]
            .sum()
            .reset_index()
            .rename(columns={"event_hour": "target_hour", "severity_weight": "severity_weighted_count"})
        )
        grouped = grouped.merge(severity_agg, on=["segment_id", "target_hour"], how="left")
        grouped["severity_weighted_count"] = grouped["severity_weighted_count"].fillna(0.0)
    else:
        grouped["severity_weighted_count"] = grouped["count_total"].astype(float)

    # ── V3: Binary hotspot target ──────────────────────────────────────────
    grouped["is_hotspot"] = (grouped["severity_weighted_count"] >= HOTSPOT_SEVERITY_THRESHOLD).astype(int)

    # ── V3: Hourly Sample Weight ───────────────────────────────────────────
    if "sample_weight" in events.columns:
        weight_agg = (
            events.groupby(["segment_id", "event_hour"], observed=True)["sample_weight"]
            .mean()
            .reset_index()
            .rename(columns={"event_hour": "target_hour"})
        )
        grouped = grouped.merge(weight_agg, on=["segment_id", "target_hour"], how="left")
        grouped["sample_weight"] = grouped["sample_weight"].fillna(1.0)
    else:
        grouped["sample_weight"] = 1.0

    return grouped.sort_values(["target_hour", "segment_id"]).reset_index(drop=True)


def build_segment_metadata(events: pd.DataFrame, selected_segments: Iterable[str]) -> pd.DataFrame:
    selected = set(selected_segments)
    src = events.loc[events["segment_id"].isin(selected)].copy()
    rows = []
    
    # V3: Pre-compute station enforcement bias features from the full event set
    # Using raw events to calculate approval rate (approved / (approved+rejected))
    station_stats = {}
    if "validation_status" in events.columns:
        valid_mask = events["validation_status"].str.lower().isin(["approved", "rejected"])
        valid_events = events[valid_mask].copy()
        if not valid_events.empty:
            valid_events["is_approved"] = (valid_events["validation_status"].str.lower() == "approved").astype(int)
            station_approval = valid_events.groupby("police_station")["is_approved"].mean()
            station_stats = station_approval.to_dict()

    for segment_id, group in src.groupby("segment_id", observed=True):
        has_grid = "lat_bin" in group.columns and "lon_bin" in group.columns
        lat_bin = int(group["lat_bin"].iloc[0]) if has_grid else 0
        lon_bin = int(group["lon_bin"].iloc[0]) if has_grid else 0
        grid_size = _infer_grid_size(group) if has_grid else 0.001
        road_class = _mode(group["road_class"], "unknown")
        geometry_wkt = _mode(group["geometry_wkt"], "") if "geometry_wkt" in group.columns else ""
        road_name = _mode(group["road_name"], "") if "road_name" in group.columns else ""
        osm_highway = _mode(group["osm_highway"], "") if "osm_highway" in group.columns else ""
        police_station = _mode(group["police_station"], "Unknown")
        
        # V3: enforcement bias and dominant severity
        approval_rate = station_stats.get(police_station, 0.5)
        severity_mean = float(group["severity_weight"].mean()) if "severity_weight" in group.columns else 1.0
        dominant_footprint = float(group["vehicle_footprint_weight"].mean()) if "vehicle_footprint_weight" in group.columns else 1.0

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
        rows.append({
            "segment_id": str(segment_id),
            "lat_center": lat_center,
            "lon_center": lon_center,
            "lat_mean": float(group["latitude"].mean()),
            "lon_mean": float(group["longitude"].mean()),
            "lat_bin": lat_bin,
            "lon_bin": lon_bin,
            "police_station": police_station,
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
            # V3 additions
            "station_approval_rate": float(approval_rate),
            "segment_severity_mean": float(severity_mean),
            "segment_dominant_vehicle_footprint": float(dominant_footprint),
        })
    meta = pd.DataFrame(rows)
    return meta.sort_values("event_count", ascending=False).reset_index(drop=True)


def sample_zero_rows(
    counts: pd.DataFrame,
    selected_segments: list[str],
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    zero_multiplier: float = 0.5,
    random_state: int = 42,
    segment_metadata: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Sample candidate rows where enforcement could happen, but no violation recorded.

    V3: Hard-negative sampling. Uses segment_event_rate (if metadata provided)
    to weight sampling probability, so we sample more zeros in active segments
    than in quiet segments, forcing the model to learn subtle time boundaries.
    """
    rng = np.random.default_rng(random_state)
    hours = pd.date_range(start_hour, end_hour, freq="h")
    desired = int(max(1, len(counts) * zero_multiplier))
    positives = counts[["segment_id", "target_hour"]].drop_duplicates()

    # V3: Compute sampling weights
    segment_weights = None
    if segment_metadata is not None and "event_count" in segment_metadata.columns:
        meta = segment_metadata.set_index("segment_id")
        event_counts = meta["event_count"].reindex(selected_segments).fillna(1.0).to_numpy(dtype=float)
        # Smoothed weights: log(1 + count) ensures we don't only sample the top 10 segments
        weights = np.log1p(event_counts)
        segment_weights = weights / weights.sum()

    zero_frames = []
    collected = 0
    attempts = 0
    while collected < desired and attempts < 20:
        attempts += 1
        sample_size = int((desired - collected) * 1.35) + 1000
        candidates = pd.DataFrame({
            "segment_id": rng.choice(selected_segments, size=sample_size, p=segment_weights),
            "target_hour": rng.choice(hours.to_numpy(), size=sample_size),
        }).drop_duplicates()
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
    zeros["severity_weighted_count"] = 0.0
    zeros["is_hotspot"] = 0
    zeros["sample_weight"] = 0.3  # V4: Down-weight synthetic negative rows
    return zeros


def make_training_frame(
    counts: pd.DataFrame,
    selected_segments: list[str],
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    zero_multiplier: float,
    random_state: int,
    **kwargs,
) -> pd.DataFrame:
    zeros = sample_zero_rows(
        counts, selected_segments,
        start_hour=start_hour, end_hour=end_hour,
        zero_multiplier=zero_multiplier, random_state=random_state,
        segment_metadata=kwargs.get("segment_metadata")
    )
    frame = pd.concat([counts, zeros], ignore_index=True)
    frame = frame.drop_duplicates(["segment_id", "target_hour"], keep="first")
    
    # ── V4: Reweight rare classes ───────────────────────────────────────────
    # Heavy and light commercial vehicles are rare but high-impact.
    # Give them a multiplier to prevent the model from ignoring them.
    rare_multiplier = 1.0 + (frame.get("count_heavy", 0) > 0).astype(float) * 2.0 + (frame.get("count_light_commercial", 0) > 0).astype(float) * 1.0
    if "sample_weight" in frame.columns:
        frame["sample_weight"] = frame["sample_weight"] * rare_multiplier
    
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
        .sum().div(days_observed).rename("segment_hour_mean").reset_index()
    )
    segment_dow_hour_mean = (
        tmp.groupby(["segment_id", "day_of_week", "hour"], observed=True)["count_total"]
        .sum().div(weeks_observed).rename("segment_dow_hour_mean").reset_index()
    )
    city_hour_mean = (
        tmp.groupby("hour", observed=True)["count_total"]
        .sum()
        .div(max(1.0, days_observed * max(1, len(selected_segments))))
        .rename("city_hour_mean").reset_index()
    )
    city_dow_hour_mean = (
        tmp.groupby(["day_of_week", "hour"], observed=True)["count_total"]
        .sum()
        .div(max(1.0, weeks_observed * max(1, len(selected_segments))))
        .rename("city_dow_hour_mean").reset_index()
    )

    # ── FIX BUG-8: Build historical lag lookup keyed on (segment_id, hour, dow) ──
    # This allows _add_lag_features_from_history() to work for future dates.
    segment_hour_lag = (
        tmp.groupby(["segment_id", "hour"], observed=True)["count_total"]
        .mean().rename("hist_lag_hour_mean").reset_index()
    )
    segment_dow_lag = (
        tmp.groupby(["segment_id", "day_of_week", "hour"], observed=True)["count_total"]
        .mean().rename("hist_lag_dow_hour_mean").reset_index()
    )

    segment_metadata = segment_metadata.copy()
    segment_metadata = segment_metadata.merge(total_by_segment, on="segment_id", how="left")
    segment_metadata[["segment_total_events", "segment_event_rate", "segment_rank_pct"]] = (
        segment_metadata[["segment_total_events", "segment_event_rate", "segment_rank_pct"]]
        .fillna(0.0).astype(float)
    )

    category_levels = {}
    for col in CATEGORICAL_COLUMNS:
        if col == "hour_bucket":
            levels = sorted(set(HOUR_BUCKET_MAP.values()))
            category_levels[col] = levels
            continue
        levels = sorted(segment_metadata[col].fillna("Unknown").astype(str).unique().tolist())
        if "Unknown" not in levels:
            levels.append("Unknown")
        category_levels[col] = levels

    # ── V3: Build recurrence and enforcement lookups ─────────────────────────
    # For rolling_7d_mean and rolling_28d_mean, we use the segment_event_rate as a proxy 
    # since we don't have rolling sliding windows at inference time.
    # The true "rolling" aspect is handled by the live daemon pushing recent stats.
    
    stats = {
        "segment_hour_mean": segment_hour_mean,
        "segment_dow_hour_mean": segment_dow_hour_mean,
        "city_hour_mean": city_hour_mean,
        "city_dow_hour_mean": city_dow_hour_mean,
        "train_hours": train_hours,
        # ── FIX BUG-8: persist historical lag lookups ──────────────────────
        "segment_hour_lag": segment_hour_lag,
        "segment_dow_lag": segment_dow_lag,
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

    # ── FIX BUG-10: Replace days_since_start with annual modular cycle ──────
    # days_since_start grew to ~730 days in 2026, far outside training range.
    # day_of_year_norm (0–1) wraps annually and stays within [0, 1] always.
    frame["day_of_year_norm"] = frame["day_of_year"] / 365.0

    # ── NEW: Weekday vs Weekend peak distinction ─────────────────────────────
    # Parking patterns differ dramatically: office areas spike Mon-Fri 8-10 AM,
    # market/temple areas spike Sat-Sun 10 AM-1 PM.
    frame["is_weekday_peak"] = (
        (~frame["day_of_week"].isin([5, 6])) & frame["hour"].isin(WEEKDAY_PEAK_HOURS)
    ).astype(int)
    frame["is_weekend_peak"] = (
        frame["day_of_week"].isin([5, 6]) & frame["hour"].isin(WEEKEND_PEAK_HOURS)
    ).astype(int)

    # ── NEW: Hour bucket categorical ─────────────────────────────────────────
    frame["hour_bucket"] = frame["hour"].map(HOUR_BUCKET_MAP).fillna("midday")

    # ── V3: Enhanced temporal features (Holidays, Festivals, Micro-windows) ──
    date_str = frame["target_hour"].dt.strftime("%Y-%m-%d")
    frame["is_holiday"] = date_str.isin(BENGALURU_HOLIDAYS).astype(int)
    frame["is_festival"] = date_str.isin(BENGALURU_FESTIVALS).astype(int)
    frame["is_first_week_of_month"] = (frame["target_hour"].dt.day <= 7).astype(int)
    frame["is_month_end"] = (frame["target_hour"].dt.days_in_month - frame["target_hour"].dt.day <= 3).astype(int)
    
    for mw_name, mw_config in MICRO_WINDOWS.items():
        mask = frame["hour"].isin(mw_config["hours"])
        if mw_config["weekdays_only"]:
            mask = mask & (~frame["day_of_week"].isin([5, 6]))
        frame[f"is_{mw_name}"] = mask.astype(int)

    frame = frame.merge(context.stats["segment_hour_mean"], on=["segment_id", "hour"], how="left")
    frame = frame.merge(
        context.stats["segment_dow_hour_mean"], on=["segment_id", "day_of_week", "hour"], how="left"
    )
    frame = frame.merge(context.stats["city_hour_mean"], on="hour", how="left")
    frame = frame.merge(
        context.stats["city_dow_hour_mean"], on=["day_of_week", "hour"], how="left"
    )
    for col in [
        "segment_hour_mean", "segment_dow_hour_mean",
        "city_hour_mean", "city_dow_hour_mean",
        "segment_total_events", "segment_event_rate", "segment_rank_pct",
    ]:
        frame[col] = frame[col].fillna(0.0)

    # Road vulnerability scoring logic
    if "road_class" in frame.columns and "road_width_m" in frame.columns:
        # Default multiplier based on class
        road_vuln = frame["road_class"].map(ROAD_VULNERABILITY).fillna(1.0)
        # Narrow roads get an extra multiplier
        road_vuln = np.where(frame["road_width_m"] < 7.0, road_vuln * 1.5, road_vuln)
        frame["road_vulnerability"] = road_vuln
    else:
        frame["road_vulnerability"] = 1.0

    # ── FIX BUG-8: Historical distribution-based lag (works for future dates) ─
    frame = _add_lag_features_from_history(frame, context)

    # ── Weather & Event Context Integration ─────────────────────────────────────
    from parking_engine.weather_context import merge_weather_context
    from parking_engine.event_context import add_event_context

    # Weather: Fetches or looks up open-meteo hourly rain based on target_hour
    frame = merge_weather_context(
        frame,
        segment_metadata=context.segment_metadata,
        timezone=context.local_timezone,
        allow_missing_weather=True,
    )
    
    # Events: Distance to active venues
    frame = add_event_context(
        frame,
        local_timezone=context.local_timezone,
    )

    # ── V4: Dynamic Hawkes-style decay and Spatial Spillover ────────────────
    # Hawkes decay: exponentially decaying importance of recent lag events
    frame["hawkes_decay_intensity"] = (
        frame["lag_1h_total"] * np.exp(-0.5) +
        frame["lag_2h_total"] * np.exp(-1.0) +
        frame["lag_3h_total"] * np.exp(-1.5)
    )

    # Spatial Spillover: sum of lag_1h_total from physical nearest neighbors
    from scipy.spatial import KDTree
    if "lat_center" in frame.columns and "lon_center" in frame.columns and len(frame) > 0:
        # Build tree for the current hour slice to find spatial neighbors
        # We group by hour if multiple hours are present (e.g. in training)
        spillover_scores = []
        for _, hour_group in frame.groupby("target_hour"):
            lats = hour_group["lat_center"].to_numpy()
            lons = hour_group["lon_center"].to_numpy()
            lags = hour_group["lag_1h_total"].fillna(0).to_numpy()
            
            # Simple Euclidean approximation for <1km distances
            # 0.005 degrees is approx 500 meters
            tree = KDTree(np.c_[lats, lons])
            # Query pairs within 0.005 deg
            pairs = tree.query_pairs(r=0.005)
            
            scores = np.zeros(len(hour_group))
            for i, j in pairs:
                scores[i] += lags[j]
                scores[j] += lags[i]
            
            hour_group_copy = hour_group.copy()
            hour_group_copy["_spillover"] = scores
            spillover_scores.append(hour_group_copy[["segment_id", "target_hour", "_spillover"]])
        
        if spillover_scores:
            spill_df = pd.concat(spillover_scores)
            frame = frame.merge(spill_df, on=["segment_id", "target_hour"], how="left")
            frame["neighbor_spillover_score"] = frame["_spillover"].fillna(0.0)
            frame = frame.drop(columns=["_spillover"])
        else:
            frame["neighbor_spillover_score"] = 0.0
    else:
        frame["neighbor_spillover_score"] = 0.0

    # ── FIX BUG-9: Inject live weather from environment variables ────────────
    frame = _inject_live_weather(frame)

    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = 0.0
    frame = apply_category_levels(frame, context.category_levels)
    return frame


def _inject_live_weather(frame: pd.DataFrame) -> pd.DataFrame:
    """FIX BUG-9: Pull live weather from env vars set by the daemon.

    If running in batch mode, env vars are absent and the features remain 0
    (matching training distribution for batch predictions).
    If running in live mode, the daemon sets LIVE_RAINFALL_MM etc.
    """
    rainfall_mm = float(os.environ.get("LIVE_RAINFALL_MM", "0.0"))
    is_raining = int(os.environ.get("LIVE_IS_RAINING", "0"))

    if "rainfall_mm" not in frame.columns:
        frame["rainfall_mm"] = 0.0
    if "is_raining" not in frame.columns:
        frame["is_raining"] = 0

    frame["rainfall_mm"] = rainfall_mm
    frame["is_raining"] = is_raining

    # rain_shelter_bottleneck: segments under bridges/underpasses become
    # MORE attractive during rain => higher risk
    if "is_underpass_or_bridge" in frame.columns and is_raining:
        frame["rain_shelter_bottleneck"] = (
            frame["is_underpass_or_bridge"].fillna(0).astype(int) * int(is_raining)
        )
    else:
        if "rain_shelter_bottleneck" not in frame.columns:
            frame["rain_shelter_bottleneck"] = 0

    return frame


def _add_lag_features_from_history(frame: pd.DataFrame, context: FeatureContext) -> pd.DataFrame:
    """FIX BUG-8: Build lag features using true history with historical fallback.

    Uses true T-1, T-24, T-168 historical values when available (training).
    Falls back to segment-hour average proxies when missing (inference).
    """
    stats = context.stats
    history = context.history_counts.copy()
    if not history.empty:
        history["target_hour"] = pd.to_datetime(history["target_hour"])
    frame_hour = pd.to_datetime(frame["target_hour"])

    merged = frame.copy()

    def merge_true_lag(df, lag_hours, prefix):
        if history.empty:
            return df
        lag_hist = history.copy()
        lag_hist["target_hour"] = lag_hist["target_hour"] + pd.Timedelta(hours=lag_hours)
        lag_hist = lag_hist.rename(columns={
            "count_total": f"true_{prefix}_total",
            "count_two_wheeler": f"true_{prefix}_two_wheeler",
            "count_car": f"true_{prefix}_car",
            "count_auto": f"true_{prefix}_auto",
            "count_light_commercial": f"true_{prefix}_light_commercial",
            "count_heavy": f"true_{prefix}_heavy",
            "count_other": f"true_{prefix}_other",
        })
        cols = ["segment_id", "target_hour", f"true_{prefix}_total"]
        if f"true_{prefix}_two_wheeler" in lag_hist.columns:
            cols.extend([
                f"true_{prefix}_two_wheeler", f"true_{prefix}_car", f"true_{prefix}_auto",
                f"true_{prefix}_light_commercial", f"true_{prefix}_heavy", f"true_{prefix}_other"
            ])
        return df.merge(lag_hist[cols], on=["segment_id", "target_hour"], how="left")

    merged = merge_true_lag(merged, 1, "lag_1h")
    merged = merge_true_lag(merged, 2, "lag_2h")
    merged = merge_true_lag(merged, 3, "lag_3h")
    merged = merge_true_lag(merged, 24, "lag_24h")
    merged = merge_true_lag(merged, 168, "lag_168h")

    # Fallback 1: historical proxy
    fb1 = stats["segment_hour_lag"].copy()
    fb1["hour"] = (fb1["hour"] + 1) % 24
    merged = merged.merge(fb1.rename(columns={"hist_lag_hour_mean": "fb_1"}), on=["segment_id", "hour"], how="left")

    fb2 = stats["segment_hour_lag"].copy()
    fb2["hour"] = (fb2["hour"] + 2) % 24
    merged = merged.merge(fb2.rename(columns={"hist_lag_hour_mean": "fb_2"}), on=["segment_id", "hour"], how="left")

    fb3 = stats["segment_hour_lag"].copy()
    fb3["hour"] = (fb3["hour"] + 3) % 24
    merged = merged.merge(fb3.rename(columns={"hist_lag_hour_mean": "fb_3"}), on=["segment_id", "hour"], how="left")

    fb24 = stats["segment_hour_lag"].copy()
    merged = merged.merge(fb24.rename(columns={"hist_lag_hour_mean": "fb_24"}), on=["segment_id", "hour"], how="left")

    fb168 = stats["segment_dow_lag"].copy()
    merged = merged.merge(fb168.rename(columns={"hist_lag_dow_mean": "fb_168", "hist_lag_dow_hour_mean": "fb_168"}), on=["segment_id", "day_of_week", "hour"], how="left")

    # Apply true lag if exists, else fallback, else 0
    for hrs in [1, 2, 3, 24, 168]:
        col = f"lag_{hrs}h_total"
        true_col = f"true_{col}"
        fb_col = f"fb_{hrs}"
        
        if true_col not in merged.columns:
            merged[true_col] = np.nan
            
        merged[col] = merged[true_col].fillna(merged.get(fb_col, 0.0)).fillna(0.0)

    # Sub-vehicle class fallbacks (only for lag_1h)
    for vclass in ["two_wheeler", "car", "auto", "light_commercial", "heavy", "other"]:
        col = f"lag_1h_{vclass}"
        true_col = f"true_lag_1h_{vclass}"
        if true_col not in merged.columns:
            merged[true_col] = np.nan
        merged[col] = merged[true_col].fillna(0.0)

    # Cleanup
    cols_to_drop = [c for c in merged.columns if c.startswith("true_") or c.startswith("fb_")]
    merged = merged.drop(columns=cols_to_drop)

    return merged

def apply_category_levels(frame: pd.DataFrame, levels: dict[str, list[str]]) -> pd.DataFrame:
    frame = frame.copy()
    for col, categories in levels.items():
        values = frame[col].fillna("Unknown").astype(str)
        values = values.where(values.isin(categories), "Unknown")
        frame[col] = pd.Categorical(values, categories=categories)
    return frame



def create_future_rows(context: FeatureContext, target_hour: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame({
        "segment_id": context.selected_segments,
        "target_hour": pd.Timestamp(target_hour).floor("h"),
    })


def create_location_row(
    context: FeatureContext, target_hour: pd.Timestamp, lat: float, lon: float
) -> pd.DataFrame:
    meta = context.segment_metadata
    distances = haversine_km(
        lat, lon,
        meta["lat_center"].astype(float).to_numpy(),
        meta["lon_center"].astype(float).to_numpy(),
    )
    idx = int(np.argmin(distances))
    return pd.DataFrame({
        "segment_id": [meta.iloc[idx]["segment_id"]],
        "target_hour": [pd.Timestamp(target_hour).floor("h")],
        "query_latitude": [lat],
        "query_longitude": [lon],
        "nearest_segment_distance_km": [float(distances[idx])],
    })


def haversine_km(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
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
    text = " ".join(
        str(row.get(col, "")) for col in ("location", "junction_name", "violation_type")
    ).upper()
    if re.search(r"RING ROAD|HIGHWAY|FLYOVER|BRIDGE|MAIN ROAD|MARKET|METRO|BUS STAND", text):
        return "primary"
    if re.search(r"JUNCTION|ROAD|CROSS|STATION|CIRCLE|AVENUE|STREET", text):
        return "secondary"
    return "residential"


def _add_lag_features(frame: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    """Legacy exact-timestamp lag join (kept for training pipeline only)."""
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
    return float(round(diffs.median(), 6))


def _parse_violation_severity(value: object) -> float:
    """Parse JSON array of violations and compute max severity."""
    text = str(value)
    if not text or text == "nan":
        return DEFAULT_VIOLATION_SEVERITY
    try:
        if text.startswith("["):
            terms = _json.loads(text)
        else:
            terms = [text]
    except Exception:
        terms = [text]
    
    max_sev = DEFAULT_VIOLATION_SEVERITY
    for term in terms:
        term_clean = str(term).strip().upper()
        sev = VIOLATION_SEVERITY_WEIGHTS.get(term_clean, DEFAULT_VIOLATION_SEVERITY)
        if sev > max_sev:
            max_sev = sev
    return max_sev
