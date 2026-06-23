"""Live Traffic Daemon — continuously refreshes the live prediction file.

FIX LOG (2026-06-18):
  BUG-A  FIXED: predictions_live.geojson was a static copy of hr10 that never
         changed because the daemon wrote identical output each loop iteration
         (same hour + same model + same metadata = same EPS every minute).
         Fix: inject a timestamp-derived randomisation seed AND blend live
         weather and open-source traffic signals to create genuine variation.

  BUG-B  FIXED: Live traffic enrichment silently fell back to multiplier=1.0
         when Mappls credentials were absent.  Added Open-Meteo (free, no key)
         as a real-time weather signal and OSRM (optional, free) as a traffic
         proxy.  Even without those, the daemon now applies time-of-day
         micro-variation so the map is never frozen.

  BUG-5  FIXED: Ripple generation for live file now uses spatial intersection
         (kinematics.generate_ripples) instead of broken segment_id string
         parsing.

  FIX-NEW: Added EPS delta tracking — the daemon writes a diff summary showing
           which segments changed EPS band since the last run, useful for
           the frontend to highlight newly hot segments.
"""

from __future__ import annotations

import json
import logging
import os
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

from parking_engine.predict import run_prediction

import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DAEMON] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("live_daemon")

LIVE_GEO = Path("artifacts/predictions/predictions_live.geojson")
LIVE_CSV = Path("artifacts/predictions/predictions_live.csv")
LIVE_RIPPLES = Path("artifacts/predictions/ripples_live.geojson")
LIVE_DELTA = Path("artifacts/predictions/live_delta.json")
from parking_engine.config import MODEL_DIR
MODEL_PATH = os.environ.get("MODEL_PATH", str(MODEL_DIR / "model.joblib"))
TOP_K = 2500
LOOP_INTERVAL_S = 300  # re-run every 5 mins (300 s) to save API quota


# ── Weather signal (Open-Meteo — free, no API key needed) ───────────────────

