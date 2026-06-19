"""Shared configuration for the parking enforcement engine.

V3 UPGRADE (Enterprise Prediction Engine):
  - Added VIOLATION_SEVERITY_WEIGHTS for severity-weighted targets.
  - Added VEHICLE_FOOTPRINT_WEIGHTS for vehicle-impact scoring.
  - Added VALIDATION_STATUS_WEIGHTS for label quality weighting.
  - Added BENGALURU_HOLIDAYS and BENGALURU_FESTIVALS for temporal features.
  - Added micro-window definitions for Bengaluru-specific temporal patterns.
  - Added 30+ new feature columns for POI gravity, enforcement bias,
    recurrence, severity, and temporal enrichment.
"""

from __future__ import annotations
from pathlib import Path

# ── Canonical Model Path ─────────────────────────────────────────────────────
# Used uniformly by train.py, server.py, run_batch.py, and live_traffic_daemon.py
MODEL_DIR = Path("artifacts/parking_model")

TARGET_COLUMNS = [
    "count_two_wheeler",
    "count_car",
    "count_auto",
    "count_light_commercial",
    "count_heavy",
    "count_other",
]

TARGET_TO_CLASS = {
    "count_two_wheeler": "two_wheeler",
    "count_car": "car",
    "count_auto": "auto",
    "count_light_commercial": "light_commercial",
    "count_heavy": "heavy",
    "count_other": "other",
}

VEHICLE_CLASS_WIDTH_M = {
    "two_wheeler": 0.8,
    "car": 1.9,
    "auto": 1.3,
    "light_commercial": 2.3,
    "heavy": 2.6,
    "other": 1.9,
}

ROAD_WIDTH_BY_CLASS_M = {
    "motorway": 15.0,
    "trunk": 15.0,
    "primary": 12.0,
    "secondary": 9.0,
    "tertiary": 7.5,
    "residential": 6.0,
    "living_street": 6.0,
    "unknown": 6.0,
}

VEHICLE_TYPE_TO_CLASS = {
    "SCOOTER": "two_wheeler",
    "MOTOR CYCLE": "two_wheeler",
    "MOTORCYCLE": "two_wheeler",
    "MOPED": "two_wheeler",
    "CAR": "car",
    "MAXI-CAB": "car",
    "MAXI CAB": "car",
    "JEEP": "car",
    "PASSENGER AUTO": "auto",
    "GOODS AUTO": "auto",
    "LGV": "light_commercial",
    "VAN": "light_commercial",
    "TEMPO": "light_commercial",
    "PRIVATE BUS": "heavy",
    "BUS (BMTC/KSRTC)": "heavy",
    "TOURIST BUS": "heavy",
    "SCHOOL VEHICLE": "heavy",
    "FACTORY BUS": "heavy",
    "HGV": "heavy",
    "LORRY/GOODS VEHICLE": "heavy",
    "LORRY": "heavy",
    "TANKER": "heavy",
    "TRACTOR": "heavy",
    "TRAILER": "heavy",
    "OTHERS": "other",
}

# ── V3: Violation severity weights ──────────────────────────────────────────
# Higher weight = more harmful to traffic flow. Used in severity_weighted_count
# target so the model learns to prioritize high-impact violations.
VIOLATION_SEVERITY_WEIGHTS: dict[str, float] = {
    "DOUBLE PARKING": 2.0,
    "PARKING IN A MAIN ROAD": 1.8,
    "PARKING NEAR ROAD CROSSING": 1.8,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 1.8,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 1.6,
    "PARKING ON FOOTPATH": 1.4,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 1.4,
    "PARKING OTHER THAN BUS STOP": 1.3,
    "NO PARKING": 1.2,
    "WRONG PARKING": 1.0,
}
DEFAULT_VIOLATION_SEVERITY = 1.0

