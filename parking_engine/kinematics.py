import json
import pandas as pd
from shapely import wkt
from pathlib import Path
from .road_graph import load_graph, get_connected_segments

def generate_ripples(predictions_df: pd.DataFrame, road_graph=None) -> list:
    if road_graph is None:
        try:
            road_graph = load_graph("artifacts/osm/bengaluru_roads.json")
        except Exception:
            return []

    ripples = []
    
    # Identify severe bottlenecks
    bottlenecks = predictions_df[predictions_df["eps"] >= 70]
    
    for _, row in bottlenecks.iterrows():
        segment_id = str(row["segment_id"])
        eps = float(row["eps"])
        
        # A simple kinematic wave spillover: 
        # The higher the EPS, the further back the queue grows
        queue_segments = get_connected_segments(road_graph, segment_id, max_distance=300)
        
        for up_seg in queue_segments:
            if up_seg == segment_id:
                continue
                
            # Grab geometry from the predictions df if available
            geom_match = predictions_df[predictions_df["segment_id"] == up_seg]
            geometry = None
            if not geom_match.empty:
                wkt_str = geom_match.iloc[0].get("geometry_wkt", "")
                if isinstance(wkt_str, str) and wkt_str:
                    try:
                        shapely_geom = wkt.loads(wkt_str)
                        if shapely_geom.geom_type == "LineString":
                            geometry = {
                                "type": "LineString",
                                "coordinates": [[float(x), float(y)] for x, y in shapely_geom.coords],
                            }
                    except Exception:
                        pass
            
            if geometry:
                ripples.append({
                    "type": "Feature",
                    "properties": {
                        "source_bottleneck": segment_id,
                        "segment_id": up_seg,
                        "eps_spillover": eps * 0.8, # Decay
                        "is_ripple": True
                    },
                    "geometry": geometry
                })
                
    return ripples

def write_ripples_geojson(ripples: list, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": ripples}
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
