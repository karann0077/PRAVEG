# PRAVEG — Predictive Parking & Traffic Enforcement Intelligence

<p align="center">
  <strong>Predict where illegal parking becomes a traffic problem — and prioritize what should be handled first.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ML-LightGBM%20%2B%20CatBoost-blue" alt="ML" />
  <img src="https://img.shields.io/badge/Backend-FastAPI-green" alt="Backend" />
  <img src="https://img.shields.io/badge/Frontend-Next.js%2016-black" alt="Frontend" />
  <img src="https://img.shields.io/badge/Geospatial-OSM%20%2B%20Shapely-orange" alt="Geospatial" />
  <img src="https://img.shields.io/badge/Status-Research%20Prototype-purple" alt="Status" />
</p>

## Overview

**PRAVEG** is a research-oriented traffic and parking enforcement intelligence system designed around a simple operational question:

> **Which roads are most likely to experience problematic parking, and which of those roads deserve attention first?**

Traditional violation systems are largely reactive: a violation is recorded, a complaint is received, or an officer observes a problem. PRAVEG instead combines **historical violation patterns, road geometry, vehicle type, legal parking availability, nearby activity, weather, events, and live congestion** to turn predictions into an operational priority.

The important distinction is that PRAVEG does not stop at predicting a violation count. It estimates the **potential road-level disruption** created by those violations and converts that information into an **Enforcement Priority Score (EPS)** for a tactical dashboard.

Built for the **Bengaluru Traffic Police Hackathon**, the project brings together machine learning, geospatial engineering, time-series feature engineering, ranking, explainability, backend systems, and an interactive map-based frontend.

---

## Why this project is interesting

The core idea is to bridge the gap between **prediction** and **decision-making**.

A model may predict that several parking violations are likely on two different roads. But those roads do not have the same operational impact:

```text
Road A: 3 parked cars on a wide road
→ noticeable, but possibly manageable

Road B: 3 parked cars on a narrow road near a busy junction
→ much greater chance of disrupting traffic
```

PRAVEG therefore models the problem as a pipeline:

```text
Historical violations
        ↓
Road matching + temporal aggregation
        ↓
100+ engineered features
        ↓
LightGBM RegressorChain
        ↓
Vehicle-specific violation forecasts
        ↓
CatBoost YetiRank prioritization
        ↓
Physical road-interruption scoring
        ↓
Live traffic adjustment
        ↓
Enforcement Priority Score (EPS)
        ↓
Explainable tactical dashboard
```

This makes the project less about “training a classifier” and more about building an **end-to-end decision-support system**.

---

## Key capabilities

### 1. Road-aware violation forecasting

Historical violation records are mapped onto physical road geometries using **OpenStreetMap (OSM) data and the Overpass API** rather than treating every GPS point as an isolated observation.

The system builds segment-hour observations and captures recurring temporal behaviour such as:

- hour-of-day and day-of-week patterns
- weekday/weekend peaks
- holidays and festivals
- school drop-off and pickup windows
- office commute periods
- lunch/market activity
- shopping and nightlife windows
- recent lagged violation counts
- historical segment intensity

### 2. Multi-vehicle prediction

PRAVEG predicts violation volume separately for six vehicle groups:

- two-wheelers
- cars
- autos
- light commercial vehicles
- heavy vehicles
- other vehicles

This matters because **vehicle type changes physical road impact**. A heavy vehicle occupying the road edge is operationally different from a two-wheeler.

The forecasting model is a **LightGBM Poisson regressor wrapped in a scikit-learn `RegressorChain`**, allowing predictions for one vehicle category to inform later categories.

### 3. Learning-to-rank for dispatch prioritization

Instead of assuming that a raw regression output is an operational priority, PRAVEG uses a second model:

**CatBoost `CatBoostRanker` + YetiRank**

The ranker operates on hourly groups and learns a relative ordering of roads based on severity-weighted violation volume.

This is particularly useful for enforcement because the real operational question is often:

> “We can only act on a limited number of roads. Which ones should be handled first?”

The system also applies **OOF-style Platt calibration** to convert ranking scores into a more useful probability-like signal for downstream scoring.

### 4. Physical interruption modelling

