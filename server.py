import sqlite3
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import shap
import uvicorn
import os

from parking_engine.modeling import load_bundle, predict_feature_frame
from parking_engine.config import FEATURE_COLUMNS
from parking_engine.features import add_features, create_future_rows, create_location_row
from parking_engine.mappls_api import enrich_with_live_traffic
from parking_engine.scoring import score_predictions, write_geojson

# Module-level singleton for the LightGBM model
model_bundle = None
db_connection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_bundle, db_connection
    
    # Load LightGBM model into memory at startup
    model_path = "artifacts/parking_model_osm/model.joblib"
    if not os.path.exists(model_path):
        model_path = "artifacts/parking_model/model.joblib"
        
    print(f"Loading model from {model_path}...")
    model_bundle = load_bundle(model_path)
    
    # Initialize SQLite database with WAL mode
    db_path = "artifacts/feedback.sqlite"
    os.makedirs("artifacts", exist_ok=True)
    db_connection = sqlite3.connect(db_path, check_same_thread=False)
    db_connection.row_factory = sqlite3.Row
    db_connection.execute("PRAGMA journal_mode=WAL")
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS model_recalibration_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT,
            predicted_eps REAL,
            actual_accuracy TEXT,
            officer_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db_connection.commit()
    
    yield
    
    # Cleanup on shutdown
    if db_connection:
        db_connection.close()

app = FastAPI(lifespan=lifespan)

@app.get("/predict")
def predict_endpoint(datetime: str = Query(...), lat: Optional[float] = None, lon: Optional[float] = None, top_k: int = 25):
    try:
        context = model_bundle["context"]
        model = model_bundle["model"]
        target_hour = pd.Timestamp(datetime).floor("h")

        if lat is not None and lon is not None:
            base_rows = create_location_row(context, target_hour, lat, lon)
        else:
            base_rows = create_future_rows(context, target_hour)

        feature_frame = add_features(base_rows, context)
        predicted = predict_feature_frame(model, feature_frame, context.category_levels)
        
        target_cols = [c for c in predicted.columns if c.startswith("count_")]
        predicted["predicted_total"] = predicted[target_cols].sum(axis=1)
        
        live_multipliers = enrich_with_live_traffic(predicted)
        
        scored = score_predictions(
            predicted,
            calibration=model_bundle.get("calibration", {}),
            live_congestion_multiplier=live_multipliers,
        )
        top = scored.head(top_k).copy()
        
        # Convert to dictionary format or directly return
        # Since the frontend usually reads GeoJSON, we can return the top predictions as JSON records
        records = top.to_dict(orient="records")
        return {"status": "success", "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/explain")
def explain_endpoint(segment_id: str, target_hour: Optional[str] = "live"):
    try:
        model = model_bundle["model"]
        context = model_bundle.get("context")
        
        meta = context.segment_metadata
        seg_data = meta[meta["segment_id"] == segment_id]
        if seg_data.empty:
            raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found in model context.")
            
        row = {}
        for f in FEATURE_COLUMNS:
            row[f] = 0.0 # Default
            if f in seg_data.columns:
                row[f] = seg_data.iloc[0][f]
        
        df_features = pd.DataFrame([row])
        
        base_lgbm = model.estimators_[0] 
        
        explainer = shap.TreeExplainer(base_lgbm)
        shap_values = explainer.shap_values(df_features)
        
        vals = shap_values[0]
        feature_impacts = []
        for i, f_name in enumerate(FEATURE_COLUMNS):
            feature_impacts.append({"feature": f_name, "impact": float(vals[i])})
            
        feature_impacts.sort(key=lambda x: x["impact"], reverse=True)
        
        top_positive = feature_impacts[:3]
        top_negative = [f for f in feature_impacts if f["impact"] < 0]
        top_negative.sort(key=lambda x: x["impact"])
        top_negative = top_negative[:1]
        
        result = {
            "segment_id": segment_id,
            "target_hour": target_hour,
            "top_positive_contributors": top_positive,
            "top_negative_contributors": top_negative
        }
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FeedbackRequest(BaseModel):
    edge_id: str
    predicted_eps: float
    actual_accuracy: str
    officer_id: Optional[str] = "unknown"

@app.post("/feedback")
def feedback_endpoint(feedback: FeedbackRequest):
    try:
        cursor = db_connection.cursor()
        cursor.execute(
            "INSERT INTO model_recalibration_logs (edge_id, predicted_eps, actual_accuracy, officer_id) VALUES (?, ?, ?, ?)",
            (feedback.edge_id, feedback.predicted_eps, feedback.actual_accuracy, feedback.officer_id)
        )
        db_connection.commit()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
