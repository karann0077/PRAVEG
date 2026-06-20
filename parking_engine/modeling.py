"""Model training, evaluation, persistence, and inference helpers."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from catboost import CatBoostClassifier
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
        min_child_samples=40,
        min_split_gain=0.01,
        random_state=random_state,
        n_jobs=-1,
        verbosity=-1,
    )
    # The exact strict physical exclusion order requested:
    # 0: count_two_wheeler, 1: count_car, 2: count_auto, 3: count_light_commercial, 4: count_heavy, 5: count_other
    return RegressorChain(base, order=[0, 1, 2, 3, 4, 5], cv=5)


def make_catboost_classifier(
    n_iterations: int = 400,
    learning_rate: float = 0.05,
    random_state: int = 42,
) -> CatBoostClassifier:
    """V3: CatBoost binary classifier for hotspot probabilities."""
    return CatBoostClassifier(
        iterations=n_iterations,
        learning_rate=learning_rate,
        depth=6,
        eval_metric="AUC",
        loss_function="Logloss",
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
) -> tuple[RegressorChain, dict[str, object], pd.DataFrame]:
    """Build features, train the model, and return metrics."""

    features = add_features(training_rows, context)
    train_mask = features["target_hour"] < cutoff_hour
    if train_mask.sum() == 0 or (~train_mask).sum() == 0:
        train_mask = np.arange(len(features)) < int(len(features) * 0.8)

    X_train = features.loc[train_mask, FEATURE_COLUMNS].copy()
    for col in CATEGORICAL_COLUMNS:
        if col in X_train.columns and hasattr(X_train[col], "cat"):
            X_train[col] = X_train[col].cat.codes
    y_train_reg = features.loc[train_mask, TARGET_COLUMNS].astype(float)
    y_train_clf = features.loc[train_mask, "is_hotspot"].astype(int)
    
    # V3: Extract sample weight if present
    sample_weight = None
    if "sample_weight" in features.columns:
        sample_weight = features.loc[train_mask, "sample_weight"].to_numpy(dtype=float)

    X_test = features.loc[~train_mask, FEATURE_COLUMNS].copy()
    for col in CATEGORICAL_COLUMNS:
        if col in X_test.columns and hasattr(X_test[col], "cat"):
            X_test[col] = X_test[col].cat.codes
    y_test_reg = features.loc[~train_mask, TARGET_COLUMNS].astype(float)
    y_test_clf = features.loc[~train_mask, "is_hotspot"].astype(int)

    # ── 1. Train Regressor Chain (Model A) ──────────────────────────────────
    model_reg = make_model(n_estimators=n_estimators, random_state=random_state)
    
    # V4: Apply log1p transform to count targets for training
    y_train_reg_log = np.log1p(y_train_reg)
    
    if sample_weight is not None:
        model_reg.fit(X_train, y_train_reg_log, sample_weight=sample_weight)
    else:
        model_reg.fit(X_train, y_train_reg_log)
        
    # V4: Apply expm1 to predictions to revert to count space
    pred_reg = np.clip(np.expm1(model_reg.predict(X_test)), 0.0, None)

    # ── 2. Train CatBoost Classifier (Model B) & Isotonic Calibration ───────
    # We split train into sub-train and calibration (last 14 days of train set)
    train_dates = features.loc[train_mask, "target_hour"]
    calib_cutoff = train_dates.max() - pd.Timedelta(days=14)
    calib_mask = train_dates >= calib_cutoff
    sub_train_mask = ~calib_mask
    
    # Identify categorical indices for CatBoost
    cat_features_idx = [i for i, col in enumerate(FEATURE_COLUMNS) if col in CATEGORICAL_COLUMNS]

    model_clf = make_catboost_classifier(n_iterations=n_estimators, random_state=random_state)
    # CatBoost expects integers or strings for categorical columns. 
    # They are already cat.codes (integers)
    # We must ensure they are cast to int for CatBoost
    X_train_cb = X_train.copy()
    for col in CATEGORICAL_COLUMNS:
        X_train_cb[col] = X_train_cb[col].astype(int)
        
    X_sub_train = X_train_cb.loc[sub_train_mask]
    y_sub_train = y_train_clf.loc[sub_train_mask]
    w_sub_train = sample_weight[sub_train_mask] if sample_weight is not None else None
    
    model_clf.fit(X_sub_train, y_sub_train, cat_features=cat_features_idx, sample_weight=w_sub_train)

    # Calibrate on the held-out calibration set
    X_calib = X_train_cb.loc[calib_mask]
    y_calib = y_train_clf.loc[calib_mask]
    calib_probs = model_clf.predict_proba(X_calib)[:, 1]
    
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(calib_probs, y_calib)
    
    # ── Conformal Uncertainty (Enterprise Dispatch Rule) ─────────────────────
    # Calculate the empirical residual margin on the calibration set to provide
    # a probability lower bound. We want to be 85% confident in our lower bound.
    calibrated_calib_probs = calibrator.predict(calib_probs)
    residuals = y_calib - calibrated_calib_probs
    # 15th percentile of residuals gives us the conservative margin
    conformal_margin = float(np.quantile(residuals, 0.15))

    
    # Predict and evaluate on test set
    X_test_cb = X_test.copy()
    for col in CATEGORICAL_COLUMNS:
        X_test_cb[col] = X_test_cb[col].astype(int)
    pred_clf_raw = model_clf.predict_proba(X_test_cb)[:, 1]
    pred_clf_calibrated = calibrator.predict(pred_clf_raw)

    test_hours = features.loc[~train_mask, "target_hour"]

    metrics = evaluate_predictions(
        y_test_reg.to_numpy(dtype=float), 
        pred_reg, 
        y_test_clf.to_numpy(dtype=int), 
        pred_clf_calibrated,
        test_hours.to_numpy()
    )
    metrics["train_rows"] = int(len(X_train))
    metrics["test_rows"] = int(len(X_test))
    metrics["cutoff_hour"] = str(cutoff_hour)
    metrics["feature_columns"] = FEATURE_COLUMNS
    metrics["target_columns"] = TARGET_COLUMNS
    metrics["categorical_columns"] = CATEGORICAL_COLUMNS
    
    models = {
        "regressor": model_reg,
        "classifier": model_clf,
        "calibrator": calibrator,
        "conformal_margin": conformal_margin,
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
        # V4: Apply expm1 to predictions to revert to count space
        predictions = np.clip(np.expm1(model_reg.predict(X)), 0.0, None)
        for idx, col in enumerate(TARGET_COLUMNS):
            out[col] = predictions[:, idx]
            
    # V3 Ensemble logic
    model_clf = models.get("classifier")
    calibrator = models.get("calibrator")
    conformal_margin = models.get("conformal_margin", -0.15)  # Fallback margin if not present

    if model_clf is not None and calibrator is not None:
        prob_raw = model_clf.predict_proba(X_cb)[:, 1]
        prob_cal = calibrator.predict(prob_raw)
        out["hotspot_probability"] = prob_cal
        out["hotspot_probability_raw"] = prob_raw
        
        # Enterprise Dispatch Rule: Conformal Lower Bound
        # We guarantee with 85% confidence that the probability is at least this much
        lower_bound = np.clip(prob_cal + conformal_margin, 0.0, 1.0)
        out["hotspot_prob_lower_bound"] = lower_bound
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
