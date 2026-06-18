"""MapmyIndia (Mappls) Live Traffic API Integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Credentials should be provided via environment variables
DEFAULT_REST_KEY = ""
DEFAULT_CLIENT_ID = ""
DEFAULT_CLIENT_SECRET = ""


def get_auth_token(client_id: str, client_secret: str) -> str | None:
    """Fetch OAuth2 token from MapmyIndia Outpost."""
    url = "https://outpost.mapmyindia.com/api/security/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
        return str(response.json().get("access_token"))
    except Exception as e:
        logger.warning(f"Failed to authenticate MapmyIndia API: {e}")
        return None


def fetch_live_congestion(
    lon: float,
    lat: float,
    rest_key: str,
    token: str | None = None,
) -> float:
    """Query MapmyIndia Advanced Routing/Distance Matrix API for real-time congestion."""
    
    # We query a tiny bounding route to ensure it forces a route evaluation on the segment.
    start_point = f"{lon},{lat}"
    end_point = f"{lon+0.0002},{lat+0.0002}"
    url = f"https://apis.mappls.com/advancedmaps/v1/{rest_key}/distance_matrix/driving/{start_point};{end_point}"
    
    headers = {}
    if token:
        headers["Authorization"] = f"bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Mappls distance matrix returns 'durations' and 'durations_in_traffic' matrices
        # We assume the first matrix element [0][1] represents start -> end
        if "durations" in data and "durations_in_traffic" in data:
            duration = data["durations"][0][1]
            duration_in_traffic = data["durations_in_traffic"][0][1]
            
            if duration > 0 and duration_in_traffic > 0:
                return float(duration_in_traffic / duration)
    except Exception as e:
        logger.warning(f"Failed to fetch live traffic for {lon},{lat}: {e}")
        
    return 1.0


def enrich_with_live_traffic(
    predictions: pd.DataFrame,
    max_queries: int = 15,
) -> pd.Series:
    """Find top risk segments and fetch their live congestion multiplier."""
    
    client_id = os.environ.get("MAPPLS_CLIENT_ID", DEFAULT_CLIENT_ID)
    client_secret = os.environ.get("MAPPLS_CLIENT_SECRET", DEFAULT_CLIENT_SECRET)
    rest_key = os.environ.get("MAPPLS_REST_KEY", DEFAULT_REST_KEY)

    token = get_auth_token(client_id, client_secret)
    multipliers = pd.Series(1.0, index=predictions.index, dtype=float)

    if not token:
        logger.warning("No MapmyIndia token available. Bypassing live traffic queries to save time.")
        return multipliers

    
    # Identify top highest-risk segments based on raw predicted vehicle load
    if not predictions.empty:
        # Sort by predicted_total descending and take the top N
        sorted_preds = predictions.sort_values("predicted_total", ascending=False)
        high_risk_indices = sorted_preds.head(max_queries).index
        
        logger.info(f"Fetching MapmyIndia live traffic for {len(high_risk_indices)} top-risk segments.")
        
        for idx in high_risk_indices:
            row = predictions.loc[idx]
            lon = float(row.get("lon_center", 77.5946))
            lat = float(row.get("lat_center", 12.9716))
            
            multiplier = fetch_live_congestion(lon, lat, rest_key, token)
            multipliers.loc[idx] = multiplier

    return multipliers