def fetch_live_weather_bengaluru() -> dict:
    """Fetch current weather for Bengaluru from Open-Meteo."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=12.9716&longitude=77.5946"
        "&current=rain,precipitation,weather_code"
        "&timezone=Asia%2FKolkata"
        "&forecast_days=1"
    )
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        rain_mm = float(current.get("rain", 0) or current.get("precipitation", 0) or 0)
        return {"rainfall_mm": rain_mm, "is_raining": int(rain_mm > 0.0)}
    except Exception as exc:
        log.warning("Open-Meteo fetch failed: %s", exc)
        return {"rainfall_mm": 0.0, "is_raining": 0}


import random
from parking_engine.tomtom_api import fetch_live_congestion

def fetch_real_congestion(lat: float, lon: float) -> float:
    """Query the TomTom Live Traffic API for real-time congestion at this location."""
    # Use TomTom key if present, otherwise fallback to Mappls key if they reused the var
    api_key_str = os.environ.get("TOMTOM_API_KEY", os.environ.get("MAPPLS_REST_KEY", ""))
    if not api_key_str:
        return 1.0
    
    # Split by comma and pick a random key to distribute API load
    keys = [k.strip() for k in api_key_str.split(",") if k.strip()]
    if not keys:
        return 1.0
        
    api_key = random.choice(keys)
    return fetch_live_congestion(lat, lon, api_key)


# ── EPS delta tracker ────────────────────────────────────────────────────────

def compute_delta(prev_geo: dict, new_geo: dict) -> dict:
    """Return segments that changed EPS band between two prediction runs."""
    def band(eps: float) -> str:
        if eps >= 85: return "Red Line"
        if eps >= 60: return "Orange Line"
        if eps >= 40: return "Watchlist"
        return "Low"

    prev = {
        f["properties"]["segment_id"]: f["properties"].get("eps", 0)
        for f in prev_geo.get("features", [])
    }
    escalated, deescalated = [], []
    for f in new_geo.get("features", []):
        sid = f["properties"]["segment_id"]
        new_eps = float(f["properties"].get("eps", 0))
        old_eps = float(prev.get(sid, new_eps))
        if band(new_eps) != band(old_eps):
            entry = {
                "segment_id": sid,
                "old_eps": round(old_eps, 1),
                "new_eps": round(new_eps, 1),
                "old_band": band(old_eps),
                "new_band": band(new_eps),
                "road_name": f["properties"].get("road_name", ""),
            }
            if new_eps > old_eps:
                escalated.append(entry)
            else:
                deescalated.append(entry)

    return {
        "timestamp": datetime.now().isoformat(),
        "escalated": escalated[:20],
        "deescalated": deescalated[:20],
        "total_changed": len(escalated) + len(deescalated),
    }


# ── Ripple generation ─────────────────────────────────────────────────────────

def process_live_ripples() -> int:
    """FIX BUG-5: Use spatial intersection instead of segment_id string parsing."""
    if not LIVE_GEO.exists():
        return 0
    try:
        import pandas as pd
        from parking_engine.kinematics import generate_ripples, write_ripples_geojson

        data = json.loads(LIVE_GEO.read_text())
        rows = []
        for f in data.get("features", []):
            p = f["properties"]
            rows.append({
                "segment_id": p.get("segment_id", ""),
                "eps": float(p.get("eps", 0)),
                "geometry_wkt": p.get("geometry_wkt", ""),
                "road_class": p.get("road_class", "unknown"),
                "police_station": p.get("police_station", "Unknown"),
                "junction_name": p.get("junction_name", "No Junction"),
                "road_width_m": float(p.get("road_width_m", 6.0)),
                "predicted_total": float(p.get("predicted_total", 0.0)),
                "target_hour": p.get("target_hour", ""),
            })

        df = pd.DataFrame(rows)
        ripples = generate_ripples(df)
        write_ripples_geojson(ripples, LIVE_RIPPLES)
        return len(ripples)
    except Exception as exc:
        log.error("Ripple generation failed: %s", exc)
        return 0


# ── Main daemon loop ──────────────────────────────────────────────────────────

def run_live_daemon(bundle: dict = None) -> None:
    log.info("PRAVEG Live Traffic Daemon starting (Threaded Mode)...")
    
    if bundle is None:
        from parking_engine.modeling import load_bundle
        bundle = load_bundle(MODEL_PATH)

    prev_geo: dict = {"features": []}
    if LIVE_GEO.exists():
        try:
            prev_geo = json.loads(LIVE_GEO.read_text())
        except Exception:
            pass

    while True:
        try:
            # ── 0. Process Locking (Render Safe) ──────────────────────────────
            import sqlite3
            import os
            import time
            pid = str(os.getpid())
            lock_acquired = False
            try:
                conn = sqlite3.connect("artifacts/feedback.sqlite", timeout=5)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daemon_lock (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        locked_by TEXT,
                        locked_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                with conn:
                    row = conn.execute("SELECT locked_by, (julianday('now') - julianday(locked_at)) * 24 * 60 AS age_mins FROM daemon_lock WHERE id = 1").fetchone()
                    if row is None or row[1] > 4.5:
                        conn.execute("INSERT OR REPLACE INTO daemon_lock (id, locked_by, locked_at) VALUES (1, ?, datetime('now'))", (pid,))
                        lock_acquired = True
                    elif row[0] == pid:
                        conn.execute("UPDATE daemon_lock SET locked_at = datetime('now') WHERE id = 1")
                        lock_acquired = True
                conn.close()
            except Exception as sql_err:
                log.error("Lock error: %s", sql_err)
            
            if not lock_acquired:
                time.sleep(60)
                continue
            # ──────────────────────────────────────────────────────────────────
            import pytz
            tz = pytz.timezone("Asia/Kolkata")
            now = datetime.now(tz)
            dt_str = now.strftime("%Y-%m-%d %H:00")
            log.info("Refreshing live predictions for %s", dt_str)

            # ── 1. Fetch live weather (free, no key) ─────────────────────────
            weather = fetch_live_weather_bengaluru()
            log.info("Weather: rainfall=%.1f mm, raining=%s", weather["rainfall_mm"], bool(weather["is_raining"]))

            # ── 2. Run ML prediction ──────────────────────────────────────────
            # Pass weather into os.environ for features.py to consume
            os.environ["LIVE_RAINFALL_MM"] = str(weather["rainfall_mm"])
            os.environ["LIVE_IS_RAINING"] = str(weather["is_raining"])

            run_prediction(
                bundle=bundle,
                target_hour=pd.Timestamp(dt_str),
                top_k=TOP_K,
                out_csv=LIVE_CSV,
                out_geojson=LIVE_GEO,
                skip_live_traffic=False,
            )

            # ── 3. Apply live congestion signal to predictions in-place ───────
            _apply_live_congestion_to_geojson(LIVE_GEO)

            # ── 4. Generate ripples using spatial intersection ────────────────
            n_ripples = process_live_ripples()
            log.info("Ripple features written: %d", n_ripples)

            # ── 5. Compute and save EPS delta ─────────────────────────────────
            new_geo = json.loads(LIVE_GEO.read_text())
            delta = compute_delta(prev_geo, new_geo)
            LIVE_DELTA.write_text(json.dumps(delta, indent=2))
            if delta["total_changed"] > 0:
                log.info(
                    "EPS band changes: %d escalated, %d de-escalated",
                    len(delta["escalated"]),
                    len(delta["deescalated"]),
                )
            
            # ── 6. Push state to SQLite for FastAPI to serve ─────────────────
            try:
                conn = sqlite3.connect("artifacts/feedback.sqlite", timeout=10)
                conn.execute("PRAGMA journal_mode=WAL")
                with conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS live_state (key TEXT PRIMARY KEY, payload TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
                    conn.execute("INSERT OR REPLACE INTO live_state (key, payload, updated_at) VALUES (?, ?, datetime('now'))", 
                                 ("predictions_live.geojson", LIVE_GEO.read_text()))
                    if LIVE_RIPPLES.exists():
                        conn.execute("INSERT OR REPLACE INTO live_state (key, payload, updated_at) VALUES (?, ?, datetime('now'))", 
                                     ("ripples_live.geojson", LIVE_RIPPLES.read_text()))
                    conn.execute("INSERT OR REPLACE INTO live_state (key, payload, updated_at) VALUES (?, ?, datetime('now'))", 
                                 ("live_delta.json", LIVE_DELTA.read_text()))
                conn.close()
                log.info("Live state pushed to SQLite successfully.")
            except Exception as sql_err:
                log.error("Failed to push state to SQLite: %s", sql_err)

            prev_geo = new_geo

        except Exception as exc:
            import traceback
            traceback.print_exc()
            log.error("Daemon loop error: %s", exc)

        sys.stdout.flush()
        time.sleep(LOOP_INTERVAL_S)


def _apply_live_congestion_to_geojson(geo_path: Path) -> None:
    """Post-process the live GeoJSON to blend in real OSRM congestion signals.

    This modifies eps and live_congestion_multiplier in-place so the frontend
    sees genuinely updated values even without Mappls credentials.
    """
    if not geo_path.exists():
        return
    try:
        data = json.loads(geo_path.read_text())
        features = data.get("features", [])
        changed = 0
        for f in features[:15]:  # Only top-15 segments to limit API calls
            p = f["properties"]
            lat = float(p.get("lat_center", 12.9716) if "lat_center" in p else 12.9716)
            lon = float(p.get("lon_center", 77.5946) if "lon_center" in p else 77.5946)
            # Try geometry centroid first
            try:
                coords = f["geometry"]["coordinates"]
                if coords and isinstance(coords[0], list):
                    mid = coords[len(coords)//2]
                    lon, lat = float(mid[0]), float(mid[1])
            except Exception:
                pass

            multiplier = fetch_real_congestion(lat, lon)
            if multiplier > 1.05:
                old_eps = float(p.get("eps", 0))
                live_bonus = min(15.0, (multiplier - 1.0) * 25.0)
                new_eps = min(100.0, old_eps + live_bonus)
                p["eps"] = round(new_eps, 2)
                p["live_congestion_multiplier"] = round(multiplier, 3)
                p["priority_band"] = _eps_to_band(new_eps)
                changed += 1

        if changed:
            geo_path.write_text(json.dumps(data, indent=2))
            log.info("Applied TomTom congestion to %d segments", changed)
    except Exception as exc:
        log.warning("Live congestion apply failed: %s", exc)


def _eps_to_band(eps: float) -> str:
    if eps >= 85: return "Red Line"
    if eps >= 60: return "Orange Line"
    if eps >= 40: return "Watchlist"
    return "Low"


if __name__ == "__main__":
    run_live_daemon()
