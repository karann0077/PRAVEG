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

from .config import (
    PEAK_HOURS, TARGET_COLUMNS, TARGET_TO_CLASS, VEHICLE_CLASS_WIDTH_M,
    VEHICLE_FOOTPRINT_WEIGHTS, ROAD_VULNERABILITY,
)

# ── Lightweight road-bearing cache (built once per process) ────────────────────
import json
from pathlib import Path as _Path

_SEGMENT_GEOMETRIES: dict[str, list[list[float]]] = {}
_segment_geometries_loaded = False

def _load_segment_geometries() -> None:
    """Load the precomputed 530KB JSON containing the exact curve coordinates of the roads."""
    global _SEGMENT_GEOMETRIES, _segment_geometries_loaded
    cache_path = _Path("artifacts/osm/segment_geometries.json")
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                _SEGMENT_GEOMETRIES.update(json.load(f))
        except Exception:
            pass
    _segment_geometries_loaded = True

def _get_exact_geometry(segment_id: str, lon: float, lat: float) -> list[list[float]]:
    """Return the exact curving road coordinates, or a fallback straight line."""
    global _SEGMENT_GEOMETRIES, _segment_geometries_loaded
    if not _segment_geometries_loaded:
        _load_segment_geometries()
    
    if segment_id in _SEGMENT_GEOMETRIES:
        return _SEGMENT_GEOMETRIES[segment_id]
        
    # Fallback to horizontal line if geometry is missing
    offset = 0.0009
    return [[round(lon - offset, 6), round(lat, 6)], [round(lon + offset, 6), round(lat, 6)]]

# V4: Use vehicle-specific dwell rates to compute expected concurrent vehicles.
# Heavy vehicles and light commercial stay longer (loading/unloading), 
# while bikes have a shorter dwell time.
OCCUPANCY_RATES: dict[str, float] = {
    "two_wheeler": 0.15,
    "car": 0.30,
    "auto": 0.20,
    "light_commercial": 0.40,
    "heavy": 0.50,
    "other": 0.25
}

# Gridlock only when concurrent vehicles genuinely choke the road.
# Old threshold was 3.0 m (too aggressive). New: 1.5 m leaves one lane.
GRIDLOCK_CLEARANCE_THRESHOLD_M: float = 1.5

