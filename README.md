# PRAVEG - AI-Powered Traffic & Parking Enforcement Intelligence

![Praveg Engine](https://img.shields.io/badge/PRAVEG-Intelligence_Engine-blue?style=for-the-badge) ![Version](https://img.shields.io/badge/version-v5.0-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

**PRAVEG** is a state-of-the-art predictive enforcement and spatial-intelligence system built for the Bengaluru Traffic Police. It solves one of the city's most crippling problems: **illegal parking leading to cascading traffic gridlocks**. 

Instead of merely reacting to public complaints, PRAVEG uses machine learning to **proactively forecast where and when** parking violations will occur. It calculates the remaining physical capacity of the road, integrates live congestion data, and dispatches enforcement units *before* an irreversible traffic jam forms.

---

## 🌟 How Everything Works (The Workflow)

1. **Data Ingestion & Spatial Snapping**
   The system starts with historical police violation records. Instead of treating these as arbitrary GPS coordinates, PRAVEG uses the OpenStreetMap (OSM) Overpass API to snap every violation to its exact, physical road segment (e.g., "Subedar Chatram Road"). 
2. **Feature Engineering**
   The ML engine extracts over 140 features for every road segment. This includes time-of-day cyclical patterns, day-of-week trends, weather patterns (Open-Meteo API), and proximity to Points of Interest (POIs like metro stations, malls, and schools). It also uses **Hawkes Processes** to calculate "spillovers" (how a bottleneck on one street quickly causes parking violations on an adjacent street).
3. **Multi-Target Prediction**
   A sophisticated **CatBoost Regressor Chain** predicts the exact volume of violations that will occur in the next hour, split by vehicle type (two-wheelers, cars, heavy vehicles, etc.).
4. **Physical Interruption Scoring**
   The system calculates the total physical footprint of the predicted illegally parked vehicles (e.g., a car is 1.9m wide). It compares this against the known width of the street to determine the **Traffic Interruption Score**. 3 illegally parked cars on a narrow 6m residential street creates a massive interruption, whereas 3 cars on a 15m highway creates minimal interruption.
5. **Live Congestion Integration**
   A background daemon constantly polls the **TomTom Routing API**. If PRAVEG predicts a high parking risk, and TomTom reports that traffic speeds on that exact street are dropping in real-time, the threat is instantly escalated.
6. **Actionable UI**
   All this data feeds into a stunning Next.js / Deck.gl interactive map. Sector commanders see glowing red/orange lines over the exact streets at risk, allowing them to dispatch towing units efficiently.

---

## 🏗 System Architecture

PRAVEG operates via a decoupled, microservices-style architecture that seamlessly fuses Data Science, Backend APIs, and a 3D Frontend:

### 1. The ML Engine (`parking_engine/`)
The brain of the system. Written in Python, this module houses the data pipelines. 
* **`train.py`**: Handles OSM road matching, feature generation, and trains the CatBoost model.
* **`predict.py`**: Uses the trained model bundle to project 24 hours into the future, creating "Time Machine" ripples.

### 2. Live Traffic Daemon (`live_traffic_daemon.py`)
A continuous Python background worker. Every 5 minutes, it:
* Wakes up and queries live weather.
* Queries the TomTom Routing API for current travel times on high-risk roads.
* Feeds this live data through the CatBoost model to calculate the current "Live EPS" (Enforcement Priority Score).
* Saves the output to a fast SQLite WAL database.

### 3. FastAPI Backend (`server.py`)
A lightning-fast ASGI server that acts as the bridge between the ML engine and the Frontend.
* Serves the live GeoJSON artifacts.
* Exposes an `/explain` endpoint that calculates **SHAP values** on-the-fly, telling the frontend exactly *why* a specific street is flagged as high-risk (e.g., "High Metro Station Proximity").

### 4. Next.js 3D Frontend (`frontend/`)
A cutting-edge React 19 / Next.js 15 application.
* Uses **Mapbox GL JS** and **Deck.gl** to render hundreds of thousands of data points and road vectors at 60FPS in 3D.
* Features a "Tactical Map", a "Dispatch Queue", and a "Time Machine" slider to view future predictions.

---

## 🚦 The Enforcement Priority Score (EPS)

PRAVEG translates complex ML arrays into a single, actionable number for police officers: the **Enforcement Priority Score (0 to 100)**.

The EPS is grouped into four distinct operational bands:
- 🔴 **Red Line (EPS > 85):** Immediate dispatch required. A gridlock is imminent.
- 🟠 **Orange Line (EPS 60-84):** Preventative dispatch. Congestion is building rapidly.
- 🟡 **Watchlist (EPS 40-59):** Monitor via CCTV. Do not dispatch yet.
- 🟢 **Low (EPS < 40):** Stand down. No major parking risk.

---

## 🚀 Quick Start Guide (For Reviewers)

To meet the 50MB upload limits, we have excluded the massive training dataset and historical 24-hour cache files. However, **the pre-trained model (`artifacts/parking_model_v5`) and the Live Prediction cache are pre-packaged!**

### 1. Run the Live Map (No Python Setup Required)
You can view the fully operational UI immediately using the pre-cached live data.

```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` to interact with the Tactical Map and Dispatch Queue!

### 2. Full Pipeline Recreation (Optional)
If you wish to train the model from scratch and generate the 24-hour Time Machine ripples:
1. Place the hackathon dataset `csv` into the `dataset/` folder.
2. Install Python dependencies: `pip install -r requirements.txt`.
3. Train the model: `make train`.
4. Generate the 24-hour prediction ripples: `make predict`.
5. Start the Live Daemon and Backend:
   ```bash
   python server.py &
   python live_traffic_daemon.py &
   ```
6. Start the frontend as shown in Step 1.

---

## 🛠 Tech Stack

- **Machine Learning:** CatBoost, scikit-learn, SHAP, Pandas, Numpy.
- **Geospatial Processing:** Shapely, OSM Overpass API, Haversine routing.
- **Backend:** FastAPI, Uvicorn, SQLite.
- **Frontend:** Next.js 15, React 19, Deck.gl, Mapbox GL JS, TailwindCSS, Framer Motion.
- **APIs:** TomTom Routing API, Open-Meteo Weather API.

---

*Developed for the Bengaluru Traffic Police Hackathon.*
