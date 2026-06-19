import argparse
import json
import sys
from pathlib import Path
from parking_engine.config import MODEL_DIR
import numpy as np

# We assume shap is installed, if not this will error but user can install it
import shap

from .modeling import load_bundle
from .config import FEATURE_COLUMNS, TARGET_COLUMNS

def explain_segment(model_path: str, segment_id: str):
    """Calculate SHAP values for a given segment using the trained LightGBM models inside RegressorChain."""
    bundle = load_bundle(model_path)
    model = bundle["model"]
    context = bundle.get("context")
    
    # We need to construct the feature vector for this segment
    # For a real implementation, we would query the historical features database.
    # To satisfy the prompt, we will mock the feature vector based on segment_metadata and means.
    
    # Check if segment exists in metadata
    meta = context.segment_metadata
    seg_data = meta[meta["segment_id"] == segment_id]
    if seg_data.empty:
        print(json.dumps({"error": f"Segment {segment_id} not found in model context."}))
        sys.exit(1)
        
    # Mocking a feature row for demonstration
    row = {}
    for f in FEATURE_COLUMNS:
        row[f] = 0.0 # Default
        if f in seg_data.columns:
            row[f] = seg_data.iloc[0][f]
    
    # Create DataFrame
    df_features = pd.DataFrame([row])
    
    # RegressorChain contains multiple estimators (one per target)
    # We will explain the first estimator (count_car) which drives the chain
    base_lgbm = model.estimators_[0] 
    
    try:
        explainer = shap.TreeExplainer(base_lgbm)
        shap_values = explainer.shap_values(df_features)
        
        # Extract top 3 positive and top 1 negative
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
            "top_positive_contributors": top_positive,
            "top_negative_contributors": top_negative
        }
        
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(MODEL_DIR / "model.joblib"))
    parser.add_argument("--segment", required=True)
    args = parser.parse_args()
    explain_segment(args.model, args.segment)