PRAVEG converts predicted vehicles into an estimate of road occupancy using configurable vehicle-width assumptions.

For example:

```text
Predicted vehicles
      ×
Vehicle footprint
      ÷
Road width
      ↓
Estimated interruption
```

The model also incorporates road-class vulnerability and severity weighting so that the same number of violations can produce different priorities on different roads.

### 5. Legal parking supply and demand pressure

Nearby legal parking is treated as part of the prediction context.

The system estimates:

- distance to the nearest legal parking facility
- nearby parking capacity
- historical demand
- an `overflow_risk_index`

This creates a useful behavioural hypothesis: **parking violations are more likely where demand is high and legal supply is inconvenient or insufficient.**

### 6. Spatial context

PRAVEG enriches road segments with nearby points of interest, including categories such as:

- metro stations
- bus stops
- schools
- hospitals
- markets
- offices
- malls
- hotels
- restaurants
- nightlife
- stadiums
- universities
- railway stations

For these POIs, the feature pipeline uses distances, local counts, and a distance-decayed gravity-style score.

### 7. Weather and event awareness

The feature pipeline incorporates weather and local activity context through external data sources.

Examples include:

- rainfall
- active rain conditions
- bridge / underpass context
- rain-shelter bottleneck behaviour
- active event proximity
- event impact score
- number of active events

This lets the system account for conditions that can change where people stop, park, or concentrate.

### 8. Live congestion escalation

A background daemon periodically enriches high-risk predictions with live traffic information from the **TomTom Traffic API**.

When congestion increases on a road already considered risky, its operational priority can be increased.

Live state is persisted through **SQLite with WAL mode**, allowing the frontend and backend to consume continuously refreshed artifacts without requiring the entire model pipeline to run inside every API request.

### 9. Explainable alerts

The dashboard can request an explanation for a selected road.

The backend reconstructs the relevant feature row and uses **SHAP-based explanations** to surface influential features behind the alert.

This is important for operational use: an officer should not only see *which road* was flagged, but also have an indication of *why* it was flagged.

### 10. Tactical map and time-machine interface

The frontend provides a map-first operational view with:

- road-level risk visualization
- dispatch queue
- selected-road inspection
- explanation panel
- predicted future hours
- impact-resolution simulation
- police-station proximity
- patrol/route visualization

The map stack uses **Next.js, React, MapLibre, Deck.gl, Zustand and Recharts**.

---

## System architecture

```text
                         ┌─────────────────────────┐
                         │ Historical Violation DB │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │ Geospatial Preprocessing│
                         │ OSM / Shapely / POIs    │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │ Feature Engineering     │
                         │ Time / Lags / Weather   │
                         │ Events / Parking / POIs │
                         └────────────┬────────────┘
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
              ┌──────────────────┐      ┌──────────────────┐
              │ LightGBM          │      │ CatBoost          │
              │ RegressorChain    │      │ YetiRank          │
              │ vehicle counts    │      │ priority ranking  │
              └─────────┬────────┘      └─────────┬────────┘
                        └────────────┬────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │ Physical Impact Scoring │
                         │ Road width + footprint  │
                         │ severity + vulnerability│
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │ Enforcement Priority    │
                         │ Score (EPS)             │
                         └────────────┬────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
          ┌────────────────────┐              ┌──────────────────┐
          │ Live Traffic /     │              │ FastAPI Backend  │
          │ Weather Daemon     │─────────────▶│ REST + GeoJSON   │
          └────────────────────┘              └────────┬─────────┘
                                                       │
                                                       ▼
                                             ┌──────────────────┐
                                             │ Next.js Tactical │
                                             │ Map Dashboard    │
                                             └──────────────────┘
```

---

## Model design

### Model A — vehicle-specific count forecasting

The forecasting component uses:

```python
LightGBM (Poisson objective)
        ↓
scikit-learn RegressorChain
        ↓
6 vehicle-specific count predictions
```

The six targets are:

```text
count_two_wheeler
count_car
count_auto
count_light_commercial
count_heavy
count_other
```

### Model B — operational ranking

The ranking stage uses:

```python
CatBoostRanker(
    loss_function="YetiRank"
)
```

Road segments are grouped by target hour so the model learns how to order competing roads within the same operational time window.

