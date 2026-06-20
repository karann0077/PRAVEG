# PRAVEG Enterprise System Architecture

This document provides a deeply comprehensive, end-to-end architectural breakdown of the PRAVEG Parking Intelligence Engine. It is designed to replace all previous documentation and provide a master reference covering the Backend Orchestration, the ML & Physics Engine, and the Frontend Dashboard interface.

---

## PART 1: BACKEND ARCHITECTURE (The Orchestrator)
**Location:** `/server.py`, `/live_traffic_daemon.py`, `/run_batch.py`

The backend serves as the critical bridge connecting the heavy data-science operations of the ML engine to the real-time requirements of the Next.js frontend. It is built on **FastAPI** to maximize async performance and throughput.

### 1.1 The FastAPI Server (`server.py`)
The `server.py` file is the master orchestrator. It controls the lifecycle of the ML models and handles HTTP request routing.

- **Lifespan Context Manager**: When the server boots, it executes the `lifespan` function. This function pre-loads the massive `model.joblib` artifact into RAM. Loading this in the lifespan block ensures that HTTP endpoints do not have to perform disk I/O when processing a user request.
- **Thread-Local Database Pool**: The backend uses SQLite (`artifacts/feedback.sqlite`) to store human-in-the-loop recalibration data from officers. Because the daemon and HTTP endpoints run concurrently, `server.py` uses a thread-local pool (`_db_local = threading.local()`) and enables WAL (Write-Ahead Logging) mode via `PRAGMA journal_mode=WAL` to prevent database locking errors.
- **Background Daemon Invocation**: The lifespan block spawns `live_traffic_daemon.py` as a background thread (`daemon=True`) immediately after the model loads.

### 1.2 Core API Endpoints
The frontend interacts with the backend through several REST endpoints:

- **`/predict`**: The primary data feed. The frontend requests data for a specific `datetime`. If the `datetime` is "live", the backend fetches the `predictions_live.geojson` file (maintained by the daemon). It parses the model's output, calculates the Enterprise CIS (Congestion Impact Score), and returns the top 25 hotspots.
- **`/explain`**: The explainability endpoint. When an officer clicks a specific road segment, this endpoint receives the `segment_id`. It reconstructs the EXACT mathematical feature row that the ML model saw, feeds it into a SHAP (SHapley Additive exPlanations) `TreeExplainer`, and returns the exact numerical impact of the Top 5 positive and Top 3 negative contributing features (e.g., Rainfall +1.2 EPS).
- **`/resolve_impact`**: The physics simulation endpoint. It pulls the expected parked width for a `segment_id` and calculates the theoretical road clearance *before* and *after* a tow truck clears the road. It returns metrics like `speed_recovery_kmh` and `economic_savings_per_hr`.
- **`/nearest_station`**: The geospatial routing endpoint. It uses the Haversine formula to compute the spherical distance between the hotspot's latitude/longitude and all police stations in `dataset/police_stations.csv`, calculating a routing ETA based on a congested city speed of 15 km/h.

### 1.3 The Live Traffic Daemon (`live_traffic_daemon.py`)
Because querying ML models and 3rd-party APIs on every page load would destroy performance and API quotas, the PRAVEG architecture uses a publish-subscribe pattern via a background daemon.

- **The Infinite Loop**: The daemon runs an infinite `while True:` loop. At the bottom of the loop, it executes `sys.stdout.flush()` and `time.sleep(300)` to strictly enforce a 5-minute update cadence.
- **External Signal Ingestion**:
  1. *Open-Meteo API*: Fetches real-time rainfall data.
  2. *OSRM / TomTom API*: Fetches real-time localized congestion multipliers.
- **Live Prediction Execution**: It passes the live weather variables into `os.environ`, overriding historical features. It calls `run_prediction`, which generates a brand new GeoJSON file covering the entire city grid.
- **Ripple Generation (`process_live_ripples`)**: It triggers the `kinematics.py` engine to calculate downstream traffic jams caused by the newly detected hotspots.
- **EPS Delta Tracking**: It compares the new EPS scores with the previous loop's scores to calculate which roads "escalated" or "de-escalated". This is saved to `live_delta.json` so the frontend can flash warning animations on newly congested roads.

---

## PART 2: ML ENGINE & PHYSICS ARCHITECTURE (The Brain)
**Location:** `/parking_engine/`

The ML engine is the core intellectual property of PRAVEG. It fuses tabular Machine Learning (CatBoost) with strict Newtonian physics formulas to bridge the gap between "number of predicted tickets" and "actual traffic gridlock".

### 2.1 Feature Engineering (`features.py` & Contexts)
Before the model can predict anything, it needs context.
- **`osm_roads.py` & `spatial_context.py`**: Ingests OpenStreetMap data to build a localized topological graph. It extracts `road_width_m`, `lanes`, and `osm_highway` classifications.
- **`fetch_pois.py`**: Queries spatial datasets to count the number of Hospitals, Malls, and Schools within a localized radius of every road segment.
- **`event_context.py`**: Reads `bengaluru_event_calendar.csv` to inject binary flags if major crowd-drawing events (like IPL cricket matches at Chinnaswamy Stadium) are occurring.

