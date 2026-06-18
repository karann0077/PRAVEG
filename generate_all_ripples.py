"""Pre-compute ripple (traffic spillover) GeoJSON for each of the 24 hourly
prediction files.

FIX LOG (2026-06-18):
  BUG-5  FIXED: The old code parsed segment_id as "osm_U_V" and tried to match
         graph nodes via string splitting.  Actual segment IDs are "osm_way_XXXXX"
         (OSM way IDs, NOT node pairs), so the upstream_map was always empty and
         every ripple file contained 0 features.

         New approach: use kinematics.get_intersecting_segments() which loads
         geometry_wkt from properties (now written by fixed scoring.py) and does
         actual Shapely spatial intersection with a 30 m buffer.

  BUG-7  FIXED: run_batch.py never called this script.  The fix is in run_batch.py.

  FIX-NEW: Ripples now carry the parent eps, decayed by 0.8, AND the ripple's
           own geometry so DeckGL can render them as separate coloured lines.
"""

from __future__ import annotations

import json
from pathlib import Path

from parking_engine.kinematics import generate_ripples, write_ripples_geojson


def process_hour(hr: int) -> int:
    """Generate ripple features for one hourly prediction file.
    Returns the number of ripple features written.
    """
    geo_path = Path(f"artifacts/predictions/predictions_{hr:02d}.geojson")
    out_path = Path(f"artifacts/predictions/ripples_{hr:02d}.geojson")

    if not geo_path.exists():
        print(f"  [SKIP] {geo_path} not found")
        return 0

    with open(geo_path, "r") as fh:
        data = json.load(fh)

    features = data.get("features", [])
    if not features:
        write_ripples_geojson([], out_path)
        return 0

    # Build a lightweight DataFrame for the ripple engine
    import pandas as pd
    rows = []
    for f in features:
        p = f["properties"]
        rows.append({
            "segment_id": p.get("segment_id", ""),
            "eps": float(p.get("eps", 0)),
            # geometry_wkt is now present in properties (fixed scoring.py)
            "geometry_wkt": p.get("geometry_wkt", ""),
            "road_class": p.get("road_class", "unknown"),
            "police_station": p.get("police_station", "Unknown"),
            "junction_name": p.get("junction_name", "No Junction"),
            "road_width_m": float(p.get("road_width_m", 6.0)),
            "predicted_total": float(p.get("predicted_total", 0.0)),
            "target_hour": p.get("target_hour", ""),
        })

    predictions_df = pd.DataFrame(rows)
    ripples = generate_ripples(predictions_df)
    write_ripples_geojson(ripples, out_path)
    return len(ripples)


def process_all_hours() -> None:
    total = 0
    for hr in range(24):
        n = process_hour(hr)
        print(f"  Hour {hr:02d}: {n} ripple features")
        total += n
    print(f"\nTotal ripple features across 24 hours: {total}")


if __name__ == "__main__":
    print("Generating ripples for all 24 hours...")
    process_all_hours()
    print("Done.")
