"""TomTom Live Traffic API Integration."""

from __future__ import annotations

import logging
import os
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DEFAULT_TOMTOM_KEY = ""


def fetch_live_congestion(
    lat: float,
    lon: float,
    api_key: str,
) -> tuple[float, list[list[float]]]:
    """Query TomTom Traffic Flow API for real-time congestion and road geometry."""
    
    # TomTom takes point=lat,lon
    point = f"{lat},{lon}"
    
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={point}&key={api_key}"
    
    multiplier = 1.0
    geometry = []
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        flow_data = data.get("flowSegmentData", {})
        
        coords = flow_data.get("coordinates", {}).get("coordinate", [])
        if coords:
            geometry = [[c["longitude"], c["latitude"]] for c in coords]
            
        # Prefer travel time ratio if available
        curr_time = flow_data.get("currentTravelTime", 0)
        free_time = flow_data.get("freeFlowTravelTime", 0)
        
        if curr_time > 0 and free_time > 0:
            multiplier = float(curr_time / free_time)
        else:
            # Fallback to speed ratio
            curr_speed = flow_data.get("currentSpeed", 0)
            free_speed = flow_data.get("freeFlowSpeed", 0)
            
            if curr_speed > 0 and free_speed > 0:
                multiplier = float(free_speed / curr_speed)
                
    except Exception as e:
        logger.warning(f"Failed to fetch live traffic for {lat},{lon}: {e}")
        
    return multiplier, geometry


def enrich_with_live_traffic(
    predictions: pd.DataFrame,
    max_queries: int = 15,
) -> pd.Series:
    """Find top risk segments and fetch their live congestion multiplier."""
    
    api_key_str = os.environ.get("TOMTOM_API_KEY", DEFAULT_TOMTOM_KEY)
    
    import random
    keys = [k.strip() for k in api_key_str.split(",") if k.strip()]
    api_key = random.choice(keys) if keys else ""

    multipliers = pd.Series(1.0, index=predictions.index, dtype=float)
    if "tomtom_geometry" not in predictions.columns:
        predictions["tomtom_geometry"] = None

    if not api_key:
        logger.warning("No TomTom API key available. Bypassing live traffic queries to save time.")
        return multipliers

    # Identify top highest-risk segments based on raw predicted vehicle load
    if not predictions.empty:
        # Sort by predicted_total descending and take the top N
        sorted_preds = predictions.sort_values("predicted_total", ascending=False)
        high_risk_indices = sorted_preds.head(max_queries).index
        
        logger.info(f"Fetching TomTom live traffic for {len(high_risk_indices)} top-risk segments.")
        
        for idx in high_risk_indices:
            row = predictions.loc[idx]
            lon = float(row.get("lon_center", 77.5946))
            lat = float(row.get("lat_center", 12.9716))
            
            multiplier, geometry = fetch_live_congestion(lat, lon, api_key)
            multipliers.loc[idx] = multiplier
            
            import json
            if geometry:
                predictions.at[idx, "tomtom_geometry"] = json.dumps(geometry)

    return multipliers
