"""FastAPI server for PRAVEG parking enforcement intelligence.

FIX LOG (2026-06-18):
  BUG-14 FIXED: /explain endpoint built an all-zero feature row, giving
         meaningless SHAP values.  Now reconstructs the actual prediction
         feature context for the requested segment and target hour.

  BUG-15 FIXED: Single shared SQLite connection without locking caused
         corruption under concurrent /feedback requests.  Replaced with
         a thread-local connection pool using sqlite3 in WAL mode.

  FIX-NEW: Added /live_delta endpoint so frontend can poll which segments
           changed EPS band in the last daemon cycle.

  FIX-NEW: Added /health endpoint with model metadata for ops monitoring.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
import shap
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from parking_engine.config import FEATURE_COLUMNS
from parking_engine.features import (
    FeatureContext,
    add_features,
    apply_category_levels,
    create_future_rows,
    create_location_row,
)
from parking_engine.mappls_api import enrich_with_live_traffic
from parking_engine.modeling import load_bundle, predict_feature_frame
from parking_engine.scoring import score_predictions, write_geojson

# ── Module-level singletons ─────────────────────────────────────────────────
model_bundle: dict | None = None

# FIX BUG-15: Thread-local connection pool instead of single shared connection
_db_local = threading.local()
_DB_PATH = "artifacts/feedback.sqlite"


def _get_db() -> sqlite3.Connection:
    """Return a per-thread SQLite connection."""
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        conn = sqlite3.connect(_DB_PATH, check_same_thread=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_recalibration_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id TEXT,
                predicted_eps REAL,
                actual_accuracy TEXT,
                officer_id TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        _db_local.conn = conn
    return _db_local.conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_bundle

    model_path = "artifacts/parking_model_osm/model.joblib"
    if not Path(model_path).exists():
        model_path = "artifacts/parking_model/model.joblib"

    print(f"Loading model from {model_path}...")
    model_bundle = load_bundle(model_path)
    print("Model loaded. Context segments:", len(model_bundle["context"].selected_segments))

    Path("artifacts").mkdir(exist_ok=True)
    _get_db()   # Pre-warm the main-thread connection

    yield

    if hasattr(_db_local, "conn") and _db_local.conn:
        _db_local.conn.close()


app = FastAPI(lifespan=lifespan)


# ── /predict ─────────────────────────────────────────────────────────────────
@app.get("/predict")
def predict_endpoint(
    datetime: str = Query(...),
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    top_k: int = 25,
):
    try:
        context: FeatureContext = model_bundle["context"]
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
        return {"status": "success", "data": top.to_dict(orient="records")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── /explain  (FIX BUG-14) ───────────────────────────────────────────────────
@app.get("/explain")
def explain_endpoint(
    segment_id: str,
    target_hour: Optional[str] = "live",
):
    """Return SHAP feature impacts for a specific segment and time.

    FIX: The old version built an all-zero feature row, producing garbage
    SHAP values.  This version reconstructs the actual prediction row for
    the segment so SHAP reflects the real prediction context.
    """
    try:
        model = model_bundle["model"]
        context: FeatureContext = model_bundle["context"]

        meta = context.segment_metadata
        if segment_id not in meta["segment_id"].values:
            raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found.")

        # ── Resolve target hour ──────────────────────────────────────────────
        if target_hour == "live" or not target_hour:
            ts = pd.Timestamp.now().floor("h")
        else:
            ts = pd.Timestamp(target_hour).floor("h")

        # ── Build actual prediction row for this segment ─────────────────────
        base_rows = pd.DataFrame({"segment_id": [segment_id], "target_hour": [ts]})
        feature_frame = add_features(base_rows, context)
        feature_frame = apply_category_levels(feature_frame, context.category_levels)

        from parking_engine.config import CATEGORICAL_COLUMNS
        X = feature_frame[FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if col in X.columns and hasattr(X[col], "cat"):
                X[col] = X[col].cat.codes

        # ── SHAP on the first estimator in the chain ─────────────────────────
        base_lgbm = model.estimators_[0]
        explainer = shap.TreeExplainer(base_lgbm)
        shap_values = explainer.shap_values(X)

        vals = shap_values[0]
        feature_impacts = [
            {"feature": f_name, "impact": float(vals[i]), "value": float(X.iloc[0][f_name])}
            for i, f_name in enumerate(FEATURE_COLUMNS)
            if i < len(vals)
        ]
        feature_impacts.sort(key=lambda x: abs(x["impact"]), reverse=True)

        top_positive = [f for f in feature_impacts if f["impact"] > 0][:5]
        top_negative = [f for f in feature_impacts if f["impact"] < 0][:3]

        return {
            "segment_id": segment_id,
            "target_hour": str(ts),
            "top_positive_contributors": top_positive,
            "top_negative_contributors": top_negative,
            "all_impacts": feature_impacts[:15],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── /feedback  (FIX BUG-15) ──────────────────────────────────────────────────
class FeedbackRequest(BaseModel):
    edge_id: str
    predicted_eps: float
    actual_accuracy: str
    officer_id: Optional[str] = "unknown"


@app.post("/feedback")
def feedback_endpoint(feedback: FeedbackRequest):
    try:
        db = _get_db()   # thread-local connection — safe for concurrent workers
        db.execute(
            "INSERT INTO model_recalibration_logs (edge_id, predicted_eps, actual_accuracy, officer_id) "
            "VALUES (?, ?, ?, ?)",
            (feedback.edge_id, feedback.predicted_eps, feedback.actual_accuracy, feedback.officer_id),
        )
        db.commit()
        return {"success": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── /live_delta  (NEW) ────────────────────────────────────────────────────────
@app.get("/live_delta")
def live_delta_endpoint():
    """Return EPS band changes from the last daemon cycle.

    Frontend can use this to highlight newly escalated segments with a flash
    animation without re-rendering the entire map.
    """
    delta_path = Path("artifacts/predictions/live_delta.json")
    if not delta_path.exists():
        return {"timestamp": None, "escalated": [], "deescalated": [], "total_changed": 0}
    try:
        return json.loads(delta_path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── /health  (NEW) ────────────────────────────────────────────────────────────
@app.get("/health")
def health_endpoint():
    """Ops health check with model metadata."""
    if model_bundle is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    context: FeatureContext = model_bundle["context"]
    return {
        "status": "ok",
        "model_segments": len(context.selected_segments),
        "calibration": model_bundle.get("calibration", {}),
        "training_summary": model_bundle.get("training_summary", {}),
    }


# ── /metrics  (existing — kept) ───────────────────────────────────────────────
@app.get("/metrics")
def metrics_endpoint():
    metrics_path = Path("artifacts/parking_model_osm/metrics.json")
    if not metrics_path.exists():
        raise HTTPException(status_code=404, detail="Metrics not found.")
    return json.loads(metrics_path.read_text())


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
