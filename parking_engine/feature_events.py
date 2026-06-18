import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.wkt import loads

# Mock Hardcoded Events Hubs
EVENT_HUBS = {
    "M. Chinnaswamy Stadium": (12.9788, 77.5996),
    "Kanteerava Stadium": (12.9698, 77.5936),
    "Palace Grounds": (13.0044, 77.5872),
    "BIEC": (13.0617, 77.4746)
}

# Mock historical event calendar (in production, loaded from CSV)
MOCK_EVENTS = [
    {"venue": "M. Chinnaswamy Stadium", "date": "2026-06-18", "start_hour": 16, "end_hour": 22},
    {"venue": "Palace Grounds", "date": "2026-06-15", "start_hour": 10, "end_hour": 18},
]

def get_active_events_for_time(current_date, current_hour):
    """Find events that are active, including the temporal buffer smear."""
    active = []
    for ev in MOCK_EVENTS:
        if str(ev["date"]) == str(current_date):
            # Temporal smear: 2 hours before, 1 hour after
            if (ev["start_hour"] - 2) <= current_hour <= (ev["end_hour"] + 1):
                active.append(ev)
    return active

def add_event_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Inject event impact score utilizing exponential decay and temporal smearing."""
    if events_df.empty:
        return events_df
        
    df = events_df.copy()
    df["event_impact_score"] = 0.0
    
    if "geometry_wkt" in df.columns:
        geoms = df["geometry_wkt"].apply(lambda x: loads(str(x)) if pd.notnull(x) else None)
    else:
        geoms = gpd.points_from_xy(df.longitude, df.latitude)
        
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    gdf = gdf.to_crs(epsg=32643) # Metric
    
    # Calculate for each row
    impacts = []
    for idx, row in df.iterrows():
        c_date = row.get("date")
        c_hour = row.get("hour")
        if pd.isnull(c_date) or pd.isnull(c_hour):
            impacts.append(0.0)
            continue
            
        active_events = get_active_events_for_time(c_date, c_hour)
        if not active_events:
            impacts.append(0.0)
            continue
            
        max_impact = 0.0
        geom = gdf.geometry.iloc[idx]
        if not geom:
            impacts.append(0.0)
            continue
            
        for ev in active_events:
            lat, lon = EVENT_HUBS[ev["venue"]]
            venue_pt = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs="EPSG:4326").to_crs(epsg=32643).iloc[0]
            dist_m = geom.distance(venue_pt)
            
            # Exponential decay: score drops to ~0.36 at 1km, ~0.13 at 2km, ~0.04 at 3km
            impact = np.exp(-dist_m / 1000.0)
            max_impact = max(max_impact, impact)
            
        impacts.append(max_impact)
        
    df["event_impact_score"] = impacts
    return df
