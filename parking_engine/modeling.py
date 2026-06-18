"""Model training, evaluation, persistence, and inference helpers."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import average_precision_score, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.multioutput import RegressorChain

from .config import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMNS
from .features import FeatureContext, add_features, apply_category_levels


def make_model(
    n_estimators: int = 350,
    learning_rate: float = 0.045,
    num_leaves: int = 63,
    random_state: int = 42,
) -> RegressorChain:
    """Create the multi-output LightGBM count forecaster using RegressorChain."""

    base = LGBMRegressor(
        objective="poisson",
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        subsample=0.88,
        colsample_bytree=0.88,
        reg_alpha=0.05,
        reg_lambda=0.35,
        min_child_samples=25,
        random_state=random_state,
        n_jobs=-1,
        verbosity=-1,
    )
    # The exact strict physical exclusion order requested:
    # 1: count_car, 0: count_two_wheeler, 4: count_heavy, 2: count_auto, 3: count_light_commercial, 5: count_other
    return RegressorChain(base, order=[1, 0, 4, 2, 3, 5], cv=5)


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

    X_train = features.loc[train_mask, FEATURE_COLUMNS]
    y_train = features.loc[train_mask, TARGET_COLUMNS].astype(float)
    X_test = features.loc[~train_mask, FEATURE_COLUMNS]
    y_test = features.loc[~train_mask, TARGET_COLUMNS].astype(float)

    model = make_model(n_estimators=n_estimators, random_state=random_state)
    model.fit(X_train, y_train)

    pred = np.clip(model.predict(X_test), 0.0, None)
    metrics = evaluate_predictions(y_test.to_numpy(dtype=float), pred)
    metrics["train_rows"] = int(len(X_train))
    metrics["test_rows"] = int(len(X_test))
    metrics["cutoff_hour"] = str(cutoff_hour)
    metrics["feature_columns"] = FEATURE_COLUMNS
    metrics["target_columns"] = TARGET_COLUMNS
    metrics["categorical_columns"] = CATEGORICAL_COLUMNS
    return model, metrics, features


def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, object]:
    """Count-model evaluation with per-target and aggregate metrics."""

    by_target = {}
    for idx, col in enumerate(TARGET_COLUMNS):
        true = y_true[:, idx]
        pred = y_pred[:, idx]
        mae = float(mean_absolute_error(true, pred))
        rmse = float(mean_squared_error(true, pred) ** 0.5)
        denom = max(1.0, float(np.abs(true).sum()))
        wape = float(np.abs(true - pred).sum() / denom)
        by_target[col] = {"mae": mae, "rmse": rmse, "wape": wape}

    true_total = y_true.sum(axis=1)
    pred_total = y_pred.sum(axis=1)
    total_mae = float(mean_absolute_error(true_total, pred_total))
    total_rmse = float(mean_squared_error(true_total, pred_total) ** 0.5)
    total_wape = float(np.abs(true_total - pred_total).sum() / max(1.0, np.abs(true_total).sum()))
    hotspot_metrics = _hotspot_ranking_metrics(true_total, pred_total)
    return {
        "total_mae": total_mae,
        "total_rmse": total_rmse,
        "total_wape": total_wape,
        **hotspot_metrics,
        "by_target": by_target,
    }


def _hotspot_ranking_metrics(true_total: np.ndarray, pred_total: np.ndarray) -> dict[str, float | None]:
    """Operational metrics for prioritizing enforcement queues."""

    has_violation = (true_total > 0).astype(int)
    metrics: dict[str, float | None] = {}
    if len(np.unique(has_violation)) == 2:
        metrics["hotspot_roc_auc"] = float(roc_auc_score(has_violation, pred_total))
        metrics["hotspot_average_precision"] = float(average_precision_score(has_violation, pred_total))
    else:
        metrics["hotspot_roc_auc"] = None
        metrics["hotspot_average_precision"] = None

    order = np.argsort(-pred_total)
    total_true = max(1.0, float(true_total.sum()))
    for pct in (0.01, 0.05, 0.10):
        k = max(1, int(len(order) * pct))
        captured = float(true_total[order[:k]].sum() / total_true)
        metrics[f"top_{int(pct * 100)}pct_violation_capture"] = captured
    return metrics


def predict_feature_frame(
    model: RegressorChain,
    feature_frame: pd.DataFrame,
    category_levels: dict[str, list[str]],
) -> pd.DataFrame:
    """Predict target columns for a prepared feature frame."""

    feature_frame = apply_category_levels(feature_frame, category_levels)
    predictions = np.clip(model.predict(feature_frame[FEATURE_COLUMNS]), 0.0, None)
    out = feature_frame.copy()
    for idx, col in enumerate(TARGET_COLUMNS):
        out[col] = predictions[:, idx]
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
