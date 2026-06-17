# Spatiotemporal Parking Hotspot And Enforcement Engine

This project trains a multi-output LightGBM engine on the provided Bengaluru parking-violation CSV. It predicts future illegal-parking hotspot intensity by segment and hour, estimates traffic-flow interruption from vehicle width and road width, and ranks enforcement dispatch priorities.

## What It Builds

- Hourly hotspot forecasts by vehicle class.
- Physical bottleneck score using vehicle widths, imputed road widths, and peak-hour multipliers.
- Enforcement Priority Score (EPS) with Red Line, Orange Line, Watchlist, and Low bands.
- CSV and GeoJSON outputs for enforcement planning and map visualization.
- Optional OSMnx road-edge matcher for the exact graph architecture when geospatial dependencies are installed.

## Train

```bash
python3 -m parking_engine.train \
  --data "dataset/jan to may police violation_anonymized791b166.csv" \
  --out artifacts/parking_model \
  --min-segment-events 20 \
  --zero-multiplier 1.5 \
  --test-days 21 \
  --n-estimators 350
```

## Train With True Road Lines From OpenStreetMap

This uses public Overpass/OpenStreetMap road ways, snaps violations to the
nearest road `LineString`, and exports future hotspots as road lines instead of
circle/radius hotspots.

```bash
python3 -m parking_engine.train \
  --data "dataset/jan to may police violation_anonymized791b166.csv" \
  --out artifacts/parking_model_osm \
  --use-osm-roads \
  --min-segment-events 20 \
  --zero-multiplier 1.25 \
  --test-days 21 \
  --n-estimators 300
```

## Predict All Hotspots

```bash
python3 -m parking_engine.predict \
  --model artifacts/parking_model/model.joblib \
  --datetime "2026-06-18 09:00" \
  --top-k 25 \
  --out-csv artifacts/predictions/predictions.csv \
  --out-geojson artifacts/predictions/predictions.geojson
```

## Predict A Specific Location

```bash
python3 -m parking_engine.predict \
  --model artifacts/parking_model/model.joblib \
  --datetime "2026-06-18 18:00" \
  --lat 12.9777 \
  --lon 77.5805 \
  --top-k 1
```

## Live Traffic Calibration

If MapmyIndia/Mappls returns live route travel time and free-flow travel time, pass:

```bash
--live-congestion-multiplier 1.45
```

That multiplier is treated as `duration_in_traffic / duration` and boosts EPS only when the predicted parking risk is also high.

## Artifacts

- `artifacts/parking_model/model.joblib`: trained model bundle.
- `artifacts/parking_model/metrics.json`: temporal test metrics.
- `artifacts/parking_model/segment_metadata.csv`: learned segment catalog.
- `artifacts/predictions/predictions.csv`: ranked future hotspot predictions.
- `artifacts/predictions/predictions.geojson`: map-ready enforcement layer.

## Important Limitation

The attached architecture correctly prefers exact road-network edges. The current workspace contains only the violation CSV, so the default trained model uses deterministic 0.001-degree grid segments. Install `osmnx` and provide/download a Bengaluru drive graph to switch Phase 1 to true road-edge matching.
