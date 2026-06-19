"""CLI for training the parking hotspot forecasting engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .features import (
    aggregate_hourly_counts,
    build_feature_context,
    build_segment_metadata,
    load_events,
    make_training_frame,
    select_active_segments,
)
from .modeling import save_bundle, train_model
from .osm_roads import fetch_osm_roads_for_events, match_events_to_osm_roads
from .scoring import calibrate_scoring

# V2 context modules — integrate real data into previously-zero feature columns
try:
    from .weather_context import fetch_bengaluru_hourly_weather, merge_weather_context
    HAS_WEATHER = True
except Exception:
    HAS_WEATHER = False

try:
    from .spatial_context import build_spatial_context_features
    HAS_SPATIAL = True
except Exception:
    HAS_SPATIAL = False

try:
    from .parking_supply import compute_legal_parking_overflow
    HAS_PARKING = True
except Exception:
    HAS_PARKING = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        default="dataset/jan to may police violation_anonymized791b166.csv",
        help="Path to the violation CSV.",
    )
    parser.add_argument("--out", default="artifacts/parking_model", help="Artifact directory.")
    parser.add_argument("--timezone", default="Asia/Kolkata", help="Local timezone for calendar features.")
    parser.add_argument("--grid-size-deg", type=float, default=0.001, help="Fallback grid size in degrees.")
    parser.add_argument("--min-segment-events", type=int, default=20, help="Minimum events per segment.")
    parser.add_argument("--max-segments", type=int, default=None, help="Optional cap on active segments.")
    parser.add_argument("--zero-multiplier", type=float, default=1.5, help="Zero rows per positive row.")
    parser.add_argument("--test-days", type=int, default=21, help="Trailing days for temporal test split.")
    parser.add_argument("--n-estimators", type=int, default=350, help="LightGBM trees per output.")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--include-non-parking", action="store_true", help="Do not filter to parking terms.")
    parser.add_argument(
        "--use-osm-roads",
        action="store_true",
        help="Fetch public OpenStreetMap road ways and snap events to true road LineStrings.",
    )
    parser.add_argument(
        "--osm-cache",
        default="artifacts/osm/bengaluru_roads.json",
        help="Cache path for Overpass road data.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading events from {data_path}")
    events = load_events(
        data_path,
        local_timezone=args.timezone,
        grid_size_deg=args.grid_size_deg,
        parking_only=not args.include_non_parking,
    )
    road_match_mode = "grid_fallback"
    if args.use_osm_roads:
        print("Fetching/loading OSM roads and snapping events to nearest road LineStrings")
        roads = fetch_osm_roads_for_events(events, cache_path=args.osm_cache)
        events = match_events_to_osm_roads(events, roads)
        events = events.merge(
            roads[["segment_id", "geometry_wkt"]],
            on="segment_id",
            how="left",
        )
        road_match_mode = "osm_overpass_nearest_road"
    selected_segments = select_active_segments(
        events,
        min_segment_events=args.min_segment_events,
        max_segments=args.max_segments,
    )
    if not selected_segments:
        raise SystemExit("No segments met the activity threshold. Lower --min-segment-events.")

    start_hour = pd.Timestamp(events["event_hour"].min()).floor("h")
    end_hour = pd.Timestamp(events["event_hour"].max()).floor("h")
    cutoff_hour = end_hour - pd.Timedelta(days=args.test_days)
    print(
        f"Using {len(selected_segments)} active segments from {start_hour} to {end_hour}; "
        f"temporal cutoff {cutoff_hour}"
    )

    segment_metadata = build_segment_metadata(events, selected_segments)
    counts = aggregate_hourly_counts(events, selected_segments)
    training_rows = make_training_frame(
        counts,
        selected_segments,
        start_hour=start_hour,
        end_hour=end_hour,
        zero_multiplier=args.zero_multiplier,
        random_state=args.random_state,
    )

    # ── V2: Integrate spatial context (dist_to_metro_m, dist_to_commercial_m) ──
    if HAS_SPATIAL:
        print("Integrating spatial context features (metro/commercial distances)...")
        try:
            spatial_features = build_spatial_context_features(
                segment_metadata, allow_network=True
            )
            segment_metadata = segment_metadata.merge(
                spatial_features, on="segment_id", how="left", suffixes=("", "_spatial")
            )
            for col in ["dist_to_metro_m", "dist_to_commercial_m"]:
                if col in segment_metadata.columns:
                    segment_metadata[col] = segment_metadata[col].fillna(5000.0)
            print(f"  Spatial context: {len(spatial_features)} segments enriched")
        except Exception as exc:
            print(f"  Spatial context failed (non-fatal): {exc}")

    # ── V2: Integrate parking supply (dist_to_legal_parking, overflow_risk) ───
    if HAS_PARKING:
        print("Integrating legal parking supply features...")
        try:
            parking_features = compute_legal_parking_overflow(segment_metadata)
            segment_metadata = segment_metadata.merge(
                parking_features, on="segment_id", how="left", suffixes=("", "_parking")
            )
            for col in ["dist_to_legal_parking_m", "legal_parking_capacity", "overflow_risk_index"]:
                if col in segment_metadata.columns:
                    segment_metadata[col] = segment_metadata[col].fillna(0.0)
            print(f"  Parking supply: {len(parking_features)} segments enriched")
        except Exception as exc:
            print(f"  Parking supply failed (non-fatal): {exc}")

    print(f"Training frame rows: {len(training_rows):,} ({len(counts):,} positive segment-hours)")

    context = build_feature_context(
        counts,
        segment_metadata,
        selected_segments,
        start_hour=start_hour,
        end_hour=end_hour,
        cutoff_hour=cutoff_hour,
        local_timezone=args.timezone,
        grid_size_deg=args.grid_size_deg,
    )
    model, metrics, feature_frame = train_model(
        training_rows,
        context,
        cutoff_hour=cutoff_hour,
        n_estimators=args.n_estimators,
        random_state=args.random_state,
    )
    calibration = calibrate_scoring(counts, context.segment_metadata)
    summary = {
        "data_path": str(data_path),
        "raw_event_rows_after_filter": int(len(events)),
        "active_segments": int(len(selected_segments)),
        "positive_segment_hours": int(len(counts)),
        "training_frame_rows": int(len(training_rows)),
        "start_hour": str(start_hour),
        "end_hour": str(end_hour),
        "cutoff_hour": str(cutoff_hour),
        "grid_size_deg": float(args.grid_size_deg),
        "map_matching_mode": road_match_mode,
    }
    bundle = {
        "model": model,
        "context": context,
        "metrics": metrics,
        "calibration": calibration,
        "training_summary": summary,
    }
    model_path = save_bundle(bundle, out_dir)
    feature_frame.head(1000).to_csv(out_dir / "feature_sample.csv", index=False)
    (out_dir / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Saved model bundle to {model_path}")
    print(json.dumps({"metrics": metrics, "calibration": calibration, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
