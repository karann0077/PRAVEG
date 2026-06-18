import json
import requests
from pathlib import Path

def fetch_bengaluru_pois():
    query = """
    [out:json];
    area["name"="Bengaluru"]->.searchArea;
    (
      node["amenity"="hospital"](area.searchArea);
      node["amenity"="school"](area.searchArea);
      node["railway"="station"](area.searchArea);
      node["shop"="mall"](area.searchArea);
    );
    out center 1000;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    response = requests.post(url, data={'data': query})
    response.raise_for_status()
    data = response.json()
    
    features = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        poi_type = "unknown"
        if "hospital" in tags.get("amenity", ""): poi_type = "hospital"
        elif "school" in tags.get("amenity", ""): poi_type = "school"
        elif "station" in tags.get("railway", ""): poi_type = "metro"
        elif "mall" in tags.get("shop", ""): poi_type = "mall"
        
        name = tags.get("name", "Unknown POI")
        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "type": poi_type
            },
            "geometry": {
                "type": "Point",
                "coordinates": [element["lon"], element["lat"]]
            }
        })
        
    out_dir = Path("frontend/public/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "pois.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
        
    print(f"Saved {len(features)} POIs to {out_dir}/pois.geojson")

if __name__ == "__main__":
    fetch_bengaluru_pois()