# ── V3: Vehicle footprint weights ───────────────────────────────────────────
# A bus blocking a narrow road is much worse than a scooter. Used to scale
# severity_weighted_count by vehicle impact on road capacity.
VEHICLE_FOOTPRINT_WEIGHTS: dict[str, float] = {
    "heavy": 2.5,
    "light_commercial": 1.8,
    "car": 1.5,
    "auto": 1.2,
    "two_wheeler": 0.8,
    "other": 1.0,
}

# ── V3: Validation status weights ──────────────────────────────────────────
# Treat approved violations as full signal, unvalidated as weak-positive (we
# don't know if they're real), rejected and duplicates are excluded.
VALIDATION_STATUS_WEIGHTS: dict[str, float] = {
    "approved": 1.0,
    "created1": 0.5,      # unvalidated — weak positive
    "processing": 0.5,    # in-progress — weak positive
    # NaN (missing) handled separately: treated as 0.5
}
VALIDATION_EXCLUDE_STATUSES: set[str] = {"rejected", "duplicate"}
VALIDATION_MISSING_WEIGHT: float = 0.5

# ── V3: Road vulnerability multipliers ─────────────────────────────────────
# Narrow or important roads suffer more from illegal parking.
ROAD_VULNERABILITY: dict[str, float] = {
    "motorway": 2.0,
    "trunk": 1.8,
    "primary": 1.5,
    "secondary": 1.2,
    "tertiary": 1.0,
    "residential": 0.8,
    "living_street": 0.7,
    "unknown": 0.9,
}

PEAK_HOURS = {8, 9, 10, 17, 18, 19, 20}

# Weekday peaks: office rush (Mon-Fri)
WEEKDAY_PEAK_HOURS = {8, 9, 10, 17, 18, 19, 20}
# Weekend peaks: markets, temples, shopping (Sat-Sun) — shifted later morning, longer evening
WEEKEND_PEAK_HOURS = {10, 11, 12, 13, 17, 18, 19, 20, 21}


# Human-readable time buckets for tree model to split on
HOUR_BUCKET_MAP = {
    0: "late_night", 1: "late_night", 2: "late_night", 3: "late_night",
    4: "early_morning", 5: "early_morning",
    6: "morning", 7: "morning",
    8: "morning_rush", 9: "morning_rush", 10: "morning_rush",
    11: "midday", 12: "midday", 13: "midday", 14: "midday",
    15: "afternoon", 16: "afternoon",
    17: "evening_rush", 18: "evening_rush", 19: "evening_rush", 20: "evening_rush",
    21: "night", 22: "night", 23: "late_night",
}

# ── V3: Bengaluru-specific temporal calendar ────────────────────────────────
# Karnataka gazetted holidays and Bengaluru-relevant festivals during our
# dataset date range (Nov 2023 – Apr 2024). Extend as data grows.
BENGALURU_HOLIDAYS: set[str] = {
    # Gazetted holidays within dataset range (2023-11 to 2024-04)
    "2023-11-14",   # Kannada Rajyotsava (observed)
    "2023-11-27",   # Guru Nanak Jayanti
    "2023-12-25",   # Christmas
    "2024-01-15",   # Sankranti / Pongal
    "2024-01-26",   # Republic Day
    "2024-03-25",   # Holi
    "2024-03-29",   # Good Friday
    "2024-04-11",   # Eid-ul-Fitr (approx)
    "2024-04-14",   # Dr. Ambedkar Jayanti
    # Common recurring patterns (model will learn the signal)
}

BENGALURU_FESTIVALS: set[str] = {
    # Major multi-day festivals/events causing extra traffic
    "2023-11-12", "2023-11-13",   # Diwali weekend
    "2023-12-31",                  # New Year's Eve
    "2024-01-01",                  # New Year
    "2024-01-14", "2024-01-15", "2024-01-16",  # Sankranti/Pongal
    "2024-03-24", "2024-03-25",   # Holi
}

