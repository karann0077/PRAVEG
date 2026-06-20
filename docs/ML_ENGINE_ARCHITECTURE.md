# ML Engine Architecture (The Brain)

This document explains the Machine Learning and predictive physics engine of PRAVEG. It is designed so that a beginner can understand exactly how data turns into predictive enforcement alerts.

## Overview
The ML Engine lives inside the `parking_engine/` directory. Its core job is to ingest raw data (OpenStreetMap roads, weather, events, historical violations) and output a clean GeoJSON file containing the predicted illegal parking count and the **Enforcement Priority Score (EPS)** for every road segment in the city.

## Directory Structure & File Explanations

### Core Pipeline
- **`train.py`**: The training script. It takes historical data and trains a powerful `CatBoostRegressor` AI model. The model learns patterns like "If it's raining, and there is a cricket match nearby, and the road is narrow, parking violations spike."
- **`predict.py` / `modeling.py`**: The Inference Engine. These scripts load the trained model into memory and feed it current data to generate live predictions. 
- **`features.py`**: The Feature Engineering factory. It combines base road data with live context (weather, time of day) so the ML model has all the inputs it needs to make a prediction.
- **`scoring.py`**: The Physics Engine. Once the ML model predicts *how many* vehicles will park illegally, this script calculates the physical impact. It subtracts vehicle width from road width to calculate `clearance_m` and `choke_percent`. It calculates the final **EPS (Enforcement Priority Score)** and the Economic Loss.

### Context Providers (The Senses)
These scripts feed real-world context into the model:
- **`osm_roads.py` & `spatial_context.py`**: Parses OpenStreetMap data to understand road width, speed limits, and intersections.
- **`weather_context.py`**: Ingests live rainfall and weather conditions.
- **`event_context.py`**: Checks if there are major events (e.g., IPL matches, concerts) happening nearby.
- **`fetch_pois.py`**: Locates Points of Interest (hospitals, malls, schools) which attract parking.
- **`tomtom_api.py`**: Connects to the TomTom Traffic API to fetch real-time congestion data for top hotspots.

### Explainability & Visuals
- **`explain.py` & `explainability.py`**: Uses a mathematical framework called **SHAP** to explain the AI's black-box decisions. This translates complex ML math into human-readable sentences like "Violations happened here at this exact time last week" so the police trust the alert.
- **`kinematics.py`**: Generates the "Ripple Effect". If a main road is blocked, this script calculates how the traffic jam will spill over into neighboring streets, generating a visual blast radius.

## How it works (Step-by-Step)
1. **Data Ingestion**: Road geometry and live context (time, weather) are gathered (`features.py`).
2. **Prediction**: The CatBoost model predicts the exact count of cars, bikes, and trucks that will park illegally (`predict.py`).
3. **Physics & Scoring**: The predicted vehicles are placed on the road. If the road is 6m wide and cars take up 2m, the road is 33% choked. An EPS score is generated (`scoring.py`).
4. **Explainability**: SHAP determines *why* the model made this prediction (`explain.py`).
5. **Output**: Everything is bundled into a `predictions.geojson` file, ready for the backend to serve to the map.
