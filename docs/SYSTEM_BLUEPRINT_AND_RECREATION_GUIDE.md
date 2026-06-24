# PRAVEG Enterprise Blueprint & Recreation Guide

This document is the absolute "Ground Truth" architectural blueprint of the PRAVEG Parking Intelligence Engine. 
---

## 1. THE MACHINE LEARNING PIPELINE (Model & Feature Engineering)
**Core Goal:** Predict the exact number of illegal vehicles (by vehicle class) that will park on a specific road segment at a specific hour, leveraging geospatial physics and temporal constraints.

### 1.1 The Machine Learning Algorithm
PRAVEG does not use Deep Learning. It uses a **Multi-Output Tree Ensemble**, specifically `CatBoostRegressor` (or an underlying LightGBM ensemble), wrapped to output multiple continuous variables. Tree-based models are mathematically superior for tabular data with high-cardinality categoricals (e.g., `segment_id`, `police_station_name`).

- **Targets:** The model predicts 5 distinct continuous targets simultaneously:
  1. `count_two_wheeler`
  2. `count_car`
  3. `count_auto`
  4. `count_light_commercial`
  5. `count_heavy`
- **Loss Function:** `MultiRMSE` (Root Mean Squared Error across all 5 dimensions).
- **Zero-Inflation Strategy:** Because illegal parking is sparse (mostly 0s), the `train.py` script applies a `--zero-multiplier=1.5` argument. For every hour that has a ticket, it intentionally injects 1.5 rows of "zero-ticket" hours to teach the model when *not* to fire.

### 1.2 Feature Engineering (`features.py` & Senses)
The exact features passed into the CatBoost model:
- **Temporal Cyclical Encoding:** `hour_sin`, `hour_cos`, `day_of_week_sin`, `day_of_week_cos`. This forces the model to understand that 11:59 PM and 12:01 AM are structurally adjacent.
- **Spatial Topological Features:** 
  - `road_width_m`: Direct from OpenStreetMap (`osm_roads.py`).
  - `poi_count_hospital`, `dist_to_commercial_m`: Parsed from `fetch_pois.py`.
- **Event Booleans:** `is_event_active`, parsed from `bengaluru_event_calendar.csv`.
- **Weather API:** `rainfall_mm` and `is_raining`, fetched directly from the Open-Meteo API.

---

## 2. THE PHYSICS & SCORING ALGORITHM (`scoring.py`)
Once the ML model predicts the counts, the system shifts from Machine Learning to **Newtonian Physics**. You cannot dispatch police based on ticket counts alone; you must calculate physical road choke percentages.

### 2.1 The Occupancy Rate Conversion
The ML model predicts *tickets per hour*. However, a vehicle does not stay parked for a full 60 minutes.
```python
# The model predicts violations per hour (an arrival rate).
# On average ~25% of those are simultaneously on-road at any moment.
OCCUPANCY_RATE = 0.25
```
**Formula:** `expected_parked_width = (predicted_cars * 1.9m + predicted_bikes * 0.8m) * 0.25`

### 2.2 Fluid Dynamics Interruption Scoring
The mathematical penalty for narrowing a road is not linear; it is exponential.
```python
# Raw interruption squares the ratio of lost width to total width
interruption_raw = (expected_parked_width / road_width) ** 2 * peak_multiplier
```

### 2.3 The Enterprise CIS / EPS Calculation
The final Enforcement Priority Score (EPS) from 0-100 is an ensemble calculation:
- **Hotspot Score (55%)**: The raw ML probability of a parking cluster forming.
- **Severity Score (35%)**: The physical weight footprint of the vehicles (Heavy trucks score 1.2x penalty).
- **Vulnerability Score (10%)**: The topological weakness of the road (Residential streets get a +0.5 boost to vulnerability if width < 7.0m).
- **Live Congestion Bonus (+0-15 points)**: Extracted from OSRM/TomTom API routing delay.

