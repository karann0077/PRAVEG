import os
import subprocess

for hr in range(24):
    dt = f"2026-06-18 {hr:02d}:00"
    print(f"Generating sanitized base predictions for {dt}...")
    subprocess.run([
        "python3", "-m", "parking_engine.predict",
        "--datetime", dt,
        "--top-k", "150",
        "--model", "artifacts/parking_model_osm/model.joblib",
        "--skip-live-traffic",
        "--out-csv", f"artifacts/predictions/predictions_{hr:02d}.csv",
        "--out-geojson", f"artifacts/predictions/predictions_{hr:02d}.geojson"
    ], check=True)
