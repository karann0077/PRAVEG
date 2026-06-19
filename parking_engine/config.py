"""Shared configuration for the parking enforcement engine."""

from __future__ import annotations

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

FEATURE_COLUMNS = [
    "segment_id",
    "police_station",
    "junction_bucket",
    "road_class",
    "lat_center",
    "lon_center",
    "road_width_m",
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
    "segment_total_events",
    "segment_event_rate",
    "segment_rank_pct",
    "segment_hour_mean",
    "segment_dow_hour_mean",
    "city_hour_mean",
    "city_dow_hour_mean",
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
    "rainfall_mm",
    "is_raining",
    "is_underpass_or_bridge",
    "rain_shelter_bottleneck",
    "dist_to_legal_parking_m",
    "legal_parking_capacity",
    "overflow_risk_index",
    "dist_to_metro_m",
    "dist_to_commercial_m",
    "distance_to_active_event_m",
    "event_impact_score",
    "active_event_count",
]

CATEGORICAL_COLUMNS = ["segment_id", "police_station", "junction_bucket", "road_class", "hour_bucket"]