The ranking target is derived from severity-weighted violation volume and bucketed into operational severity levels.

### Calibration

Because a ranking score is not automatically a probability, PRAVEG adds a calibration layer. The training pipeline includes a held-out calibration window and fits a logistic mapping from ranking scores to a probability-like hotspot signal when sufficient data is available.

---

## Feature engineering

The packaged V5 model records **100 engineered model features** spanning several categories.

| Feature family | Examples |
|---|---|
| Road identity | segment ID, station, junction, road class |
| Road geometry | road width, vulnerability |
| Time | hour, weekday, month, cyclical encodings |
| Operational windows | school, commute, market, shopping, nightlife |
| Recurrence | segment mean, segment-hour mean, city-hour mean |
| Lags | 1h, 2h, 3h, 24h, 168h |
| Vehicle context | vehicle-specific lag counts and footprint |
| Weather | rainfall, rain state, infrastructure context |
| Parking supply | legal parking distance, capacity, overflow risk |
| POIs | nearest distances, counts, gravity score |
| Enforcement history | station-level enforcement and approval metrics |
| Events | active event count, distance, event impact |
| Spatial spillover | decayed intensity and neighbouring-segment score |

The spillover features are implemented as **time-decayed intensity / neighbourhood spillover features**. They are inspired by self-exciting traffic-event behaviour, but the current implementation should not be interpreted as a fully fitted Hawkes point-process model.

---

## Evaluation

The repository includes held-out evaluation results for the packaged **V5 model**.

### Forecasting

| Metric | V5 result |
|---|---:|
| Total MAE | **1.393** |
| Total RMSE | **2.923** |
| Total WAPE | **107.3%** |

### Hotspot / prioritization

| Metric | V5 result |
|---|---:|
| Hotspot ROC-AUC | **0.730** |
| Hotspot Average Precision | **0.244** |
| Hotspot Log Loss | **0.347** |
| Hotspot Brier Score | **0.085** |
| Top 10% violation capture | **24.5%** |
| Precision @ 10 | **24.3%** |
| NDCG @ 10 | **0.376** |
| False dispatch rate @ 10 | **18.3%** |

The V5 evaluation uses a time-based cutoff of **2024-03-18 23:00:00** with separate training and test rows recorded in the model metrics artifact.

> **Important:** These are research-prototype metrics, not production traffic-control guarantees. The relatively high WAPE reflects the difficulty of forecasting sparse, zero-heavy event counts and is one of the areas that should be improved in a future iteration.

---

## Enforcement Priority Score (EPS)

PRAVEG converts the model outputs into a **0–100 operational score** instead of exposing raw model outputs to the user.

The score is influenced by factors such as:

- predicted violation intensity
- vehicle-specific physical footprint
- road width
- violation severity
- road vulnerability
- live congestion adjustments

The frontend uses the score to build a tactical queue and visual risk bands.

Because the current repository contains a few historical threshold definitions across backend, daemon and frontend code, the exact production threshold bands should be **centralized into one configuration source before deployment**.

---

## Project structure

```text
PRAVEG/
│
├── parking_engine/
│   ├── config.py              # Feature/target/config definitions
│   ├── features.py            # Main feature engineering pipeline
│   ├── modeling.py            # LightGBM + CatBoost training
│   ├── train.py               # Training entry point
│   ├── predict.py             # Inference / prediction pipeline
│   ├── scoring.py              # Physical impact + EPS scoring
│   ├── kinematics.py           # Spatial ripple/spillover generation
│   ├── osm_roads.py             # OSM road retrieval + matching
│   ├── road_graph.py            # Optional OSMnx road graph utilities
│   ├── spatial_context.py       # POIs and spatial features
│   ├── parking_supply.py        # Legal parking / supply features
│   ├── weather_context.py       # Weather features
│   ├── event_context.py         # Event features
│   ├── tomtom_api.py            # Live traffic integration
│   ├── explainability.py        # Main SHAP/explanation pipeline
│   └── explain.py               # Legacy explanation helper
│
├── server.py                    # FastAPI backend
├── live_traffic_daemon.py       # Continuous live-state updater
├── run_batch.py                 # 24-hour batch prediction workflow
├── generate_all_ripples.py      # Future ripple generation
│
├── frontend/
│   ├── src/app/                 # Next.js application
│   ├── package.json             # Frontend dependencies/scripts
│   └── ...
│
├── artifacts/                   # Packaged model + evaluation artifacts
├── dataset/                     # Local/private datasets where applicable
├── docs/                        # Additional documentation
├── Makefile                     # Training / prediction commands
├── requirements.txt             # Python dependencies
└── README.md
```

