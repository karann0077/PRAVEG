"""Model training, evaluation, persistence, and inference helpers."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from catboost import CatBoostClassifier, CatBoostRanker, Pool
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, mean_absolute_error, mean_squared_error, roc_auc_score, log_loss, brier_score_loss, ndcg_score
from sklearn.multioutput import RegressorChain

from .config import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMNS
from .features import FeatureContext, add_features, apply_category_levels


def make_model(
    n_estimators: int = 400,
    learning_rate: float = 0.04,
    num_leaves: int = 47,
    random_state: int = 42,
) -> RegressorChain:
    """Create the multi-output LightGBM count forecaster using RegressorChain.

    Hyperparameter tuning notes (v2):
    - num_leaves reduced 63→47: fewer leaves reduces overfitting on zero-heavy data.
    - min_child_samples raised 25→40: requires more evidence before splitting.
    - min_split_gain added: prevents splits that don't meaningfully reduce loss.
    - n_estimators raised 350→400 to compensate for slower learning from above.
    """

    base = LGBMRegressor(
        objective="poisson",
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.08,
        reg_lambda=0.5,
        min_child_samples=20,   # V5: reduced from 40 → 20 to handle sparser segments
        min_split_gain=0.01,
        random_state=random_state,
        n_jobs=-1,
        verbosity=-1,
    )
    # The exact strict physical exclusion order requested:
    # 0: count_two_wheeler, 1: count_car, 2: count_auto, 3: count_light_commercial, 4: count_heavy, 5: count_other
    return RegressorChain(base, order=[0, 1, 2, 3, 4, 5], cv=5)


def make_catboost_ranker(
    n_iterations: int = 400,
    learning_rate: float = 0.05,
    random_state: int = 42,
) -> CatBoostRanker:
    """V5: CatBoost learning-to-rank model for dispatch priority.
    
    Optimizes for YetiRank listwise loss grouped by hour.
    """
    return CatBoostRanker(
        iterations=n_iterations,
        learning_rate=learning_rate,
        depth=6,
        loss_function="YetiRank",
        random_seed=random_state,
        verbose=False,
        thread_count=-1,
    )


def train_model(
    training_rows: pd.DataFrame,
    context: FeatureContext,
    cutoff_hour: pd.Timestamp,
    n_estimators: int,
    random_state: int,
) -> tuple[dict[str, object], dict[str, object], pd.DataFrame]:
    """Build features, train the model, and return metrics."""

    features = add_features(training_rows, context)
    time_train_mask = features["target_hour"] < cutoff_hour
    if time_train_mask.sum() == 0 or (~time_train_mask).sum() == 0:
        time_train_mask = np.arange(len(features)) < int(len(features) * 0.8)

    # ── 1. Create Spatial Holdout (20% of police stations) ──
    unique_stations = features["police_station"].unique()
    np.random.seed(random_state)
    n_holdout = max(1, int(len(unique_stations) * 0.2))
    test_stations = set(np.random.choice(unique_stations, n_holdout, replace=False))
    space_test_mask = features["police_station"].isin(test_stations)

    # ── 2. Define Quadrants ──
    quad_a_mask = time_train_mask & ~space_test_mask  # Train Space & Time
    quad_b_mask = ~time_train_mask & ~space_test_mask # Temporal Holdout
    quad_c_mask = time_train_mask & space_test_mask   # Spatial Holdout
    quad_d_mask = ~time_train_mask & space_test_mask  # Spatiotemporal Holdout

    def _fit_models(fit_mask):
        X_train = features.loc[fit_mask, FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if col in X_train.columns and hasattr(X_train[col], "cat"):
                X_train[col] = X_train[col].cat.codes.astype(int)
            elif col in X_train.columns:
                X_train[col] = X_train[col].astype(int)
                
        y_train_reg = features.loc[fit_mask, TARGET_COLUMNS].astype(float)
        
        # Ranker target
        features_fit = features.loc[fit_mask].copy()
        features_fit = features_fit.sort_values(by="target_hour").reset_index(drop=True)
        X_train_cb = features_fit[FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if col in X_train_cb.columns:
                if hasattr(X_train_cb[col], "cat"):
                    X_train_cb[col] = X_train_cb[col].cat.codes.astype(int)
                else:
                    X_train_cb[col] = X_train_cb[col].astype(int)
                    
        y_train_rank = pd.cut(
            features_fit["severity_weighted_count"], 
            bins=[-np.inf, 2.0, 10.0, 30.0, np.inf], 
            labels=[0, 1, 2, 3]
        ).astype(float).fillna(0).to_numpy()
        
        group_id_train = features_fit["target_hour"].astype("category").cat.codes.astype(int).to_numpy()
        cat_features_idx = [i for i, col in enumerate(FEATURE_COLUMNS) if col in CATEGORICAL_COLUMNS]

        model_reg = make_model(n_estimators=n_estimators, random_state=random_state)
        w_fit = features.loc[fit_mask, "sample_weight"].to_numpy(dtype=float) if "sample_weight" in features.columns else None
        if w_fit is not None:
            model_reg.fit(X_train, y_train_reg, sample_weight=w_fit)
        else:
            model_reg.fit(X_train, y_train_reg)

        model_rank = make_catboost_ranker(n_iterations=n_estimators, random_state=random_state)
        train_pool = Pool(
            data=X_train_cb,
            label=y_train_rank,
            group_id=group_id_train,
            cat_features=cat_features_idx
        )
        model_rank.fit(train_pool)
        return model_reg, model_rank

    # ── 3. Train Evaluation Model on Quadrant A ──
    print(f"Training Evaluation Model (Holdout {len(test_stations)} stations)...")
    eval_model_reg, eval_model_rank = _fit_models(quad_a_mask)

    def _eval_on(eval_mask):
        if eval_mask.sum() == 0:
            return {}
        X_eval = features.loc[eval_mask, FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if hasattr(X_eval[col], "cat"):
                X_eval[col] = X_eval[col].cat.codes.astype(int)
            else:
                X_eval[col] = X_eval[col].astype(int)
                
        y_eval_reg = features.loc[eval_mask, TARGET_COLUMNS].astype(float)
        y_eval_clf = features.loc[eval_mask, "is_hotspot"].astype(int)
        
        pred_reg = np.clip(eval_model_reg.predict(X_eval), 0.0, None)
        pred_rank_raw = eval_model_rank.predict(X_eval)
        pred_clf_calibrated = 1.0 / (1.0 + np.exp(-pred_rank_raw))
        
        test_hours = features.loc[eval_mask, "target_hour"]
        
        return evaluate_predictions(
            y_eval_reg.to_numpy(dtype=float),
            pred_reg,
            y_eval_clf.to_numpy(dtype=int),
            pred_clf_calibrated,
            test_hours.to_numpy()
        )

    print("Evaluating quadrants...")
    metrics = {
        "temporal_holdout": _eval_on(quad_b_mask),
        "spatial_holdout": _eval_on(quad_c_mask),
        "spatiotemporal_holdout": _eval_on(quad_d_mask),
        "train_rows": int(quad_a_mask.sum()),
        "cutoff_hour": str(cutoff_hour),
        "test_stations_held_out": list(test_stations),
        "feature_columns": FEATURE_COLUMNS,
        "target_columns": TARGET_COLUMNS,
        "categorical_columns": CATEGORICAL_COLUMNS,
    }

    # ── 4. Train Production Model on ALL Space ──
    print("Training Production Model (100% stations)...")
    prod_model_reg, prod_model_rank = _fit_models(time_train_mask)
    
    models = {
        "regressor": prod_model_reg,
        "classifier": prod_model_rank,
        "conformal_margin": 0.0,
    }
    return models, metrics, features


def evaluate_predictions(
    y_true_reg: np.ndarray, 
    y_pred_reg: np.ndarray,
    y_true_clf: np.ndarray,
    y_pred_clf_prob: np.ndarray,
    target_hours: np.ndarray | None = None,
) -> dict[str, object]:
    """Count-model evaluation with per-target and aggregate metrics, plus binary classifier metrics."""

    by_target = {}
    for idx, col in enumerate(TARGET_COLUMNS):
        true = y_true_reg[:, idx]
        pred = y_pred_reg[:, idx]
        mae = float(mean_absolute_error(true, pred))
        rmse = float(mean_squared_error(true, pred) ** 0.5)
        denom = max(1.0, float(np.abs(true).sum()))
        wape = float(np.abs(true - pred).sum() / denom)
        by_target[col] = {"mae": mae, "rmse": rmse, "wape": wape}

    true_total = y_true_reg.sum(axis=1)
    pred_total = y_pred_reg.sum(axis=1)
    total_mae = float(mean_absolute_error(true_total, pred_total))
    total_rmse = float(mean_squared_error(true_total, pred_total) ** 0.5)
    total_wape = float(np.abs(true_total - pred_total).sum() / max(1.0, np.abs(true_total).sum()))
    
    # Binary classification metrics
    clf_metrics = {}
    if len(np.unique(y_true_clf)) == 2:
        clf_metrics["hotspot_roc_auc"] = float(roc_auc_score(y_true_clf, y_pred_clf_prob))
        clf_metrics["hotspot_average_precision"] = float(average_precision_score(y_true_clf, y_pred_clf_prob))
        clf_metrics["hotspot_logloss"] = float(log_loss(y_true_clf, y_pred_clf_prob))
        clf_metrics["hotspot_brier"] = float(brier_score_loss(y_true_clf, y_pred_clf_prob))

    # Hotspot ranking metrics using the probabilities instead of pure counts
    order = np.argsort(-y_pred_clf_prob)
    total_true = max(1.0, float(true_total.sum()))
    for pct in (0.01, 0.05, 0.10):
        k = max(1, int(len(order) * pct))
        captured = float(true_total[order[:k]].sum() / total_true)
        clf_metrics[f"top_{int(pct * 100)}pct_violation_capture"] = captured

    # ── Phase 4: Decision-focused Evaluation (Per-Hour Metrics) ──────────────
    if target_hours is not None:
        df = pd.DataFrame({
            'hour': target_hours,
            'true_total': true_total,
            'true_hotspot': y_true_clf,
            'prob': y_pred_clf_prob
        })
        
        k_values = [10, 25, 50]
        precisions = {k: [] for k in k_values}
        ndcgs = {k: [] for k in k_values}
        fdrs = {k: [] for k in k_values}
        
        for _, group in df.groupby('hour'):
            if len(group) < max(k_values):
                continue
                
            y_true_h = group['true_hotspot'].to_numpy()
            y_prob_h = group['prob'].to_numpy()
            true_total_h = group['true_total'].to_numpy()
            order_h = np.argsort(-y_prob_h)
            
            for k in k_values:
                top_k_idx = order_h[:k]
                precisions[k].append(np.mean(y_true_h[top_k_idx]))
                fdrs[k].append(np.mean(true_total_h[top_k_idx] == 0))
                try:
                    ndcgs[k].append(ndcg_score([true_total_h], [y_prob_h], k=k))
                except ValueError:
                    pass
                    
        for k in k_values:
            if precisions[k]:
                clf_metrics[f"precision_at_{k}"] = float(np.mean(precisions[k]))
                clf_metrics[f"ndcg_at_{k}"] = float(np.mean(ndcgs[k]))
                clf_metrics[f"false_dispatch_rate_at_{k}"] = float(np.mean(fdrs[k]))

    return {
        "total_mae": total_mae,
        "total_rmse": total_rmse,
        "total_wape": total_wape,
        **clf_metrics,
        "by_target": by_target,
    }


def predict_feature_frame(
    models: dict[str, object],
    feature_frame: pd.DataFrame,
    category_levels: dict[str, list[str]],
) -> pd.DataFrame:
    """Predict target columns for a prepared feature frame using the ensemble."""

    feature_frame = apply_category_levels(feature_frame, category_levels)
    X = feature_frame[FEATURE_COLUMNS].copy()
    
    for col in CATEGORICAL_COLUMNS:
        if col in X.columns and hasattr(X[col], "cat"):
            X[col] = X[col].cat.codes
            
    X_cb = X.copy()
    for col in CATEGORICAL_COLUMNS:
        if col in X_cb.columns:
            X_cb[col] = X_cb[col].astype(int)
            
    if not isinstance(models, dict):
        model_reg = models
        models = {}
    else:
        model_reg = models.get("regressor") or models.get("model") # Fallback to "model" for legacy bundles
    
    out = feature_frame.copy()
    if model_reg is not None:
        predictions = np.clip(model_reg.predict(X), 0.0, None)
        for idx, col in enumerate(TARGET_COLUMNS):
            out[col] = predictions[:, idx]
            
    # V3 Ensemble logic (now a Ranker)
    model_clf = models.get("classifier")
    
    if model_clf is not None:
        try:
            # Check if it's the old classifier or the new ranker
            if hasattr(model_clf, "predict_proba"):
                prob_raw = model_clf.predict_proba(X_cb)[:, 1]
                prob_cal = models.get("calibrator").predict(prob_raw) if models.get("calibrator") else prob_raw
                out["hotspot_probability"] = prob_cal
                out["hotspot_probability_raw"] = prob_raw
                out["hotspot_prob_lower_bound"] = prob_cal
            else:
                # It's the new Ranker
                pred_rank_raw = model_clf.predict(X_cb)
                # Global Sigmoid Calibration
                prob_cal = 1.0 / (1.0 + np.exp(-pred_rank_raw))
                out["hotspot_probability"] = prob_cal
                out["hotspot_probability_raw"] = pred_rank_raw
                out["hotspot_prob_lower_bound"] = prob_cal  # No conformal bound for ranker
        except Exception as e:
            print("Error in ranking prediction:", e)
            out["hotspot_probability"] = 0.0
            out["hotspot_probability_raw"] = 0.0
            out["hotspot_prob_lower_bound"] = 0.0
    else:
        out["hotspot_probability"] = 0.0
        out["hotspot_probability_raw"] = 0.0
        out["hotspot_prob_lower_bound"] = 0.0
        
    return out


def save_bundle(bundle: dict[str, object], out_dir: str | Path) -> Path:
    """Persist trained model and human-readable artifact sidecars."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "model.joblib"
    joblib.dump(bundle, model_path)

    metrics = bundle.get("metrics", {})
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    context = bundle["context"]
    if isinstance(context, FeatureContext):
        context.segment_metadata.to_csv(out / "segment_metadata.csv", index=False)
    config = {
        "feature_columns": FEATURE_COLUMNS,
        "target_columns": TARGET_COLUMNS,
        "categorical_columns": CATEGORICAL_COLUMNS,
        "calibration": bundle.get("calibration", {}),
        "training_summary": bundle.get("training_summary", {}),
    }
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return model_path


def load_bundle(model_path: str | Path) -> dict[str, object]:
    """Load a persisted model bundle."""

    return joblib.load(model_path)