### 2.2 The ML Pipeline (`train.py` & `predict.py`)
- **Algorithm**: PRAVEG uses a Multi-Output `CatBoostRegressor` (or an underlying LightGBM ensemble wrapped in a custom predictor). Tree-based models are chosen over Deep Learning because they handle tabular categorical data (like "Day of Week" or "Police Station ID") significantly better and are natively compatible with SHAP explainability.
- **Targets**: The model does not predict "congestion". It strictly predicts count variables: `count_two_wheeler`, `count_car`, `count_auto`, `count_light_commercial`, and `count_heavy`.

### 2.3 The Physics & Scoring Engine (`scoring.py`)
This file is the most mathematically complex script in the repository. Once the model predicts raw vehicle counts, `scoring.py` converts those abstract numbers into actionable police dispatch scores.

- **The Occupancy Correction**: The ML model predicts *arrivals per hour*. However, a vehicle does not park for an entire hour. The `OCCUPANCY_RATE = 0.25` constant assumes a 15-minute average dwell time. This converts the hourly arrival rate into an *expected concurrent footprint*.
- **The Choke Equation**:
  ```python
  expected_parked_width = (predicted_cars * 1.9m + predicted_bikes * 0.8m) * 0.25
  interruption_raw = (expected_parked_width / actual_road_width) ** 2
  ```
  Squaring the ratio mimics non-linear fluid dynamics—losing 1 meter on a 10m road is a minor inconvenience, but losing 1 meter on a 3m road is catastrophic.
- **Enterprise CIS (Congestion Impact Score) / EPS**:
  The final EPS (0-100) is a weighted mathematical ensemble:
  - `55%`: The pure ML hotspot probability.
  - `35%`: The severity footprint (normalized count of heavy vs light vehicles).
  - `10%`: Road Vulnerability (Residential streets score higher vulnerability than Motorways).
- **Economic Loss Calculator**: Calculates exact INR lost per hour using empirical traffic flow models. It calculates `t_normal_hr` vs `t_congested_hr` based on road-width choke percentages, multiplying the delay by traffic volume and a blended vehicular cost rate of 233 INR/hr.

---

## PART 3: FRONTEND ARCHITECTURE (The Dashboard)
**Location:** `/frontend/src/`

The frontend is a React-based Next.js App Router application. It acts as the tactical "single pane of glass" for the police dispatch commander.

### 3.1 Next.js App Router & BFF Pattern
- **BFF (Backend-For-Frontend)**: The `frontend/src/app/api/` directory acts as a proxy. Instead of the browser directly fetching data from the Python server (which exposes backend IPs and risks CORS violations), the React components fetch from `/api/predict/route.ts` (Node.js), which securely relays the request to Python.

### 3.2 Global State Management (`useMapStore.ts`)
PRAVEG relies on **Zustand** for global state. Because Deck.GL (the map), the DispatchQueue (left panel), and the PhysicsInspector (right panel) are entirely separate components in the React tree, they communicate via `useMapStore`.
- `targetHour`: Controls the Time Machine. When changed, the map re-fetches data.
- `selectedEdge`: Stores the GeoJSON properties of a clicked road segment, triggering the Right Panel to open.
- `activeLayerMode`: Toggles between viewing "Actionable Roads", "Traffic Blockage", or "Patrol Routes".

### 3.3 Visual Layering Engine (`TacticalMap.tsx`)
The map utilizes **Deck.GL** overlaid on **React-Map-GL**. It uses a specialized layered rendering architecture:
1. **PathLayer (The Roads)**: Renders the glowing line segments. The color accessor dynamically reads the `eps` property from the GeoJSON to assign Red (Critical), Orange (Warning), or Blue (Clear).
2. **IconLayer (The Ripples)**: Renders pulsating warning icons on downstream segments computed by the kinematics engine.
3. **TripsLayer (The Patrol Simulation)**: A time-animated layer that draws a moving blue "comet" along the `patrolRouteGeometry`, simulating a tow truck driving from the nearest police station to the hotspot.

### 3.4 Commander UI Panels
- **`DispatchQueue.tsx` (Left Panel)**: Acts as the task list. It sorts all GeoJSON features by EPS descending. It heavily utilizes Tailwind flexbox layouts to display nested badges showing "Blockage %" and "Confidence Bands".
- **`PhysicsInspector.tsx` (Right Panel)**: The deep-dive analytical view. When `selectedEdge` is populated in Zustand, this panel slides into view. It maps the SHAP impact arrays into visual progress bars (Green for positive impact, Red for negative). It also mounts the Traffic Flow Recovery visualizer, rendering a dual-tone CSS bar chart to prove the efficacy of dispatching a tow truck.
- **`TimeMachine.tsx` (Bottom UI)**: An interactive timeline scrubber. It calculates dynamic hour intervals (`currentHour + 3`, etc.) and updates the global `targetHour` state, causing the entire React tree to cascade an update and re-render the future state of the city.

---

*This architecture document covers the complete V4 state of the PRAVEG system, detailing its evolution from a simple parking predictor to an enterprise-grade physics and kinematics intelligence platform.*
