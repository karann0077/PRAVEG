"""CLI for future hotspot, bottleneck, and enforcement prediction."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

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
    parser.add_argument("--skip-live-traffic", action="store_true", help="Do not fetch live Mappls traffic.")
    parser.add_argument("--out-csv", default="artifacts/predictions/predictions.csv")
    parser.add_argument("--out-geojson", default="artifacts/predictions/predictions.geojson")
    return parser.parse_args()


def run_prediction(
    bundle: dict,
    target_hour: pd.Timestamp,
    top_k: int,
    out_csv: Path,
    out_geojson: Path,
    skip_live_traffic: bool = False,
    live_congestion_multiplier: float = 1.0,
    lat: float = None,
    lon: float = None,
) -> None:
    context = bundle["context"]
    model = bundle["model"]

    if (lat is None) ^ (lon is None):
        raise SystemExit("Pass both --lat and --lon, or neither.")
    if lat is not None and lon is not None:
        base_rows = create_location_row(context, target_hour, lat, lon)
    else:
        base_rows = create_future_rows(context, target_hour)

    feature_frame = add_features(base_rows, context)
    predicted = predict_feature_frame(model, feature_frame, context.category_levels)
    
    # Calculate initial total to identify high risk segments for API query
    target_cols = [c for c in predicted.columns if c.startswith("count_")]
    predicted["predicted_total"] = predicted[target_cols].sum(axis=1)
    
    # Fetch live traffic multipliers from MapmyIndia API for top 15% segments
    if skip_live_traffic:
        live_multipliers = live_congestion_multiplier
    else:
        live_multipliers = enrich_with_live_traffic(predicted)
    
    scored = score_predictions(
        predicted,
        calibration=bundle.get("calibration", {}),
        live_congestion_multiplier=live_multipliers,
    )
    top = scored.head(top_k).copy()

    # Filter out safe segments to prevent the map from rendering thousands of irrelevant green lines (abnormal graph fix)
    top = top[top["eps"] >= 15]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    top.to_csv(out_csv, index=False)
    write_geojson(top, out_geojson, grid_size_deg=context.grid_size_deg)


def main() -> None:
    args = parse_args()
    bundle = load_bundle(args.model)
    target_hour = pd.Timestamp(args.datetime).floor("h")

    out_csv = Path(args.out_csv)
    out_geojson = Path(args.out_geojson)

    run_prediction(
        bundle=bundle,
        target_hour=target_hour,
        top_k=args.top_k,
        out_csv=out_csv,
        out_geojson=out_geojson,
        skip_live_traffic=args.skip_live_traffic,
        live_congestion_multiplier=args.live_congestion_multiplier,
        lat=args.lat,
        lon=args.lon,
    )

    # Note: CLI output printing was removed from run_prediction to keep it clean.
    # To restore it for CLI, you could read the saved CSV and print here.
    print(f"\nSaved CSV: {out_csv}")
    print(f"Saved GeoJSON: {out_geojson}")




if __name__ == "__main__":
    main()
