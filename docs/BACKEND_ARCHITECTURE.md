# Backend Architecture (The Orchestrator)

This document explains the Backend server of PRAVEG. It bridges the gap between the heavy ML Engine and the sleek Frontend UI.

## Overview
The backend is a high-performance **FastAPI** Python server. Its main job is to manage the ML predictions, schedule background data fetching, and serve clean, lightning-fast JSON/GeoJSON data to the frontend dashboard. 

## Directory Structure & File Explanations

### The Core Server
- **`server.py`**: The heart of the backend. It boots up the FastAPI web server. 
  - **Routes (API Endpoints)**: It provides endpoints like `/api/predict` (gets parking predictions), `/api/explain` (gets SHAP explanations), and `/api/resolve_impact` (calculates traffic recovery). 
  - **Thread Management**: When the server boots, it automatically launches the background daemon thread so data stays fresh.

### The Background Workers
Because running complex AI models and querying external APIs (like TomTom) takes time, we cannot do it while a user is waiting for the webpage to load. Instead, we use background workers:

- **`live_traffic_daemon.py`**: The real-time worker. 
  - It runs in an infinite loop, waking up exactly every 5 minutes.
  - It fetches live weather (Open-Meteo) and live traffic (TomTom).
  - It triggers the ML engine to generate a prediction for *right now*.
  - It saves the output silently to `artifacts/predictions_live.geojson`. 
  - *Why this matters:* When 1,000 police officers open the dashboard at once, the server doesn't crash making 1,000 API calls. It simply serves the static `.geojson` file that the daemon already prepared!

- **`run_batch.py`**: The time-machine worker.
  - While the live daemon handles "right now", this script pre-calculates the future (+3h, +6h, +9h, +12h).
  - It runs periodically in the background, projecting future traffic conditions based purely on historical patterns, and saves them to static files (e.g., `predictions_03.geojson`).

### Storage
- **`artifacts/`**: The output folder. All generated GeoJSON prediction files, ripple effects, and the feedback database (`feedback.sqlite`) are stored here so the frontend can download them instantly.

## How it works (Step-by-Step)
1. The FastAPI server (`server.py`) starts up.
2. It immediately spawns the `live_traffic_daemon.py` in a background thread.
3. Every 5 minutes, the daemon pulls live data, runs the AI, and overwrites `predictions_live.geojson`.
4. The user opens the web dashboard. The frontend hits the `/api/predictions` endpoint.
5. The backend instantly serves the pre-calculated `predictions_live.geojson` file. No waiting required!