---

## Running the project

### Prerequisites

- Python 3.x
- Node.js / npm
- Git
- Optional API access for live traffic/weather integrations

### Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:3000
```

The repository contains pre-generated artifacts used by the dashboard, so the frontend can be explored without retraining the model.

### Run the Python backend

From the repository root:

```bash
pip install -r requirements.txt
python server.py
```

### Recreate the ML pipeline

The full training workflow requires the original training dataset and the external geospatial/data services used by the feature pipeline.

A typical workflow is:

```bash
pip install -r requirements.txt
make train
make predict
```

For live processing:

```bash
python server.py
python live_traffic_daemon.py
```

### Environment variables

External integrations may require API keys or configuration for services such as TomTom and other data providers.

**Do not commit real API keys or secrets to the repository.** Use environment variables or a local `.env` file that remains ignored by Git.

---

## Technology stack

### Machine Learning

- LightGBM
- CatBoost
- scikit-learn
- SHAP
- Pandas
- NumPy

### Geospatial

- OpenStreetMap
- Overpass API
- Shapely
- OSMnx
- Turf.js
- Haversine distance calculations

### Backend

- FastAPI
- Uvicorn
- SQLite / SQLite WAL

### Frontend

- Next.js **16.2.9**
- React **19.2.4**
- Deck.gl **9.3.4**
- MapLibre GL
- react-map-gl
- Zustand
- Recharts
- Tailwind CSS
- Framer Motion

### External data/services

- TomTom Traffic API
- Open-Meteo
- OpenStreetMap / Overpass
- OSRM for route visualization

---

## What I learned building PRAVEG

This project was intentionally designed as more than a notebook model. The difficult part was integrating several layers that have to agree with each other:

```text
Messy records
→ spatial representation
→ time-aware features
→ ML predictions
→ ranking
→ physical interpretation
→ live enrichment
→ explainability
→ API
→ interactive UI
```

The project exposed several engineering realities that are easy to miss in isolated ML experiments:

- prediction quality and operational usefulness are different objectives
- sparse event data makes naive regression metrics misleading
- ranking is often more relevant than classification when enforcement capacity is limited
- geospatial feature quality can matter as much as model choice
- live systems need a clear source of truth between cached artifacts, background workers and APIs
- explainability must use the same reconstructed feature row as the prediction path
- prototype authentication, API keys, routing and frontend state should be hardened before production deployment

---

## Current limitations and next steps

PRAVEG is a **research / hackathon prototype**, not a production police-deployment system.

Important next steps would include:

1. **Improve temporal generalization** with longer historical data and rolling validation across multiple time windows.
2. **Handle zero-heavy counts more explicitly** with zero-inflated or hurdle-style approaches where appropriate.
3. **Unify EPS thresholds** across backend, daemon and frontend through a single configuration source.
4. **Strengthen live-data reliability** with retries, monitoring, API failure handling and explicit data freshness metadata.
5. **Replace prototype authentication** with real server-side authentication and authorization.
6. **Centralize route computation** rather than mixing heuristic ETA and frontend routing services.
7. **Build a true network-flow spillover model** in place of the current spatial/time-decay heuristic.
8. **Add automated tests and CI** for the feature pipeline, scoring logic, API contracts and frontend behaviour.
9. **Validate economic-loss estimates** against measured traffic delay/cost data rather than treating them as direct observations.
10. **Retrain and validate on current Bengaluru data** before using the system for real operational decisions.

---

## Project positioning

PRAVEG demonstrates the ability to work across the full applied-ML stack:

**Data engineering → geospatial systems → feature engineering → forecasting → learning-to-rank → explainability → real-time enrichment → backend APIs → visualization.**

That end-to-end integration is the main contribution of the project.

---

## Acknowledgement

Developed as a project for the **Bengaluru Traffic Police Hackathon**.
