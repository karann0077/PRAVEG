import json
from pathlib import Path

def process_geojson_ripples():
    for hr in range(24):
        geo_path = Path(f"artifacts/predictions/predictions_{hr:02d}.geojson")
        out_path = Path(f"artifacts/predictions/ripples_{hr:02d}.geojson")
        
        if not geo_path.exists():
            continue
            
        print(f"Generating ripples for hour {hr:02d}...")
        
        with open(geo_path, "r") as f:
            data = json.load(f)
            
        features = data.get("features", [])
        
        # Build dictionary: v -> list of features where feature's v == this v
        # Wait, if upstream flows into bottleneck: upstream_v == bottleneck_u
        
        upstream_map = {} # Maps a target node 'u' to a list of segments that flow into 'u'
        
        for f in features:
            seg_id = f["properties"].get("segment_id", "")
            if seg_id.startswith("osm_"):
                parts = seg_id.split("_")
                if len(parts) >= 3:
                    u = parts[1]
                    v = parts[2]
                    # This segment flows INTO node v.
                    # So if someone is looking for segments that flow into node v, we are one.
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
                    
                    # Find segments that flow INTO bottleneck_u
                    upstreams = upstream_map.get(bottleneck_u, [])
                    for up_f in upstreams:
                        # Create a ripple feature
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

if __name__ == "__main__":
    process_geojson_ripples()
