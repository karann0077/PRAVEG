import json
import pandas as pd
from shapely import wkt
from pathlib import Path

def get_intersecting_segments(target_wkt: str, predictions_df: pd.DataFrame, distance_m: float = 30.0) -> list:
    """Find segments within distance_m of the target segment geometry using spatial intersection."""
    try:
        target_geom = wkt.loads(target_wkt)
    except Exception:
        return []
    
    # Approximate 1 degree ~ 111000 meters in latitude
    buffer_deg = distance_m / 111000.0
    target_buffered = target_geom.buffer(buffer_deg)
    
    intersecting = []
    for _, row in predictions_df.iterrows():
        wkt_str = row.get("geometry_wkt", "")
        if not wkt_str or not isinstance(wkt_str, str):
            continue
        try:
            geom = wkt.loads(wkt_str)
            if target_buffered.intersects(geom):
                intersecting.append(str(row["segment_id"]))
        except Exception:
            pass
    return intersecting

def generate_ripples(predictions_df: pd.DataFrame, road_graph=None) -> list:
    ripples = []
    
    # Identify severe bottlenecks
    bottlenecks = predictions_df[predictions_df["eps"] >= 70]
    
    for _, row in bottlenecks.iterrows():
        segment_id = str(row["segment_id"])
        eps = float(row["eps"])
        target_wkt = str(row.get("geometry_wkt", ""))
        
        if not target_wkt:
            continue
        
        # Use spatial intersection instead of string parsing or road graph
        queue_segments = get_intersecting_segments(target_wkt, predictions_df, distance_m=30.0)
        
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
