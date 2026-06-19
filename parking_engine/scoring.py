"""Traffic interruption and enforcement-priority scoring.

FIX LOG (2026-06-18):
  BUG-1  FIXED: clearance calculation now uses OCCUPANCY_RATE (0.25) to convert
         hourly violation count to simultaneous on-road count.  The old code
         treated predicted_total (violations/hour) as simultaneously parked
         vehicles – a residential road with 27 violations/hour would compute
         27 × 1.9 m = 51.3 m width on a 6 m road and fire the gridlock flag
         for every single segment.

  BUG-2  FIXED: calibration saturation.  parking_risk and traffic_interruption
         both saturated to ~100 whenever predicted_total > 3 × count_p95.
         Added a soft-scaling fallback so the 0-100 range is used properly.

  BUG-3  FIXED: EPS formula produced only 0-30 or 90 (bimodal).  The
         emergency_gridlock_flag was applying np.maximum(eps, 90) BEFORE the
         final clip, compressing the entire orange / watchlist range.  The flag
         now only triggers for truly extreme cases (clearance < 1.5 m after
         occupancy correction) and uses a graduated penalty instead of a hard
         jump to 90.

  BUG-4  FIXED: geometry_wkt now written to GeoJSON properties so kinematics
         ripple engine can do spatial intersection queries.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import wkt

from .config import PEAK_HOURS, TARGET_COLUMNS, TARGET_TO_CLASS, VEHICLE_CLASS_WIDTH_M

# ── NEW: occupancy rate ──────────────────────────────────────────────────────
# The model predicts *violations per hour* (an arrival rate).
# On average ~25 % of those violations are simultaneously on-road at any
# moment (assuming ~15-minute average dwell time: 15/60 = 0.25).
# This converts the Poisson arrival rate to an *expected concurrent count*
# before the physical road-width check.
OCCUPANCY_RATE: float = 0.25

# Gridlock only when concurrent vehicles genuinely choke the road.
# Old threshold was 3.0 m (too aggressive). New: 1.5 m leaves one lane.
GRIDLOCK_CLEARANCE_THRESHOLD_M: float = 1.5


def peak_multiplier(hour: int, day_of_week: int) -> float:
    """Rush-hour multiplier – kept conservative to avoid saturation."""
    if hour in PEAK_HOURS:
        return 1.8          # was 2.5 – too aggressive, caused interruption saturation
    if hour >= 23 or hour <= 5:
        return 0.3
    return 1.0


def calibrate_scoring(counts: pd.DataFrame, segment_metadata: pd.DataFrame) -> dict[str, float]:
    """Build percentile scales used to convert raw scores into 0-100 EPS values."""
    if counts.empty:
        return {"count_p95": 1.0, "interruption_p95": 1.0}
    tmp = counts.merge(segment_metadata[["segment_id", "road_width_m"]], on="segment_id", how="left")
    tmp["road_width_m"] = tmp["road_width_m"].fillna(6.0)

    # ── FIX: apply occupancy rate when computing training-time interruption ──
    concurrent_width = np.zeros(len(tmp), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        concurrent_width += (
            tmp[target_col].to_numpy(dtype=float)
            * VEHICLE_CLASS_WIDTH_M[cls]
            * OCCUPANCY_RATE
        )
    tmp["raw_interruption"] = (concurrent_width / tmp["road_width_m"].to_numpy(dtype=float)) ** 2

    count_p95 = float(max(1.0, np.percentile(tmp["count_total"].to_numpy(dtype=float), 95)))
    interruption_p95 = float(
        max(0.05, np.percentile(tmp["raw_interruption"].to_numpy(dtype=float), 95))
    )
    return {"count_p95": count_p95, "interruption_p95": interruption_p95}


def score_predictions(
    predictions: pd.DataFrame,
    calibration: dict[str, float],
    live_congestion_multiplier: float | pd.Series = 1.0,
) -> pd.DataFrame:
    """Compute bottleneck severity, EPS, and enforcement recommendations.

    Changes vs old version
    ----------------------
    1. OCCUPANCY_RATE applied before road-width clearance check.
    2. Gridlock threshold lowered to 1.5 m; penalty is graduated not binary.
    3. EPS formula re-balanced: 50/40/10 split gives proper orange / watchlist
       bands instead of bimodal 0 or 90.
    4. count_p95 / interruption_p95 floor raised to avoid saturation.
    """
    frame = predictions.copy()
    for col in TARGET_COLUMNS:
        frame[col] = frame[col].clip(lower=0.0)
    frame["predicted_total"] = frame[TARGET_COLUMNS].sum(axis=1)

    # ── Physical width using CONCURRENT (occupancy-corrected) count ─────────
    total_width_rate = np.zeros(len(frame), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        total_width_rate += frame[target_col].to_numpy(dtype=float) * VEHICLE_CLASS_WIDTH_M[cls]

    # expected_parked_width_m = rate-adjusted concurrent occupancy
    frame["expected_parked_width_m"] = total_width_rate * OCCUPANCY_RATE

    frame["peak_multiplier"] = [
        peak_multiplier(int(hour), int(dow))
        for hour, dow in zip(frame["hour"], frame["day_of_week"], strict=False)
    ]
    road_width = frame["road_width_m"].fillna(6.0).astype(float).clip(lower=3.0)

    frame["interruption_raw"] = (
        (frame["expected_parked_width_m"].astype(float) / road_width) ** 2
    ) * frame["peak_multiplier"].astype(float)

    frame["clearance_after_predicted_load_m"] = road_width - frame["expected_parked_width_m"]

    # ── FIX BUG-1: gridlock flag uses corrected clearance + stricter threshold ─
    frame["emergency_gridlock_flag"] = (
        frame["clearance_after_predicted_load_m"] < GRIDLOCK_CLEARANCE_THRESHOLD_M
    )

    # ── FIX BUG-2: use true calibration, scale for proper gradient ──────────
    count_scale = max(1.0, float(calibration.get("count_p95", 5.0))) / 2.0
    interruption_scale = max(0.01, float(calibration.get("interruption_p95", 0.05))) / 2.0

    frame["parking_risk_0_100"] = 100.0 * (
        1.0 - np.exp(-frame["predicted_total"] / count_scale)
    )
    frame["traffic_interruption_0_100"] = 100.0 * (
        1.0 - np.exp(-frame["interruption_raw"] / interruption_scale)
    )


    # ── Live congestion bonus ────────────────────────────────────────────────
    if isinstance(live_congestion_multiplier, pd.Series):
        frame["live_congestion_multiplier"] = live_congestion_multiplier.clip(lower=0.1)
    else:
        frame["live_congestion_multiplier"] = max(0.1, float(live_congestion_multiplier))

    live_bonus = np.clip((frame["live_congestion_multiplier"] - 1.0) * 25.0, 0, 15)

    # ── FIX BUG-3: re-balanced EPS formula (50/40/10) ───────────────────────
    # Old: 0.55 * parking + 0.35 * interruption  => max = 90 always
    # New: 0.50 * parking + 0.40 * interruption + live_bonus
    #      max without gridlock = 0.50*100 + 0.40*100 + 15 = 105 -> clip 100
    #      This gives proper gradient across the 0-100 range.
    frame["eps_raw"] = (
        0.50 * frame["parking_risk_0_100"]
        + 0.40 * frame["traffic_interruption_0_100"]
        + live_bonus
    ).clip(0, 100)

    # ── FIX BUG-3: graduated gridlock penalty (not a hard jump to 90) ────────
    # Segments near true gridlock (clearance < 0 m) get eps boosted to min 85.
    # Segments with clearance between 0-1.5 m get a graduated boost.
    clearance = frame["clearance_after_predicted_load_m"]
    gridlock_boost = np.where(
        clearance < 0,
        np.maximum(frame["eps_raw"], 85.0),            # true blockage → min 85
        np.where(
            frame["emergency_gridlock_flag"],
            frame["eps_raw"] + (1.5 - clearance.clip(upper=1.5)) * 10,  # 0-15 point boost
            frame["eps_raw"],
        ),
    )
    frame["eps"] = gridlock_boost.clip(0, 100)

    # ── Priority bands ───────────────────────────────────────────────────────
    frame["priority_band"] = np.select(
        [frame["eps"] >= 85, frame["eps"] >= 60, frame["eps"] >= 40],
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


# ── Traffic volume estimates by road class (vehicles/hour) ───────────────────
ROAD_CLASS_TRAFFIC_VOLUME = {
    "motorway": 5000, "trunk": 5000, "primary": 3000,
    "secondary": 1500, "tertiary": 500, "residential": 200,
    "living_street": 100, "unknown": 500,
}


def compute_resolution_impact(row: dict) -> dict:
    """Compute before/after enforcement impact for a single segment.

    Returns realistic traffic flow improvement metrics when illegal
    parking is resolved, not just zeroed-out values.
    """
    road_width = float(row.get("road_width_m", 6.0))
    parked_width = float(row.get("expected_parked_width_m", 0.0))
    eps = float(row.get("eps", 0.0))
    road_class = str(row.get("road_class", "unknown")).lower()
    live_mult = float(row.get("live_congestion_multiplier", 1.0))

    # Before enforcement
    clearance_before = max(0.0, road_width - parked_width)
    lanes_before = max(0, int(clearance_before / 3.0))
    choke_pct = min(100.0, (parked_width / max(road_width, 1.0)) * 100.0)

    # Estimate speed reduction from road choke (empirical model)
    # When 30% of road is blocked, speed drops ~40%. At 60%, speed drops ~80%.
    speed_reduction_pct = min(95.0, choke_pct * 1.3 + eps * 0.15)
    base_speed_kmh = {"primary": 40, "secondary": 35, "tertiary": 25, "residential": 20}.get(road_class, 30)
    speed_before = max(5.0, base_speed_kmh * (1.0 - speed_reduction_pct / 100.0))

    # After enforcement — full road restored
    clearance_after = road_width
    lanes_after = max(1, int(road_width / 3.0))
    speed_after = base_speed_kmh  # free-flow speed restored

    # Traffic volume and economic impact
    traffic_vol = ROAD_CLASS_TRAFFIC_VOLUME.get(road_class, 500)
    cost_per_delayed_vehicle = 50  # ₹50 per vehicle-hour delay (fuel + time)
    econ_loss_before = (speed_reduction_pct / 100.0) * traffic_vol * cost_per_delayed_vehicle
    econ_loss_after = 0.0  # enforcement clears the blockage
    econ_savings = econ_loss_before - econ_loss_after

    # Cascade effect: how many downstream segments benefit
    # Estimate based on road class connectivity
    cascade_segments = {"primary": 8, "secondary": 5, "tertiary": 3, "residential": 1}.get(road_class, 2)

    return {
        "before": {
            "clearance_m": round(clearance_before, 1),
            "lanes_available": lanes_before,
            "choke_percent": round(choke_pct, 0),
            "speed_kmh": round(speed_before, 0),
            "economic_loss_per_hr": round(econ_loss_before, 0),
            "eps": round(eps, 1),
        },
        "after": {
            "clearance_m": round(clearance_after, 1),
            "lanes_available": lanes_after,
            "choke_percent": 0,
            "speed_kmh": round(speed_after, 0),
            "economic_loss_per_hr": 0,
            "eps": 0,
        },
        "improvement": {
            "speed_recovery_kmh": round(speed_after - speed_before, 0),
            "speed_recovery_pct": round((speed_after - speed_before) / max(1, speed_before) * 100, 0),
            "lanes_restored": lanes_after - lanes_before,
            "economic_savings_per_hr": round(econ_savings, 0),
            "cascade_segments_helped": cascade_segments,
        },
    }


def compute_enforcement_priority(row: dict) -> dict:
    """Compute weighted enforcement priority score for dispatch ranking.

    Factors:
    - EPS severity (40%): how bad is the violation
    - Economic impact (25%): how much money is being lost
    - Accessibility (20%): can a tow truck reach this (clearance > 2.5m)?
    - Cascade potential (15%): resolving this helps downstream roads
    """
    eps = float(row.get("eps", 0))
    road_class = str(row.get("road_class", "unknown")).lower()
    clearance = float(row.get("clearance_after_predicted_load_m", 6.0))

    # Severity component (0-100)
    severity = min(100, eps)

    # Economic component (0-100) based on road class traffic volume
    traffic_vol = ROAD_CLASS_TRAFFIC_VOLUME.get(road_class, 500)
    econ_score = min(100.0, (traffic_vol / 5000.0) * 100.0 * (eps / 100.0))

    # Accessibility (0-100): tow trucks need ~2.5m clearance
    if clearance > 4.0:
        access_score = 100.0  # easy access
    elif clearance > 2.5:
        access_score = 70.0   # tight but possible
    elif clearance > 1.5:
        access_score = 40.0   # very difficult
    else:
        access_score = 15.0   # near-impossible, foot patrol only

    # Cascade potential (0-100)
    cascade_map = {"primary": 90, "secondary": 65, "tertiary": 40, "residential": 20}
    cascade_score = cascade_map.get(road_class, 30)

    # Weighted priority
    priority = (0.40 * severity + 0.25 * econ_score + 0.20 * access_score + 0.15 * cascade_score)
    priority = min(100.0, max(0.0, priority))

    # Human-readable urgency label
    if priority >= 75:
        urgency = "Immediate"
    elif priority >= 50:
        urgency = "Within 30 min"
    else:
        urgency = "Can Wait"

    return {
        "priority_score": round(priority, 1),
        "urgency": urgency,
        "components": {
            "severity": round(severity, 1),
            "economic_impact": round(econ_score, 1),
            "accessibility": round(access_score, 1),
            "cascade_potential": round(cascade_score, 1),
        },
    }

def write_geojson(predictions: pd.DataFrame, path: str | Path, grid_size_deg: float) -> None:
    """Write scored predictions as GeoJSON LineString features.

    FIX BUG-4: geometry_wkt is now included in properties so kinematics.py
    ripple engine can do spatial intersection queries on the output.
    """
    features = []
    half = grid_size_deg * 0.42
    for _, row in predictions.iterrows():
        lon = float(row.get("lon_center", row.get("lon_mean", 0.0)))
        lat = float(row.get("lat_center", row.get("lat_mean", 0.0)))
        geometry_wkt_val = str(row.get("geometry_wkt", "") or "")

        properties = {
            "segment_id": str(row["segment_id"]),
            "target_hour": str(row["target_hour"]),
            "police_station": str(row.get("police_station", "Unknown")),
            "junction_name": str(row.get("junction_name", "No Junction")),
            "road_class": str(row.get("road_class", "unknown")),
            "road_width_m": float(row.get("road_width_m", 6.0)),
            "predicted_total": float(row.get("predicted_total", 0.0)),
            "traffic_interruption_0_100": float(row.get("traffic_interruption_0_100", 0.0)),
            "parking_risk_0_100": float(row.get("parking_risk_0_100", 0.0)),
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
            "live_congestion_multiplier": float(row.get("live_congestion_multiplier", 1.0)),
            "clearance_m": float(row.get("clearance_after_predicted_load_m", 0.0)),
            "emergency_gridlock_flag": bool(row.get("emergency_gridlock_flag", False)),
            # ── FIX BUG-4: include geometry_wkt for kinematics ripple engine ──
            "geometry_wkt": geometry_wkt_val,
        }

        # ── Resolve geometry ─────────────────────────────────────────────────
        geometry = None
        if geometry_wkt_val:
            try:
                shapely_geom = wkt.loads(geometry_wkt_val)
                if shapely_geom.geom_type == "LineString":
                    geometry = {
                        "type": "LineString",
                        "coordinates": [[float(x), float(y)] for x, y in shapely_geom.coords],
                    }
                elif shapely_geom.geom_type == "MultiLineString":
                    # flatten to first line for DeckGL compatibility
                    coords = list(shapely_geom.geoms[0].coords)
                    geometry = {
                        "type": "LineString",
                        "coordinates": [[float(x), float(y)] for x, y in coords],
                    }
            except Exception:
                geometry = None

        if geometry is None:
            geometry = {
                "type": "LineString",
                "coordinates": [[lon - half, lat], [lon + half, lat]],
            }

        features.append({"type": "Feature", "properties": properties, "geometry": geometry})

    payload = {"type": "FeatureCollection", "features": features}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
