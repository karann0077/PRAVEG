import osmnx as ox
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree
from shapely.wkt import loads

def get_bengaluru_pois():
    """Download Namma Metro stations and Commercial retail areas."""
    tags_metro = {"railway": "station"}
    tags_commercial = {"landuse": ["commercial", "retail"]}
    
    # Download POIs for Bengaluru
    metro_pois = ox.features_from_place("Bengaluru, India", tags=tags_metro)
    commercial_pois = ox.features_from_place("Bengaluru, India", tags=tags_commercial)
    
    # Ensure they have geometries
    metro_pois = metro_pois[metro_pois.geometry.notnull()]
    commercial_pois = commercial_pois[commercial_pois.geometry.notnull()]
    
    # Project to EPSG:32643 (UTM zone 43N - South India) for accurate metric distances
    metro_pois = metro_pois.to_crs(epsg=32643)
    commercial_pois = commercial_pois.to_crs(epsg=32643)
    
    # Extract centroids to avoid point-to-polygon M*N complexity
    metro_centroids = metro_pois.geometry.centroid
    commercial_centroids = commercial_pois.geometry.centroid
    
    return metro_centroids, commercial_centroids

def add_poi_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Add distance to nearest metro and commercial zones using cKDTree."""
    if events_df.empty:
        return events_df
        
    df = events_df.copy()
    
    # Check if we already have geometries
    if "geometry_wkt" in df.columns:
        geoms = df["geometry_wkt"].apply(lambda x: loads(str(x)) if pd.notnull(x) else None)
    else:
        # Fallback to lat/lon if geometry_wkt is missing
        geoms = gpd.points_from_xy(df.longitude, df.latitude)
        
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    
    # Project to EPSG:32643
    gdf = gdf.to_crs(epsg=32643)
    
    # Get centroids of roads/events
    event_centroids = gdf.geometry.centroid
    
    try:
        metro_centroids, commercial_centroids = get_bengaluru_pois()
        
        # Build cKDTrees for O(N log M) lookups
        tree_metro = cKDTree(list(zip(metro_centroids.x, metro_centroids.y)))
        tree_commercial = cKDTree(list(zip(commercial_centroids.x, commercial_centroids.y)))
        
        # Query nearest distances
        event_coords = list(zip(event_centroids.x, event_centroids.y))
        
        dist_metro, _ = tree_metro.query(event_coords, k=1)
        dist_comm, _ = tree_commercial.query(event_coords, k=1)
        
        df["dist_to_metro_m"] = dist_metro
        df["dist_to_commercial_m"] = dist_comm
        
    except Exception as e:
        print(f"Warning: Failed to fetch POIs via OSMnx. Falling back to default distances. Error: {e}")
        df["dist_to_metro_m"] = 5000.0  # default far distance
        df["dist_to_commercial_m"] = 5000.0
        
    return df
