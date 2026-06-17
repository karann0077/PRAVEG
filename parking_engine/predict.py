"""CLI for future hotspot, bottleneck, and enforcement prediction."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .features import add_features, create_future_rows, create_location_row
from .modeling import load_bundle, predict_feature_frame
from .scoring import score_predictions, write_geojson
from .mappls_api import enrich_with_live_traffic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="artifacts/parking_model/model.joblib", help="Trained model bundle.")
    parser.add_argument("--datetime", required=True, help="Future local datetime, e.g. '2026-06-18 09:00'.")
    parser.add_argument("--top-k", type=int, default=25, help="Number of ranked segments to print/export.")
    parser.add_argument("--lat", type=float, default=None, help="Optional latitude for a single-location query.")
    parser.add_argument("--lon", type=float, default=None, help="Optional longitude for a single-location query.")
    parser.add_argument(
        "--live-congestion-multiplier",
        type=float,
        default=1.0,
        help="Optional live traffic multiplier, duration_in_traffic / duration.",
    )
    parser.add_argument("--out-csv", default="artifacts/predictions/predictions.csv")
    parser.add_argument("--out-geojson", default="artifacts/predictions/predictions.geojson")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = load_bundle(args.model)
    context = bundle["context"]
    model = bundle["model"]
    target_hour = pd.Timestamp(args.datetime).floor("h")

    if (args.lat is None) ^ (args.lon is None):
        raise SystemExit("Pass both --lat and --lon, or neither.")
    if args.lat is not None and args.lon is not None:
        base_rows = create_location_row(context, target_hour, args.lat, args.lon)
    else:
        base_rows = create_future_rows(context, target_hour)

    feature_frame = add_features(base_rows, context)
    predicted = predict_feature_frame(model, feature_frame, context.category_levels)
    
    # Calculate initial total to identify high risk segments for API query
    target_cols = [c for c in predicted.columns if c.startswith("count_")]
    predicted["predicted_total"] = predicted[target_cols].sum(axis=1)
    
    # Fetch live traffic multipliers from MapmyIndia API for top 15% segments
    live_multipliers = enrich_with_live_traffic(predicted)
    
    scored = score_predictions(
        predicted,
        calibration=bundle.get("calibration", {}),
        live_congestion_multiplier=live_multipliers,
    )
    top = scored.head(args.top_k).copy()

    out_csv = Path(args.out_csv)
    out_geojson = Path(args.out_geojson)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    top.to_csv(out_csv, index=False)
    write_geojson(top, out_geojson, grid_size_deg=context.grid_size_deg)

    display_cols = [
        "target_hour",
        "segment_id",
        "police_station",
        "junction_name",
        "road_class",
        "predicted_total",
        "traffic_interruption_0_100",
        "eps",
        "priority_band",
        "recommended_action",
        "recommended_force_units",
    ]
    print(top[display_cols].to_string(index=False, max_colwidth=42))
    print(f"\nSaved CSV: {out_csv}")
    print(f"Saved GeoJSON: {out_geojson}")


if __name__ == "__main__":
    main()
