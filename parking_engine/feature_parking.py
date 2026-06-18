import osmnx as ox
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree
from shapely.wkt import loads

def get_bengaluru_parking():
    """Download legal parking geometries and calculate capacity with multi-storey logic."""
    tags_parking = {"amenity": "parking"}
    
    parking_pois = ox.features_from_place("Bengaluru, India", tags=tags_parking)
    parking_pois = parking_pois[parking_pois.geometry.notnull()]
    
    # Project to EPSG:32643 to calculate exact area in square meters
    parking_pois = parking_pois.to_crs(epsg=32643)
    
    # Extract capacity or estimate it
    def estimate_capacity(row):
        # Use tagged capacity if it exists
        if "capacity" in row and pd.notnull(row["capacity"]):
            try:
                return float(row["capacity"])
            except ValueError:
                pass
                
        # Fallback to spatial estimation
        area_sqm = row.geometry.area
        base_capacity = area_sqm / 15.0 # 15 sqm per spot
        
        # Multi-storey edge case check
        if "parking" in row and row["parking"] == "multi-storey":
            levels = 3 # Assume 3 levels if not specified
            if "building:levels" in row and pd.notnull(row["building:levels"]):
                try:
                    levels = max(1, float(row["building:levels"]))
                except ValueError:
                    pass
            return base_capacity * levels
            
        return base_capacity
        
    parking_pois["legal_parking_capacity"] = parking_pois.apply(estimate_capacity, axis=1)
    parking_centroids = parking_pois.geometry.centroid
    
    return parking_centroids, parking_pois["legal_parking_capacity"].values

def add_parking_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Add distance to legal parking, capacity, and overflow risk index."""
    if events_df.empty:
        return events_df
        
    df = events_df.copy()
    
    if "geometry_wkt" in df.columns:
        geoms = df["geometry_wkt"].apply(lambda x: loads(str(x)) if pd.notnull(x) else None)
    else:
        geoms = gpd.points_from_xy(df.longitude, df.latitude)
        
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    gdf = gdf.to_crs(epsg=32643)
    event_centroids = gdf.geometry.centroid
    
    try:
        parking_centroids, parking_capacities = get_bengaluru_parking()
        
        tree_parking = cKDTree(list(zip(parking_centroids.x, parking_centroids.y)))
        event_coords = list(zip(event_centroids.x, event_centroids.y))
        
        dist_parking, idx_parking = tree_parking.query(event_coords, k=1)
        
        df["dist_to_legal_parking_m"] = dist_parking
        df["nearest_parking_capacity"] = [parking_capacities[i] for i in idx_parking]
        
        # Calculate overflow risk: historical volume / (capacity + 1)
        # We assume segment_total_events represents volume proxy
        volume = df.get("segment_total_events", 10) 
        df["overflow_risk_index"] = volume / (df["nearest_parking_capacity"] + 1)
        
    except Exception as e:
        print(f"Warning: Failed to fetch parking POIs. Error: {e}")
        df["dist_to_legal_parking_m"] = 5000.0
        df["nearest_parking_capacity"] = 50.0
        df["overflow_risk_index"] = 0.0
        
    return df
