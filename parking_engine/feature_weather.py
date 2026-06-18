import pandas as pd
import requests

def get_historical_weather(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch hourly weather from Open-Meteo and force IST timezone."""
    # Bengaluru coords
    lat, lon = 12.9716, 77.5946
    
    # Open-Meteo defaults to UTC. We MUST request in local timezone IST (Asia/Kolkata)
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&hourly=rain&timezone=Asia%2FKolkata"
    )
    
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    
    hourly = data.get("hourly", {})
    df_weather = pd.DataFrame({
        "time": pd.to_datetime(hourly.get("time", [])), # This is now aligned to Asia/Kolkata
        "rainfall_mm": hourly.get("rain", [])
    })
    
    df_weather["date"] = df_weather["time"].dt.date
    df_weather["hour"] = df_weather["time"].dt.hour
    df_weather["is_raining"] = (df_weather["rainfall_mm"] > 0.1).astype(int)
    
    return df_weather

def add_weather_features(events_df: pd.DataFrame) -> pd.DataFrame:
    """Merge weather data and create the rain_shelter_bottleneck feature."""
    if events_df.empty:
        return events_df
        
    df = events_df.copy()
    
    # Ensure datetime parsing
    if "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"])
        df["date"] = dt.dt.date
        df["hour"] = dt.dt.hour
        
    min_date = df["date"].min().strftime("%Y-%m-%d")
    max_date = df["date"].max().strftime("%Y-%m-%d")
    
    try:
        weather_df = get_historical_weather(min_date, max_date)
        # Merge on composite key
        df = pd.merge(df, weather_df[["date", "hour", "rainfall_mm", "is_raining"]], 
                     on=["date", "hour"], how="left")
                     
        # Impute missing
        df["rainfall_mm"] = df["rainfall_mm"].fillna(0.0)
        df["is_raining"] = df["is_raining"].fillna(0)
        
        # OSM tags check for underpass/bridge
        # We will assume a proxy if road_class or osm_highway exists.
        # Normally this requires exact OSM tags, we mock it using string matching for "underpass" or "bridge" in road_name
        is_underpass = df.get("road_name", "").astype(str).str.lower().str.contains("underpass|bridge|flyover")
        df["is_underpass_or_bridge"] = is_underpass.astype(int)
        
        # Interaction feature
        df["rain_shelter_bottleneck"] = df["is_raining"] * df["is_underpass_or_bridge"]
        
    except Exception as e:
        print(f"Warning: Failed to fetch weather data. Error: {e}")
        df["rainfall_mm"] = 0.0
        df["is_raining"] = 0
        df["is_underpass_or_bridge"] = 0
        df["rain_shelter_bottleneck"] = 0
        
    return df