# ── V3: Micro-window definitions (hour ranges for Bengaluru activity) ──────
# These are area-dependent interaction features: school_pickup × school_density etc.
MICRO_WINDOWS: dict[str, dict] = {
    "school_dropoff": {"hours": {7, 8, 9}, "weekdays_only": True},
    "school_pickup":  {"hours": {14, 15, 16}, "weekdays_only": True},
    "lunch_market":   {"hours": {12, 13, 14}, "weekdays_only": False},
    "office_commute_am": {"hours": {8, 9, 10}, "weekdays_only": True},
    "office_commute_pm": {"hours": {17, 18, 19}, "weekdays_only": True},
    "shopping_evening": {"hours": {17, 18, 19, 20}, "weekdays_only": False},
    "nightlife_peak": {"hours": {21, 22, 23, 0}, "weekdays_only": False},
    "late_night_enforcement": {"hours": {0, 1, 2, 3}, "weekdays_only": False},
}

# ── V3: Hotspot binary threshold ───────────────────────────────────────────
# A cell-hour is considered a "hotspot" if severity_weighted_count exceeds this.
# Tuned to roughly the 80th percentile of non-zero observations.
HOTSPOT_SEVERITY_THRESHOLD: float = 3.0

FEATURE_COLUMNS = [
    # ── Identity / static ──
    "segment_id",
    "police_station",
    "junction_bucket",
    "road_class",
    "lat_center",
    "lon_center",
    "road_width_m",
    # ── Temporal ──
    "hour",
    "day_of_week",
    "month",
    "day_of_year",
    "is_weekend",
    "is_peak",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "month_sin",
    "month_cos",
    "day_of_year_norm",
    "is_weekday_peak",
    "is_weekend_peak",
    "hour_bucket",
    # ── V3: Enhanced temporal ──
    "is_holiday",
    "is_festival",
    "is_first_week_of_month",
    "is_month_end",
    "is_school_dropoff",
    "is_school_pickup",
    "is_lunch_market",
    "is_office_commute_am",
    "is_office_commute_pm",
    "is_shopping_evening",
    "is_nightlife_peak",
    # ── Historical recurrence ──
    "segment_total_events",
    "segment_event_rate",
    "segment_rank_pct",
    "segment_hour_mean",
    "segment_dow_hour_mean",
    "city_hour_mean",
    "city_dow_hour_mean",
    # ── V3: Enhanced recurrence ──
    "hawkes_decay_intensity",
    "neighbor_spillover_score",
    "segment_severity_mean",
    "segment_dominant_vehicle_footprint",
    # ── Lag features ──
    "lag_1h_total",
    "lag_2h_total",
    "lag_3h_total",
    "lag_24h_total",
    "lag_168h_total",
    "lag_1h_two_wheeler",
    "lag_1h_car",
    "lag_1h_auto",
    "lag_1h_light_commercial",
    "lag_1h_heavy",
    "lag_1h_other",
    # ── Weather ──
    "rainfall_mm",
    "is_raining",
    "is_underpass_or_bridge",
    "rain_shelter_bottleneck",
    # ── Parking supply ──
    "dist_to_legal_parking_m",
    "legal_parking_capacity",
    "overflow_risk_index",
    # ── Spatial context (POI proximity) ──
    "dist_to_metro_m",
    "dist_to_commercial_m",
    # ── V3: Expanded POI features ──
    "dist_to_bus_stop_m",
    "dist_to_school_m",
    "dist_to_hospital_m",
    "dist_to_market_m",
    "dist_to_restaurant_m",
    "dist_to_worship_m",
    "poi_count_200m",
    "poi_count_500m",
    "poi_gravity_score",
    # ── V3: Enforcement bias ──
    "station_enforcement_volume",
    "station_approval_rate",
    "station_event_rate",
    # ── Event context ──
    "distance_to_active_event_m",
    "event_impact_score",
    "active_event_count",
    # ── V3: Road vulnerability ──
    "road_vulnerability",
]

CATEGORICAL_COLUMNS = ["segment_id", "police_station", "junction_bucket", "road_class", "hour_bucket"]

