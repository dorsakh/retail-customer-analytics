"""Data and prediction drift monitoring with delayed-label evaluation.

Monitoring is descriptive: alerts do not prove that model accuracy has
degraded. Out-of-sample outcomes are only scored after the seven-day window
is complete and strictly after the model's last training observation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from .data import DATABASE_URL, FEATURE_COLUMNS
from .score import load_saved_model, load_scoring_features


SCHEMA_PATH = Path(__file__).with_name("sql") / "monitoring_reports.sql"
REFERENCE_FIRST_DAY = 180
REFERENCE_LAST_DAY = 540
PSI_WARNING = 0.20
MISSING_RATE_WARNING = 0.05


def population_stability_index(reference, current, bins: int = 10) -> float:
    """PSI using reference-derived quantiles plus an explicit missing bucket.

    Includes separate low/equal/high buckets when reference is constant.
    Half-count smoothing avoids undefined logarithms for empty bins.
    """
    ref = pd.to_numeric(pd.Series(reference), errors="raise").to_numpy(dtype=float)
    cur = pd.to_numeric(pd.Series(current), errors="raise").to_numpy(dtype=float)
    if len(ref) == 0 or len(cur) == 0:
        raise ValueError("Drift comparison needs nonempty reference and current data.")
    if np.isinf(ref).any() or np.isinf(cur).any():
        raise ValueError("Infinite values are not valid for drift monitoring.")
    finite_ref = ref[np.isfinite(ref)]
    finite_cur = cur[np.isfinite(cur)]

    if len(finite_ref) == 0:
        ref_counts = np.array([0, len(ref)], dtype=float)
        cur_counts = np.array([len(finite_cur), len(cur) - len(finite_cur)], dtype=float)
    else:
        quantiles = np.unique(np.quantile(finite_ref, np.linspace(0, 1, bins + 1)))
        if len(quantiles) == 1:
            value = float(quantiles[0])
            edges = np.array([-np.inf, value, np.nextafter(value, np.inf), np.inf])
        elif len(quantiles) == 2:
            low, high = quantiles
            midpoint = low + (high - low) / 2
            edges = np.array([-np.inf, low, midpoint, np.nextafter(high, np.inf), np.inf])
        else:
            edges = np.r_[-np.inf, quantiles[1:-1], np.inf]
        ref_hist, _ = np.histogram(finite_ref, bins=edges)
        cur_hist, _ = np.histogram(finite_cur, bins=edges)
        ref_counts = np.r_[ref_hist, len(ref) - len(finite_ref)].astype(float)
        cur_counts = np.r_[cur_hist, len(cur) - len(finite_cur)].astype(float)

    alpha = 0.5
    expected = (ref_counts + alpha) / (ref_counts.sum() + alpha * len(ref_counts))
    observed = (cur_counts + alpha) / (cur_counts.sum() + alpha * len(cur_counts))
    return float(np.sum((observed - expected) * np.log(observed / expected)))


def feature_drift_report(reference: pd.DataFrame, current: pd.DataFrame,
                         *, psi_warning: float = PSI_WARNING) -> list[dict]:
    records = []
    for name in FEATURE_COLUMNS:
        ref = pd.to_numeric(reference[name], errors="raise")
        cur = pd.to_numeric(current[name], errors="raise")
        psi = population_stability_index(ref, cur)
        missing_before = float(ref.isna().mean())
        missing_now = float(cur.isna().mean())
        missing_delta = missing_now - missing_before
        records.append({
            "feature": name,
            "psi": round(psi, 4),
            "reference_missing_rate": round(missing_before, 4),
            "current_missing_rate": round(missing_now, 4),
            "missing_rate_change": round(missing_delta, 4),
            "reference_median": float(ref.median()) if ref.notna().any() else None,
            "current_median": float(cur.median()) if cur.notna().any() else None,
            "warning": bool(
                psi >= psi_warning or missing_delta >= MISSING_RATE_WARNING
            ),
        })
    return sorted(records, key=lambda record: record["psi"], reverse=True)


def evaluate_matured_predictions(probabilities, outcomes) -> dict:
    """Unbiased only if these observations postdate model training."""
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=int)
    if len(p) == 0 or len(y) != len(p):
        raise ValueError("Invalid probabilities/outcomes for evaluation.")
    if not np.isfinite(p).all() or not ((0 <= p) & (p <= 1)).all():
        raise ValueError("Invalid prediction probabilities.")
    if not np.isin(y, [0, 1]).all():
        raise ValueError("Invalid outcome labels.")
    base_rate = float(y.mean())
    selected = max(1, int(np.ceil(0.2 * len(p))))
    # Stable descending order resolves ties reproducibly.
    ranked = np.argsort(-p, kind="mergesort")
    precision = float(y[ranked[:selected]].mean())
    positives = int(y.sum())
    negatives = len(y) - positives
    auc = None
    if positives > 0 and negatives > 0:
        ranks = pd.Series(p).rank(method="average").to_numpy(dtype=float)
        auc = float(
            (ranks[y == 1].sum() - positives * (positives + 1) / 2)
            / (positives * negatives)
        )
    return {
        "observations": len(y),
        "repurchase_rate": base_rate,
        "brier": float(np.mean((p - y) ** 2)),
        "roc_auc": auc,
        "precision_at_20": precision,
        "lift_at_20": precision / base_rate if base_rate > 0 else None,
    }


def _outcomes_if_mature(connection, *, day: int, version: str,
                        source_max_day: int, training_last_day: int):
    if day <= training_last_day:
        return "not_applicable_training_period", None
    if day + 7 > source_max_day:
        return "pending", None
    observed = pd.read_sql_query(text("""
        SELECT p.predicted_probability,
               EXISTS (
                   SELECT 1 FROM analytics.baskets b
                   WHERE b.household_key = p.household_key
                     AND b.day BETWEEN :next_day AND :last_day
               ) AS repurchased_7d
        FROM analytics.customer_predictions p
        WHERE p.as_of_day = :day AND p.model_version = :version
        ORDER BY p.household_key
    """), connection, params={
        "day": day, "version": version,
        "next_day": day + 1, "last_day": day + 7,
    })
    if observed.empty:
        raise ValueError("Cannot evaluate: no stored predictions.")
    return "available", evaluate_matured_predictions(
        observed["predicted_probability"], observed["repurchased_7d"]
    )


def _refresh_pending_evaluations(connection, *, source_max_day: int,
                                 trained_through: int, checksum: str) -> int:
    pending = connection.execute(text("""
        SELECT as_of_day, model_version, model_sha256
        FROM analytics.monitoring_reports
        WHERE label_status = 'pending' AND as_of_day + 7 <= :max_day
    """), {"max_day": source_max_day}).mappings().all()
    updated = 0
    for record in pending:
        if record["model_sha256"] != checksum:
            continue
        status, metrics = _outcomes_if_mature(
            connection,
            day=int(record["as_of_day"]),
            version=str(record["model_version"]),
            source_max_day=source_max_day,
            training_last_day=trained_through,
        )
        connection.execute(text("""
            UPDATE analytics.monitoring_reports
            SET label_status = :status, outcome_metrics = CAST(:metrics AS jsonb),
                source_max_day = :max_day, checked_at = CURRENT_TIMESTAMP
            WHERE as_of_day = :day AND model_version = :version
        """), {
            "status": status, "metrics": json.dumps(metrics),
            "max_day": source_max_day, "day": record["as_of_day"],
            "version": record["model_version"],
        })
        updated += 1
    return updated


def run_monitor(as_of_day: int | None = None, *, psi_warning: float = PSI_WARNING) -> dict:
    if not 0 < psi_warning < 10:
        raise ValueError("PSI warning threshold must be between 0 and 10.")
    model, metadata = load_saved_model()
    version = str(metadata["model_version"])
    checksum = str(metadata["model_sha256"])
    training_last_day = int(metadata["max_training_as_of_day"])
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            maximum = connection.execute(
                text("SELECT MAX(day) FROM analytics.baskets")
            ).scalar_one()
            if maximum is None:
                raise ValueError("No source basket history is available.")
            day = int(maximum) if as_of_day is None else int(as_of_day)
            if not 180 <= day <= int(maximum):
                raise ValueError(f"Observation day must be between 180 and {maximum}.")
            columns = ", ".join(FEATURE_COLUMNS)  # fixed code-owned identifiers
            reference = pd.read_sql_query(text(f"""
                SELECT {columns}
                FROM analytics.household_snapshots
                WHERE as_of_day BETWEEN :first AND :last
            """), connection, params={
                "first": REFERENCE_FIRST_DAY, "last": REFERENCE_LAST_DAY
            })
            predictions = pd.read_sql_query(text("""
                SELECT household_key, predicted_probability
                FROM analytics.customer_predictions
                WHERE as_of_day = :day AND model_version = :version
            """), connection, params={"day": day, "version": version})
        if reference.empty or predictions.empty:
            raise ValueError("Reference snapshots or saved predictions are missing.")
        current = load_scoring_features(day)
        if len(predictions) != len(current) or predictions["household_key"].duplicated().any():
            raise ValueError("Prediction rows do not match current household features.")
        if set(predictions["household_key"]) != set(current["household_key"]):
            raise ValueError("Prediction and feature household keys differ.")

        reference_features = reference[FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
        current_features = current[FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
        feature_report = feature_drift_report(
            reference_features, current_features, psi_warning=psi_warning
        )
        reference_scores = np.asarray(
            model.predict(reference_features, validate_features=True), dtype=float
        )
        current_scores = pd.to_numeric(
            predictions["predicted_probability"], errors="raise"
        ).to_numpy(dtype=float)
        probability_psi = population_stability_index(reference_scores, current_scores)
        prediction_report = {
            "psi": round(probability_psi, 4),
            "reference_mean_probability": float(np.mean(reference_scores)),
            "current_mean_probability": float(np.mean(current_scores)),
            "warning": bool(probability_psi >= psi_warning),
            "note": (
                "Training-period reference scores are descriptive and in-sample; "
                "this comparison is not an accuracy estimate."
            ),
        }
        flagged = [record["feature"] for record in feature_report if record["warning"]]
        alerts = [
            {"type": "feature_drift", "feature": name}
            for name in flagged
        ]
        if prediction_report["warning"]:
            alerts.append({"type": "prediction_drift"})
        drift_status = "watch" if alerts else "ok"

        with engine.begin() as connection:
            connection.exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))
            existing = connection.execute(text("""
                SELECT model_sha256 FROM analytics.monitoring_reports
                WHERE as_of_day = :day AND model_version = :version
            """), {"day": day, "version": version}).scalar_one_or_none()
            if existing is not None and existing != checksum:
                raise ValueError(
                    "Model artifact changed without a new version; refuse to overwrite history."
                )
            label_status, outcome_metrics = _outcomes_if_mature(
                connection, day=day, version=version,
                source_max_day=int(maximum), training_last_day=training_last_day
            )
            connection.execute(text("""
                INSERT INTO analytics.monitoring_reports (
                    as_of_day, model_version, model_sha256, source_max_day,
                    household_count, reference_count, drift_status,
                    feature_drift, prediction_drift, alerts,
                    label_status, outcome_metrics
                ) VALUES (
                    :day, :version, :checksum, :max_day,
                    :household_count, :reference_count, :status,
                    CAST(:features AS jsonb), CAST(:predictions AS jsonb),
                    CAST(:alerts AS jsonb), :label_status, CAST(:metrics AS jsonb)
                )
                ON CONFLICT (as_of_day, model_version) DO UPDATE SET
                    checked_at = CURRENT_TIMESTAMP,
                    source_max_day = EXCLUDED.source_max_day,
                    household_count = EXCLUDED.household_count,
                    reference_count = EXCLUDED.reference_count,
                    drift_status = EXCLUDED.drift_status,
                    feature_drift = EXCLUDED.feature_drift,
                    prediction_drift = EXCLUDED.prediction_drift,
                    alerts = EXCLUDED.alerts,
                    label_status = EXCLUDED.label_status,
                    outcome_metrics = EXCLUDED.outcome_metrics
            """), {
                "day": day, "version": version, "checksum": checksum,
                "max_day": int(maximum), "household_count": len(current),
                "reference_count": len(reference), "status": drift_status,
                "features": json.dumps(feature_report, allow_nan=False),
                "predictions": json.dumps(prediction_report, allow_nan=False),
                "alerts": json.dumps(alerts, allow_nan=False),
                "label_status": label_status,
                "metrics": json.dumps(outcome_metrics, allow_nan=False),
            })
            matured_count = _refresh_pending_evaluations(
                connection, source_max_day=int(maximum),
                trained_through=training_last_day, checksum=checksum,
            )
        return {
            "as_of_day": day,
            "model_version": version,
            "drift_status": drift_status,
            "feature_alert_count": len(flagged),
            "prediction_psi": prediction_report["psi"],
            "most_shifted_features": [
                {"feature": record["feature"], "psi": record["psi"]}
                for record in feature_report[:3]
            ],
            "label_status": label_status,
            "outcome_metrics": outcome_metrics,
            "previous_windows_evaluated": matured_count,
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record data/prediction drift and available delayed-label metrics."
    )
    parser.add_argument("--as-of-day", type=int)
    parser.add_argument("--psi-warning", type=float, default=PSI_WARNING)
    args = parser.parse_args()
    result = run_monitor(as_of_day=args.as_of_day, psi_warning=args.psi_warning)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
