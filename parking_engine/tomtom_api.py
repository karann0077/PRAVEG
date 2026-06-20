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
) -> float:
    """Query TomTom Traffic Flow API for real-time congestion."""
    
    # TomTom takes point=lat,lon
    point = f"{lat},{lon}"
    
    url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={point}&key={api_key}"
    
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        flow_data = data.get("flowSegmentData", {})
        
        # Prefer travel time ratio if available
        curr_time = flow_data.get("currentTravelTime", 0)
        free_time = flow_data.get("freeFlowTravelTime", 0)
        
        if curr_time > 0 and free_time > 0:
            return float(curr_time / free_time)
            
        # Fallback to speed ratio
        curr_speed = flow_data.get("currentSpeed", 0)
        free_speed = flow_data.get("freeFlowSpeed", 0)
        
        if curr_speed > 0 and free_speed > 0:
            return float(free_speed / curr_speed)
            
    except Exception as e:
        logger.warning(f"Failed to fetch live traffic for {lat},{lon}: {e}")
        
    return 1.0


def enrich_with_live_traffic(
    predictions: pd.DataFrame,
    max_queries: int = 15,
) -> pd.Series:
    """Find top risk segments and fetch their live congestion multiplier."""
    
    api_key = os.environ.get("TOMTOM_API_KEY", DEFAULT_TOMTOM_KEY)

    multipliers = pd.Series(1.0, index=predictions.index, dtype=float)

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
            
            multiplier = fetch_live_congestion(lat, lon, api_key)
            multipliers.loc[idx] = multiplier

    return multipliers