### 2.4 Economic Loss Formula
Calculates exact INR lost per hour using fluid traffic models:
```python
# Base speed (e.g. 40km/h for primary, 20km/h for residential)
# Speed drops 40% when 30% of road is blocked
speed_reduction_pct = min(95.0, choke_pct * 1.3 + eps * 0.15)
delay_per_vehicle_hr = (D / congested_speed) - (D / base_speed)

# Blended traffic cost based on Bengaluru fleet makeup = 233 INR/hr
economic_loss_inr = traffic_vol * delay_per_vehicle_hr * 233.0
```

---

## 3. BACKEND ORCHESTRATION & DAEMONS
**Core Goal:** Serve massive GeoJSON payloads to the frontend in <50ms without hitting ML inference latency.

### 3.1 FastAPI Architecture (`server.py`)
- **Memory Pre-loading**: `model.joblib` (which is often >100MB) is loaded once via FastAPI `@asynccontextmanager async def lifespan(app)`.
- **Database Thread-Pool**: A SQLite connection to `artifacts/feedback.sqlite` uses `threading.local()` with `PRAGMA journal_mode=WAL` to prevent database locks when multiple police officers submit SHAP recalibration feedback simultaneously.
- **The `/explain` Endpoint**: Instead of storing static explanations, the `/explain` endpoint dynamically reconstructs the exact feature row via `add_features(base_rows, context)` and feeds it into `shap.TreeExplainer(base_lgbm).shap_values(X)` to mathematically prove *why* the CatBoost model flagged the road.

### 3.2 The Background Worker (`live_traffic_daemon.py`)
This script isolates heavy processing from the web server.
- Uses `time.sleep(300)` to execute precisely every 5 minutes.
- Implements `sys.stdout.flush()` to ensure logging circumvents Docker/Render 4KB block buffering.
- Generates `predictions_live.geojson` safely to the local disk. The `/predict` endpoint simply serves this static JSON file, guaranteeing immense horizontal scaling.

---

## 4. FRONTEND ARCHITECTURE (React + Deck.GL)
**Core Goal:** Render 10,000+ data points cleanly at 60 frames per second using WebGL while maintaining synchronized React state across deeply nested components.

### 4.1 Next.js BFF (Backend-For-Frontend)
The `src/app/api/` routes are standard Next.js Route Handlers. They exist purely to hide the backend server's IP address and proxy the requests to avoid Cross-Origin Resource Sharing (CORS) exceptions in the browser.

### 4.2 Zustand Global State (`useMapStore.ts`)
Prop-drilling is avoided entirely by utilizing a global Zustand store.
```typescript
interface MapState {
  targetHour: string | null;  // E.g. "live", "15:00"
  selectedEdge: any | null;   // The clicked GeoJSON feature
  activeLayerMode: 'action_roads' | 'traffic_blockage';
}
```
When `targetHour` changes via the Time Machine slider, the map detects the state change, triggers a new `/api/predictions` request, and cross-fades the new GeoJSON data.

### 4.3 WebGL Map Rendering (`TacticalMap.tsx`)
Deck.GL sits directly over React-Map-GL.
- **PathLayer**: Renders the core road network. It extracts the `geometry_wkt` from the GeoJSON and converts it to coordinate arrays. Color is determined by `getLineColor: d => [d.eps >= 80 ? 239 : 59, ...]`.
- **IconLayer**: The Kinematic Ripples. Renders pulsing SVG icons over the coordinates generated by `kinematics.py`.
- **TripsLayer**: The Patrol Simulation. Animates a glowing comet along `patrolRouteGeometry` (fetched via the `/nearest_station` routing endpoint) using a synchronized `requestAnimationFrame` loop tied to the system clock.

### 4.4 The Analytical Panels
- **DispatchQueue (Left)**: Loops through the GeoJSON, filtering for `priority_band === 'Red Line'`, and sorting by EPS.
- **PhysicsInspector (Right)**: Activated via `selectedEdge`. Renders the Dual-Tone CSS Traffic Flow Recovery bar by dividing `speed_kmh` by `base_speed_kmh` and mapping it to `width: ${recovery_pct}%`.
