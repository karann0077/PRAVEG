import pandas as pd
import joblib
import math

def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))

stations_df = pd.read_csv("dataset/police_stations.csv")
bundle = joblib.load("artifacts/parking_model_v3_ensemble/model.joblib")
meta = bundle["context"].segment_metadata

for _, row in meta.head(5).iterrows():
    seg_lat = float(row.get("lat_center", 0))
    seg_lon = float(row.get("lon_center", 0))
    
    distances = stations_df.apply(
        lambda r: haversine(seg_lat, seg_lon, float(r["latitude"]), float(r["longitude"])), axis=1
    )
    nearest_idx = distances.idxmin()
    nearest_station = stations_df.loc[nearest_idx]
    print(f"{row['segment_id']}: {nearest_station['matched_name']} ({seg_lat}, {seg_lon})")