# ── Time-of-day credibility dampener ────────────────────────────────────────
# Training data has a known artifact: enforcement officers entered violations
# in bulk during off-hours (0-5AM), causing the ML model to see artificially
# high violation counts at late night. This multiplier corrects EPS at inference
# time by damping night predictions to realistic levels without retraining.
# At true peak hours (8-20) the multiplier is 1.0 (no change).
# Source: hour distribution analysis shows 2AM has 3x records vs 6PM in training data.
NIGHT_EPS_DAMPENER: dict[int, float] = {
    0: 0.40, 1: 0.30, 2: 0.25, 3: 0.25, 4: 0.30, 5: 0.45,
    6: 0.70, 7: 0.88,
    # Hours 8-20: no dampening (multiplier=1.0, handled as default)
    21: 0.80, 22: 0.55, 23: 0.45,
}


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
        occ_rate = OCCUPANCY_RATES.get(cls, 0.25)
        concurrent_width += (
            tmp[target_col].to_numpy(dtype=float)
            * VEHICLE_CLASS_WIDTH_M.get(cls, 1.9)
            * occ_rate
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
    expected_parked_width_m = np.zeros(len(frame), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        occ_rate = OCCUPANCY_RATES.get(cls, 0.25)
        expected_parked_width_m += (
            frame[target_col].to_numpy(dtype=float)
            * VEHICLE_CLASS_WIDTH_M.get(cls, 1.9)
            * occ_rate
        )

    # expected_parked_width_m = rate-adjusted concurrent occupancy
    frame["expected_parked_width_m"] = expected_parked_width_m

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

    # ── Time-of-day dampener application ─────────────────────────────────────
    dampener = frame["hour"].map(NIGHT_EPS_DAMPENER).fillna(1.0).astype(float)

    # ── Live congestion bonus ────────────────────────────────────────────────
    if isinstance(live_congestion_multiplier, pd.Series):
        frame["live_congestion_multiplier"] = live_congestion_multiplier.clip(lower=0.1)
    else:
        frame["live_congestion_multiplier"] = max(0.1, float(live_congestion_multiplier))

    live_bonus = np.clip((frame["live_congestion_multiplier"] - 1.0) * 25.0, 0, 15)

    # ── V3: Enterprise Congestion Impact Score (CIS) ─────────────────────────
    # 1. Hotspot Probability Score (0-100)
    hotspot_prob = frame.get("hotspot_probability", pd.Series(0.0, index=frame.index))
    hotspot_score = hotspot_prob * 100.0 * dampener

    # 2. Normalized Severity Score (0-100)
    severity_sum = np.zeros(len(frame), dtype=float)
    for target_col in TARGET_COLUMNS:
        cls = TARGET_TO_CLASS[target_col]
        severity_sum += frame[target_col].to_numpy(dtype=float) * VEHICLE_FOOTPRINT_WEIGHTS.get(cls, 1.0) * 1.2
    
    norm_severity = (severity_sum / count_scale) * 50.0 
    severity_score = np.clip(norm_severity * dampener, 0, 100)

    # 3. Road Vulnerability Score (0-100)
    road_vuln_mult = frame["road_class"].map(ROAD_VULNERABILITY).fillna(0.9)
    road_vuln_mult = np.where(road_width < 7.0, road_vuln_mult + 0.5, road_vuln_mult)
    vuln_score = np.clip((road_vuln_mult - 0.7) / 1.8 * 100.0 * dampener, 0, 100)

    # Base CIS (0-100) — weights sum to 1.0
    # hotspot_score: primary signal from the trained classifier (0.55)
    # severity_score: how many/heavy violations predicted at this road (0.35)
    # vuln_score: road type tiebreaker only — no longer a floor (0.10)
    frame["eps_raw"] = (
        0.55 * hotspot_score +
        0.35 * severity_score +
        0.10 * vuln_score +
        live_bonus
    ).clip(0, 100)

    # ── FIX BUG-3: graduated gridlock penalty (not a hard jump to 90) ────────
    clearance = frame["clearance_after_predicted_load_m"]
    gridlock_boost = np.where(
        clearance < 0,
        np.maximum(frame["eps_raw"], 85.0),
        np.where(
            frame["emergency_gridlock_flag"],
            frame["eps_raw"] + (1.5 - clearance.clip(upper=1.5)) * 10,  # 0-15 point boost
            frame["eps_raw"],
        ),
    )
    frame["eps"] = gridlock_boost.clip(0, 100)
    # Round final EPS for clean display.
    frame["eps"] = frame["eps"].clip(0, 100).round(2)

    # ── Enterprise Dispatch Rule (Conformal Uncertainty) ─────────────────────
    prob_lb = frame.get("hotspot_prob_lower_bound", pd.Series(0.0, index=frame.index))
    
    # Enforce conservative dispatch: If we are not at least 85% confident that the
    # probability is >= 0.35, cap EPS at Orange Line boundary (79)
    eps_vals = frame["eps"].values
    prob_lb_vals = prob_lb.values
    cap_mask = (prob_lb_vals < 0.35) & (eps_vals >= 80)
    frame["eps"] = np.where(cap_mask, 79.0, eps_vals)

    # ── Priority bands ───────────────────────────────────────────────────────
    frame["priority_band"] = np.select(
        [frame["eps"] >= 80, frame["eps"] >= 50, frame["eps"] >= 35],
        ["Red Line", "Orange Line", "Watchlist"],
        default="Low",
    )
    
    # ── Confidence Band ──────────────────────────────────────────────────────
    prob = frame.get("hotspot_probability", pd.Series(0.0, index=frame.index))
    prob_fallback = np.maximum(prob, frame["parking_risk_0_100"] / 100.0)

    frame["confidence_band"] = np.select(
        [prob_lb > 0.6, prob_lb >= 0.35, prob_fallback > 0.4],
        ["High", "Medium", "Medium"],  # Use prob_lb for High and Medium
        default="Low",
    )

    frame["recommended_action"] = np.select(
        [
            (frame["priority_band"] == "Red Line") & (frame["confidence_band"] == "High"),
            (frame["priority_band"] == "Red Line") & (frame["confidence_band"] != "High"),
            (frame["priority_band"] == "Orange Line") & (frame["confidence_band"] == "High"),
            (frame["priority_band"] == "Orange Line") & (frame["confidence_band"] != "High"),
            (frame["priority_band"] == "Low") & (frame["live_congestion_multiplier"] >= 1.2),
        ],
        [
            "Immediate dispatch",
            "Immediate dispatch or tow readiness",
            "Preventative dispatch",
            "Monitor (Low Confidence)",
            "Stand down: congestion likely not parking-led",
        ],
        default="Monitor",
    )
    frame["recommended_force_units"] = np.ceil(frame["eps"] / 35.0).clip(0, 3).astype(int)
    frame.loc[(frame["eps"] < 40) | (frame["confidence_band"] == "Low"), "recommended_force_units"] = 0

    # ── Economic Loss Calculation (INR/hr) ───────────────────────────────────
    # We specifically calculate the loss caused by illegal parking delay.
    base_speed = frame["road_class"].map({"primary": 40, "secondary": 35, "tertiary": 25, "residential": 20}).fillna(30).astype(float)
    traffic_vol = frame["road_class"].map(ROAD_CLASS_TRAFFIC_VOLUME).fillna(500).astype(float)
    
    choke_pct = (frame["expected_parked_width_m"] / road_width) * 100.0
    choke_pct = choke_pct.clip(upper=100.0)
    speed_reduction_pct = (choke_pct * 1.3 + frame["eps"] * 0.15).clip(upper=95.0)
    
    congested_speed = base_speed * (1.0 - speed_reduction_pct / 100.0)
    congested_speed = congested_speed.clip(lower=5.0)
    
    D = 0.5  # Assumed segment length in km
    t_normal_hr = D / base_speed
    t_congested_hr = D / congested_speed
    delay_per_vehicle_hr = t_congested_hr - t_normal_hr
    
    # Blended Cost per vehicle-hour based on Bengaluru traffic split:
    # 50% 2W (VoT+VOC=120), 30% Car (350), 10% Auto (180), 5% LCV (300), 5% Heavy (700)
    # Blended = 0.5*120 + 0.3*350 + 0.1*180 + 0.05*300 + 0.05*700 = 233 INR/hr
    blended_cost_per_hr = 233.0
    
    frame["economic_loss_inr"] = traffic_vol * delay_per_vehicle_hr * blended_cost_per_hr
    frame["economic_loss_inr"] = frame["economic_loss_inr"].round(0)


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
    road_class = str(row.get("road_class", "unknown")).lower()
    eps = float(row.get("eps", 0.0))

    # ── FIX: expected_parked_width_m is NOT exported to GeoJSON.
    # Derive it from clearance_m (which IS in the GeoJSON):
    #   clearance_m = road_width - parked_width  →  parked_width = road_width - clearance_m
    parked_width = float(row.get("expected_parked_width_m", 0.0))
    if parked_width == 0.0:
        clearance_m = float(row.get("clearance_m", road_width))
        parked_width = max(0.0, road_width - clearance_m)

    # If both are missing, fall back to traffic_interruption_0_100 to estimate blockage
    if parked_width == 0.0:
        interruption_pct = float(row.get("traffic_interruption_0_100", 0.0))
        parked_width = road_width * (interruption_pct / 100.0) * 0.5  # conservative estimate

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
        tomtom_geom_str = str(row.get("tomtom_geometry", "") or "")

        properties = {
            "segment_id": str(row["segment_id"]),
            "target_hour": str(row["target_hour"]),
            "police_station": str(row.get("police_station", "Unknown")) if pd.notna(row.get("police_station")) else "Unknown",
            "junction_name": str(row.get("junction_name", "No Junction")) if pd.notna(row.get("junction_name")) else "No Junction",
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
            "road_name": str(row.get("road_name", "")) if pd.notna(row.get("road_name")) else "",
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
            "confidence_band": str(row.get("confidence_band", "Low")),
            "hotspot_probability": float(row.get("hotspot_probability", 0.0)),
            "economic_loss_inr": float(row.get("economic_loss_inr", 0.0)),
            # ── FIX BUG-4: include geometry_wkt for kinematics ripple engine ──
            "geometry_wkt": geometry_wkt_val,
        }

        # ── Resolve geometry ─────────────────────────────────────────────────
        geometry = None
        
        if geometry_wkt_val and geometry_wkt_val != "nan":
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
            if str(row.get("map_matching_mode", "")) == "osm_overpass_nearest_road":
                import logging
                logging.getLogger("scoring").warning(f"Skipping geometry for {properties['segment_id']} - missing WKT")
                continue
            
            # ── Fallback for missing geometry (grid dots) ────────────────────────
            geometry = {
                "type": "Point",
                "coordinates": [lon, lat],
            }

        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }
        features.append(feature)

    payload = {"type": "FeatureCollection", "features": features}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
