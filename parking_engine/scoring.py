"""Traffic interruption and enforcement-priority scoring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import wkt

from .config import PEAK_HOURS, TARGET_COLUMNS, TARGET_TO_CLASS, VEHICLE_CLASS_WIDTH_M


def peak_multiplier(hour: int, day_of_week: int) -> float:
    """Rush-hour multiplier from the architecture document."""

    if hour in PEAK_HOURS:
        return 2.5
    if hour >= 23 or hour <= 5:
        return 0.2
    return 1.0


def calibrate_scoring(counts: pd.DataFrame, segment_metadata: pd.DataFrame) -> dict[str, float]:
    """Build percentile scales used to convert raw scores into 0-100 EPS values."""

    if counts.empty:
        return {"count_p95": 1.0, "interruption_p95": 1.0}
    tmp = counts.merge(segment_metadata[["segment_id", "road_width_m"]], on="segment_id", how="left")
    tmp["road_width_m"] = tmp["road_width_m"].fillna(6.0)
    total_width = np.zeros(len(tmp), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        total_width += tmp[target_col].to_numpy(dtype=float) * VEHICLE_CLASS_WIDTH_M[cls]
    tmp["raw_interruption"] = (total_width / tmp["road_width_m"].to_numpy(dtype=float)) ** 2
    count_p95 = float(max(1.0, np.percentile(tmp["count_total"].to_numpy(dtype=float), 95)))
    interruption_p95 = float(max(0.05, np.percentile(tmp["raw_interruption"].to_numpy(dtype=float), 95)))
    return {"count_p95": count_p95, "interruption_p95": interruption_p95}


def score_predictions(
    predictions: pd.DataFrame,
    calibration: dict[str, float],
    live_congestion_multiplier: float | pd.Series = 1.0,
) -> pd.DataFrame:
    """Compute bottleneck severity, EPS, and enforcement recommendations."""

    frame = predictions.copy()
    for col in TARGET_COLUMNS:
        frame[col] = frame[col].clip(lower=0.0)
    frame["predicted_total"] = frame[TARGET_COLUMNS].sum(axis=1)

    total_width = np.zeros(len(frame), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        total_width += frame[target_col].to_numpy(dtype=float) * VEHICLE_CLASS_WIDTH_M[cls]
    frame["expected_parked_width_m"] = total_width
    frame["peak_multiplier"] = [
        peak_multiplier(int(hour), int(dow))
        for hour, dow in zip(frame["hour"], frame["day_of_week"], strict=False)
    ]
    road_width = frame["road_width_m"].fillna(6.0).astype(float).clip(lower=3.0)
    frame["interruption_raw"] = (
        (frame["expected_parked_width_m"].astype(float) / road_width) ** 2
    ) * frame["peak_multiplier"].astype(float)
    frame["clearance_after_predicted_load_m"] = road_width - frame["expected_parked_width_m"]
    frame["emergency_gridlock_flag"] = frame["clearance_after_predicted_load_m"] < 3.0

    count_scale = max(1.0, float(calibration.get("count_p95", 1.0)))
    interruption_scale = max(0.05, float(calibration.get("interruption_p95", 0.05)))
    frame["parking_risk_0_100"] = 100.0 * (1.0 - np.exp(-frame["predicted_total"] / count_scale))
    frame["traffic_interruption_0_100"] = 100.0 * (
        1.0 - np.exp(-frame["interruption_raw"] / interruption_scale)
    )
    if isinstance(live_congestion_multiplier, pd.Series):
        frame["live_congestion_multiplier"] = live_congestion_multiplier.clip(lower=0.1)
    else:
        frame["live_congestion_multiplier"] = max(0.1, float(live_congestion_multiplier))
    live_bonus = np.clip((frame["live_congestion_multiplier"] - 1.0) * 25.0, 0, 20)
    frame["eps"] = (
        0.55 * frame["parking_risk_0_100"]
        + 0.35 * frame["traffic_interruption_0_100"]
        + live_bonus
    ).clip(0, 100)
    frame.loc[frame["emergency_gridlock_flag"], "eps"] = np.maximum(
        frame.loc[frame["emergency_gridlock_flag"], "eps"], 90.0
    )
    frame["priority_band"] = np.select(
        [frame["eps"] >= 90, frame["eps"] >= 60, frame["eps"] >= 40],
        ["Red Line", "Orange Line", "Watchlist"],
        default="Low",
    )
    frame["recommended_action"] = np.select(
        [
            (frame["priority_band"] == "Red Line") & (frame["live_congestion_multiplier"] >= 1.2),
            frame["priority_band"] == "Red Line",
            frame["priority_band"] == "Orange Line",
            (frame["priority_band"] == "Low") & (frame["live_congestion_multiplier"] >= 1.2),
        ],
        [
            "Immediate dispatch",
            "Immediate dispatch or tow readiness",
            "Preventative dispatch",
            "Stand down: congestion likely not parking-led",
        ],
        default="Monitor",
    )
    frame["recommended_force_units"] = np.ceil(frame["eps"] / 35.0).clip(0, 3).astype(int)
    frame.loc[frame["eps"] < 40, "recommended_force_units"] = 0
    return frame.sort_values(["eps", "predicted_total"], ascending=False).reset_index(drop=True)


def write_geojson(predictions: pd.DataFrame, path: str | Path, grid_size_deg: float) -> None:
    """Write scored predictions as GeoJSON LineString features."""

    features = []
    half = grid_size_deg * 0.42
    for _, row in predictions.iterrows():
        lon = float(row.get("lon_center", row.get("lon_mean", 0.0)))
        lat = float(row.get("lat_center", row.get("lat_mean", 0.0)))
        properties = {
            "segment_id": str(row["segment_id"]),
            "target_hour": str(row["target_hour"]),
            "police_station": str(row.get("police_station", "Unknown")),
            "junction_name": str(row.get("junction_name", "No Junction")),
            "road_class": str(row.get("road_class", "unknown")),
            "road_width_m": float(row.get("road_width_m", 6.0)),
            "predicted_total": float(row.get("predicted_total", 0.0)),
            "traffic_interruption_0_100": float(row.get("traffic_interruption_0_100", 0.0)),
            "eps": float(row.get("eps", 0.0)),
            "priority_band": str(row.get("priority_band", "Low")),
            "recommended_action": str(row.get("recommended_action", "Monitor")),
            "recommended_force_units": int(row.get("recommended_force_units", 0)),
            "map_matching_mode": str(row.get("map_matching_mode", "grid_fallback")),
            "road_name": str(row.get("road_name", "")),
            "osm_highway": str(row.get("osm_highway", "")),
            "count_two_wheeler": float(row.get("count_two_wheeler", 0.0)),
            "count_car": float(row.get("count_car", 0.0)),
            "count_auto": float(row.get("count_auto", 0.0)),
            "count_light_commercial": float(row.get("count_light_commercial", 0.0)),
            "count_heavy": float(row.get("count_heavy", 0.0)),
            "count_other": float(row.get("count_other", 0.0)),
        }
        geometry_wkt = row.get("geometry_wkt", "")
        geometry = None
        if isinstance(geometry_wkt, str) and geometry_wkt:
            try:
                shapely_geom = wkt.loads(geometry_wkt)
                if shapely_geom.geom_type == "LineString":
                    geometry = {
                        "type": "LineString",
                        "coordinates": [[float(x), float(y)] for x, y in shapely_geom.coords],
                    }
            except Exception:
                geometry = None
        if geometry is None:
            geometry = {
                "type": "LineString",
                "coordinates": [[lon - half, lat], [lon + half, lat]],
            }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            }
        )
    payload = {"type": "FeatureCollection", "features": features}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
