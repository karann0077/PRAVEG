import time
import subprocess
import json
from datetime import datetime
from pathlib import Path

def process_live_ripples():
    geo_path = Path("artifacts/predictions/predictions_live.geojson")
    out_path = Path("artifacts/predictions/ripples_live.geojson")
    
    if not geo_path.exists():
        return
        
    with open(geo_path, "r") as f:
        data = json.load(f)
        
    features = data.get("features", [])
    upstream_map = {} 
    
    for f in features:
        seg_id = f["properties"].get("segment_id", "")
        if seg_id.startswith("osm_"):
            parts = seg_id.split("_")
            if len(parts) >= 3:
                u = parts[1]
                v = parts[2]
                if v not in upstream_map:
                    upstream_map[v] = []
                upstream_map[v].append(f)
                
    ripples = []
    for f in features:
        eps = f["properties"].get("eps", 0)
        if eps >= 70:
            seg_id = f["properties"].get("segment_id", "")
            parts = seg_id.split("_")
            if len(parts) >= 3:
                bottleneck_u = parts[1]
                upstreams = upstream_map.get(bottleneck_u, [])
                for up_f in upstreams:
                    ripple_feature = {
                        "type": "Feature",
                        "properties": {
                            **up_f["properties"],
                            "source_bottleneck": seg_id,
                            "is_ripple": True,
                            "eps_spillover": eps * 0.8
                        },
                        "geometry": up_f["geometry"]
                    }
                    ripples.append(ripple_feature)
                    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": ripples}, f)

def run_live_daemon():
    print("Starting Live Traffic Daemon...")
    while True:
        try:
            now = datetime.now()
            dt_str = now.strftime("%Y-%m-%d %H:00")
            print(f"[{now.strftime('%H:%M:%S')}] Fetching Live Traffic for Top 15 Hotspots...")
            
            subprocess.run([
                "python3", "-m", "parking_engine.predict",
                "--datetime", dt_str,
                "--top-k", "150",
                "--model", "artifacts/parking_model_osm/model.joblib",
                "--out-csv", "artifacts/predictions/predictions_live.csv",
                "--out-geojson", "artifacts/predictions/predictions_live.geojson"
            ], check=True)
            
            process_live_ripples()
            print(f"[{now.strftime('%H:%M:%S')}] Successfully updated predictions_live.geojson and ripples_live.geojson")
            
        except Exception as e:
            print(f"Daemon Error: {e}")
            
        time.sleep(60)

if __name__ == "__main__":
    run_live_daemon()
