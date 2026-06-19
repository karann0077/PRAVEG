"""On-demand feature contribution explanations for one segment-hour."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMNS
from .features import FeatureContext, add_features, apply_category_levels
from .modeling import load_bundle, predict_feature_frame


from parking_engine.config import MODEL_DIR
DEFAULT_MODEL_PATH = MODEL_DIR / "model.joblib"


class ExplainabilityInputError(ValueError):
    """Raised when a request cannot be explained because inputs are invalid."""


def explain_segment_hour(
    model_path: str | Path,
    segment_id: str,
    target_hour: str | pd.Timestamp,
    *,
    feature_sample_path: str | Path | None = None,
    use_shap: bool = True,
) -> dict[str, Any]:
    """Explain the predicted total for a single segment at a single hour.

    SHAP is used when installed and compatible with the persisted model. When
    unavailable, this falls back to a deterministic local approximation that
    combines feature baselines, feature deviations, model perturbations, and
    trained LightGBM feature importances.
    """

    model_path = Path(model_path)
    bundle = load_bundle(model_path)
    context = bundle.get("context")
    if not isinstance(context, FeatureContext):
        raise ExplainabilityInputError("Model bundle does not include a FeatureContext.")

    segment_id = str(segment_id)
    if segment_id not in set(map(str, context.selected_segments)):
        raise ExplainabilityInputError(f"Unknown segment_id for this model: {segment_id}")

    target_timestamp = pd.Timestamp(target_hour).floor("h")
    base_row = pd.DataFrame({"segment_id": [segment_id], "target_hour": [target_timestamp]})
    feature_frame = add_features(base_row, context)
    predicted = predict_feature_frame(bundle["model"], feature_frame, context.category_levels)

    prediction = _prediction_payload(predicted.iloc[0])
    row = feature_frame.loc[:, FEATURE_COLUMNS].copy()

    method = "fallback"
    method_note = ""
    contributions: np.ndarray | None = None
    baselines: dict[str, Any] = {}
    deviations: dict[str, float] = {}

    if use_shap:
        contributions, method_note = _try_shap_contributions(bundle["model"], row)
        if contributions is not None:
            method = "shap"

    if contributions is None:
        sample_path = Path(feature_sample_path) if feature_sample_path else _default_sample_path(model_path)
        contributions, baselines, deviations = _fallback_contributions(
            bundle["model"],
            row,
            context,
            sample_path,
            prediction["predicted_total"],
        )
        if not method_note:
            method_note = "shap is not installed or unavailable; used deterministic fallback."

    ranked = _rank_contributions(contributions, row, baselines=baselines, deviations=deviations)
    meta = _segment_metadata(context, segment_id)
    return {
        "segment_id": segment_id,
        "target_hour": target_timestamp.isoformat(),
        "model_path": str(model_path),
        "method": method,
        "method_note": method_note,
        "prediction": prediction,
        "metadata": meta,
        "positive": ranked["positive"],
        "negative": ranked["negative"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH), help="Path to model.joblib.")
    parser.add_argument("--segment-id", required=True, help="Segment id to explain.")
    parser.add_argument("--datetime", required=True, help="Local datetime, e.g. '2026-06-18 09:00'.")
    parser.add_argument("--feature-sample", default=None, help="Optional feature_sample.csv path.")
    parser.add_argument("--no-shap", action="store_true", help="Skip SHAP and force deterministic fallback.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = explain_segment_hour(
            args.model,
            args.segment_id,
            args.datetime,
            feature_sample_path=args.feature_sample,
            use_shap=not args.no_shap,
        )
    except ExplainabilityInputError as exc:
        _write_json({"error": str(exc), "code": "bad_request"}, pretty=args.pretty)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _write_json(
            {
                "error": "Failed to explain segment-hour.",
                "code": "explainability_error",
                "detail": str(exc),
            },
            pretty=args.pretty,
        )
        return 1

    _write_json(result, pretty=args.pretty)
    return 0


def _try_shap_contributions(model: Any, row: pd.DataFrame) -> tuple[np.ndarray | None, str]:
    try:
        import shap  # type: ignore[import-not-found]
    except Exception as exc:
        return None, f"SHAP unavailable ({type(exc).__name__}: {exc}); used deterministic fallback."

    estimators = getattr(model, "estimators_", None)
    if not estimators:
        return None, "Model does not expose per-target estimators; used deterministic fallback."

    try:
        total = np.zeros(len(FEATURE_COLUMNS), dtype=float)
        for estimator in estimators:
            explainer = shap.TreeExplainer(estimator)
            values = explainer.shap_values(row)
            total += _coerce_shap_row(values)
    except Exception as exc:
        return None, f"SHAP failed ({type(exc).__name__}: {exc}); used deterministic fallback."

    return total, "SHAP TreeExplainer contributions summed across target count models."


def _fallback_contributions(
    model: Any,
    row: pd.DataFrame,
    context: FeatureContext,
    sample_path: Path,
    predicted_total: float,
) -> tuple[np.ndarray, dict[str, Any], dict[str, float]]:
    sample = _load_feature_sample(sample_path, context)
    baselines = _feature_baselines(sample, row)
    deviations = _feature_deviations(row, baselines, sample)
    importances = _aggregate_importances(model)
    base_total = _predict_total(model, row, context.category_levels)
    scale = max(1.0, float(predicted_total), float(base_total))
    contributions = np.zeros(len(FEATURE_COLUMNS), dtype=float)

    for idx, feature in enumerate(FEATURE_COLUMNS):
        perturbed = row.copy()
        perturbed.at[perturbed.index[0], feature] = baselines[feature]
        perturbed = apply_category_levels(perturbed, context.category_levels)
        try:
            delta = base_total - _predict_total(model, perturbed, context.category_levels)
        except Exception:
            delta = 0.0

        if not _is_nonzero(delta):
            deviation = deviations[feature]
            sign = math.copysign(1.0, deviation) if _is_nonzero(deviation) else 0.0
            delta = sign * abs(deviation) * importances[idx] * scale

        contributions[idx] = float(delta)

    return contributions, baselines, deviations


def _load_feature_sample(sample_path: Path, context: FeatureContext) -> pd.DataFrame:
    if sample_path.exists():
        sample = pd.read_csv(sample_path, usecols=lambda col: col in FEATURE_COLUMNS)
        for feature in FEATURE_COLUMNS:
            if feature not in sample.columns:
                sample[feature] = np.nan
        return apply_category_levels(sample.loc[:, FEATURE_COLUMNS], context.category_levels)

    fallback = context.segment_metadata.copy()
    fallback["target_hour"] = context.start_hour
    sample = add_features(fallback[["segment_id", "target_hour"]], context)
    return sample.loc[:, FEATURE_COLUMNS]


def _feature_baselines(sample: pd.DataFrame, row: pd.DataFrame) -> dict[str, Any]:
    baselines: dict[str, Any] = {}
    for feature in FEATURE_COLUMNS:
        if feature in CATEGORICAL_COLUMNS:
            values = sample[feature].astype(str)
            baselines[feature] = values.mode().iloc[0] if not values.empty else str(row.iloc[0][feature])
            continue

        numeric = pd.to_numeric(sample[feature], errors="coerce").dropna()
        if numeric.empty:
            baselines[feature] = _json_safe(row.iloc[0][feature])
        else:
            baselines[feature] = float(numeric.median())
    return baselines


def _feature_deviations(
    row: pd.DataFrame,
    baselines: dict[str, Any],
    sample: pd.DataFrame,
) -> dict[str, float]:
    deviations: dict[str, float] = {}
    actual = row.iloc[0]
    for feature in FEATURE_COLUMNS:
        if feature in CATEGORICAL_COLUMNS:
            deviations[feature] = 0.0 if str(actual[feature]) == str(baselines[feature]) else 1.0
            continue

        value = _to_float(actual[feature])
        baseline = _to_float(baselines[feature])
        numeric = pd.to_numeric(sample[feature], errors="coerce").dropna()
        scale = float(numeric.std(ddof=0)) if len(numeric) > 1 else 0.0
        if not math.isfinite(scale) or scale <= 1e-12:
            scale = 1.0
        deviations[feature] = 0.0 if value is None or baseline is None else (value - baseline) / scale
    return deviations


def _aggregate_importances(model: Any) -> np.ndarray:
    raw = np.zeros(len(FEATURE_COLUMNS), dtype=float)
    for estimator in getattr(model, "estimators_", []) or []:
        values = getattr(estimator, "feature_importances_", None)
        if values is None:
            continue
        arr = np.asarray(values, dtype=float)
        raw[: min(len(raw), len(arr))] += arr[: len(raw)]

    if raw.sum() <= 0:
        return np.ones(len(FEATURE_COLUMNS), dtype=float) / len(FEATURE_COLUMNS)
    return raw / raw.sum()


def _predict_total(model: Any, frame: pd.DataFrame, category_levels: dict[str, list[str]]) -> float:
    prepared = apply_category_levels(frame, category_levels)
    predictions = np.clip(model.predict(prepared.loc[:, FEATURE_COLUMNS]), 0.0, None)
    return float(np.asarray(predictions, dtype=float).sum(axis=1)[0])


def _prediction_payload(row: pd.Series) -> dict[str, Any]:
    by_target = {col: _round_float(row[col]) for col in TARGET_COLUMNS}
    return {
        "predicted_total": _round_float(sum(by_target.values())),
        "by_target": by_target,
    }


def _rank_contributions(
    contributions: np.ndarray,
    row: pd.DataFrame,
    *,
    baselines: dict[str, Any],
    deviations: dict[str, float],
) -> dict[str, list[dict[str, Any]]]:
    records = []
    actual = row.iloc[0]
    for idx, feature in enumerate(FEATURE_COLUMNS):
        contribution = float(contributions[idx])
        record = {
            "feature": feature,
            "value": _json_safe(actual[feature]),
            "contribution": _round_float(contribution),
        }
        if feature in baselines:
            record["baseline"] = _json_safe(baselines[feature])
        if feature in deviations:
            record["deviation"] = _round_float(deviations[feature])
        records.append(record)

    positives = sorted((item for item in records if item["contribution"] > 0), key=lambda x: x["contribution"], reverse=True)
    negatives = sorted((item for item in records if item["contribution"] < 0), key=lambda x: x["contribution"])
    return {
        "positive": positives[:3],
        "negative": negatives[:1],
    }


def _segment_metadata(context: FeatureContext, segment_id: str) -> dict[str, Any]:
    meta = context.segment_metadata.loc[context.segment_metadata["segment_id"].astype(str) == segment_id]
    if meta.empty:
        return {}

    row = meta.iloc[0]
    wanted = [
        "police_station",
        "junction_name",
        "junction_bucket",
        "road_class",
        "road_width_m",
        "lat_center",
        "lon_center",
        "map_matching_mode",
        "road_name",
        "osm_highway",
    ]
    return {key: _json_safe(row[key]) for key in wanted if key in row.index}


def _coerce_shap_row(values: Any) -> np.ndarray:
    if isinstance(values, list):
        values = values[0]

    arr = np.asarray(values, dtype=float)
    if arr.ndim == 3:
        arr = arr[0, :, 0]
    elif arr.ndim == 2:
        arr = arr[0]
    elif arr.ndim != 1:
        raise ValueError(f"Unsupported SHAP value shape: {arr.shape}")

    if len(arr) != len(FEATURE_COLUMNS):
        raise ValueError(f"Expected {len(FEATURE_COLUMNS)} SHAP values, got {len(arr)}.")
    return arr


def _default_sample_path(model_path: Path) -> Path:
    return model_path.parent / "feature_sample.csv"


def _write_json(payload: dict[str, Any], *, pretty: bool) -> None:
    kwargs = {"indent": 2, "sort_keys": True} if pretty else {}
    sys.stdout.write(json.dumps(payload, **kwargs))
    sys.stdout.write("\n")


def _round_float(value: Any) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        return 0.0
    return round(numeric, 6)


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return _round_float(value)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if pd.isna(value):
        return None
    return str(value)


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _is_nonzero(value: float) -> bool:
    return math.isfinite(value) and abs(value) > 1e-12


if __name__ == "__main__":
    raise SystemExit(main())
