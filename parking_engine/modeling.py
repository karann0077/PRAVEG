"""Model training, evaluation, persistence, and inference helpers."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from catboost import CatBoostRanker, Pool
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
    
    if sample_weight is not None:
        model_reg.fit(X_train, y_train_reg, sample_weight=sample_weight)
    else:
        model_reg.fit(X_train, y_train_reg)
        
    pred_reg = np.clip(model_reg.predict(X_test), 0.0, None)

    # ── 2. Train CatBoost Ranker (Model B) ──────────────────────────────────
    # We group by target_hour and use bucketed severity as the ranking target
    features_train = features.loc[train_mask].copy()
    features_train = features_train.sort_values(by="target_hour").reset_index(drop=True)
    
    X_train_cb = features_train[FEATURE_COLUMNS].copy()
    for col in CATEGORICAL_COLUMNS:
        if col in X_train_cb.columns:
            if hasattr(X_train_cb[col], "cat"):
                X_train_cb[col] = X_train_cb[col].cat.codes.astype(int)
            else:
                X_train_cb[col] = X_train_cb[col].astype(int)
                
    # Target for ranker: bucketed severity (0=low, 1=watchlist, 2=high, 3=critical)
    y_train_rank = pd.cut(
        features_train["severity_weighted_count"], 
        bins=[-np.inf, 2.0, 10.0, 30.0, np.inf], 
        labels=[0, 1, 2, 3]
    ).astype(float).fillna(0).to_numpy()
    
    group_id_train = features_train["target_hour"].astype("category").cat.codes.astype(int).to_numpy()
    w_train = features_train["sample_weight"].to_numpy(dtype=float) if "sample_weight" in features_train.columns else None

    cat_features_idx = [i for i, col in enumerate(FEATURE_COLUMNS) if col in CATEGORICAL_COLUMNS]

    model_rank = make_catboost_ranker(n_iterations=n_estimators, random_state=random_state)
    
    train_pool = Pool(
        data=X_train_cb,
        label=y_train_rank,
        group_id=group_id_train,
        cat_features=cat_features_idx
    )
    
    model_rank.fit(train_pool)

    # ── True Out-of-Fold Platt Scaling (fixes in-sample calibration leakage) ─
    # PROBLEM: Fitting LogisticRegression on scores from a ranker that was already
    # trained on those same examples is in-sample calibration — the LR is fitting
    # to memorized scores, not genuine probability estimates. This causes the
    # calibrated probabilities to be overconfident and poorly generalised.
    #
    # FIX: Two-phase approach:
    #   Phase 1 — train a "calibration ranker" on [all train EXCEPT last 14 days],
    #              get its predictions on the held-out 14 days (true OOF scores).
    #   Phase 2 — fit LogisticRegression on those clean OOF (segment, label) pairs.
    #   Final    — retrain the production ranker on ALL train data (more data = better
    #              ranking). Use the OOF-fitted calibrator with this final ranker.
    #
    # Why this works: the calibration ranker and the production ranker share the same
    # feature space and similar score distributions, so the LR mapping learned from
    # OOF scores transfers reliably to the production ranker's outputs.

    from sklearn.linear_model import LogisticRegression

    conformal_margin = 0.0
    calib_cutoff = cutoff_hour - pd.Timedelta(days=14)

    # ── Phase 1: True OOF calibration ───────────────────────────────────────
    train_proper_mask = train_mask & (features["target_hour"] < calib_cutoff)
    calib_mask = train_mask & (features["target_hour"] >= calib_cutoff)

    # Fallback: if either window is empty (tiny dataset), skip OOF and use full set
    use_oof = (train_proper_mask.sum() > 0) and (calib_mask.sum() > 0)

    calibrator = LogisticRegression(random_state=random_state)

    if use_oof:
        print(f"  OOF Platt calibration: training calibration ranker on "
              f"{train_proper_mask.sum()} rows, calibrating on "
              f"{calib_mask.sum()} held-out rows...")

        # Build calibration ranker training pool (train_proper_mask only)
        ft_proper = features.loc[train_proper_mask].copy()
        ft_proper = ft_proper.sort_values(by="target_hour").reset_index(drop=True)
        X_proper_cb = ft_proper[FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if hasattr(X_proper_cb[col], "cat"):
                X_proper_cb[col] = X_proper_cb[col].cat.codes.astype(int)
            else:
                X_proper_cb[col] = X_proper_cb[col].astype(int)

        y_proper_rank = pd.cut(
            ft_proper["severity_weighted_count"],
            bins=[-np.inf, 2.0, 10.0, 30.0, np.inf],
            labels=[0, 1, 2, 3]
        ).astype(float).fillna(0).to_numpy()

        group_id_proper = ft_proper["target_hour"].astype("category").cat.codes.astype(int).to_numpy()

        calib_ranker = make_catboost_ranker(n_iterations=n_estimators, random_state=random_state)
        calib_pool = Pool(
            data=X_proper_cb,
            label=y_proper_rank,
            group_id=group_id_proper,
            cat_features=cat_features_idx
        )
        calib_ranker.fit(calib_pool)

        # Get OOF scores on the held-out 14 days — zero leakage
        X_calib_oof = features.loc[calib_mask, FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if hasattr(X_calib_oof[col], "cat"):
                X_calib_oof[col] = X_calib_oof[col].cat.codes.astype(int)
            else:
                X_calib_oof[col] = X_calib_oof[col].astype(int)

        y_calib_clf = features.loc[calib_mask, "is_hotspot"].astype(int).to_numpy()
        calib_scores_oof = calib_ranker.predict(X_calib_oof).reshape(-1, 1)

        if len(np.unique(y_calib_clf)) > 1:
            calibrator.fit(calib_scores_oof, y_calib_clf)
            print(f"  OOF Platt calibrator fitted: coef={calibrator.coef_[0][0]:.4f}, "
                  f"intercept={calibrator.intercept_[0]:.4f}")
        else:
            # Safety: calibration window is all-positive or all-negative
            print("  WARNING: calibration window has only one class — using identity sigmoid fallback")
            calibrator.classes_ = np.array([0, 1])
            calibrator.coef_ = np.array([[1.0]])
            calibrator.intercept_ = np.array([0.0])
    else:
        # Fallback for tiny datasets: keep in-sample (better than crashing)
        print("  WARNING: insufficient data for OOF calibration — falling back to in-sample Platt scaling")
        ft_all = features.loc[train_mask].copy()
        X_calib_fb = ft_all[FEATURE_COLUMNS].copy()
        for col in CATEGORICAL_COLUMNS:
            if hasattr(X_calib_fb[col], "cat"):
                X_calib_fb[col] = X_calib_fb[col].cat.codes.astype(int)
            else:
                X_calib_fb[col] = X_calib_fb[col].astype(int)
        y_calib_clf = ft_all["is_hotspot"].astype(int).to_numpy()
        fb_scores = model_rank.predict(X_calib_fb).reshape(-1, 1)
        if len(np.unique(y_calib_clf)) > 1:
            calibrator.fit(fb_scores, y_calib_clf)
        else:
            calibrator.classes_ = np.array([0, 1])
            calibrator.coef_ = np.array([[1.0]])
            calibrator.intercept_ = np.array([0.0])

    # ── Predict and evaluate on test set ─────────────────────────────────────
    X_test_cb = X_test.copy()
    for col in CATEGORICAL_COLUMNS:
        X_test_cb[col] = X_test_cb[col].astype(int)

    pred_rank_raw = model_rank.predict(X_test_cb).reshape(-1, 1)
    pred_clf_calibrated = calibrator.predict_proba(pred_rank_raw)[:, 1]

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
        "classifier": model_rank,
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
        predictions = np.clip(model_reg.predict(X), 0.0, None)
        for idx, col in enumerate(TARGET_COLUMNS):
            out[col] = predictions[:, idx]
            
    # V5 Learning-to-Rank logic
    model_rank = models.get("ranker") or models.get("classifier") # Fallback to classifier for legacy compatibility
    
    if model_rank is not None:
        try:
            # Ranker inference
            pred_rank_raw = model_rank.predict(X_cb).reshape(-1, 1)
            calibrator = models.get("calibrator")
            if calibrator is not None:
                prob_cal = calibrator.predict_proba(pred_rank_raw)[:, 1]
            else:
                prob_cal = 1.0 / (1.0 + np.exp(-pred_rank_raw.flatten()))
                
            out["priority_score_calibrated"] = prob_cal
            out["priority_score_raw"] = pred_rank_raw.flatten()
        except Exception as e:
            print("Error in ranking prediction:", e)
            out["priority_score_calibrated"] = 0.0
            out["priority_score_raw"] = 0.0
    else:
        out["priority_score_calibrated"] = 0.0
        out["priority_score_raw"] = 0.0
        
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
