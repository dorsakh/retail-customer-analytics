"""Leakage-aware evaluation for customer lapse risk and decision scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from .models import make_lightgbm_model, make_logistic_model
from .retention_data import (
    ALL_FAMILIES,
    HORIZONS,
    ROOT,
    VALIDATION_DAYS,
    features_frame,
    partition,
)


REPORTS = ROOT / "reports" / "tables"
TOP_CAPACITY = 0.20


def top_capacity_stats(data: pd.DataFrame, scores, fraction: float = TOP_CAPACITY):
    """Select the highest risk per day, not 20% of pooled observations."""
    if not 0 < fraction <= 1:
        raise ValueError("Capacity must be in (0, 1]")
    if len(scores) != len(data):
        raise ValueError("One risk score is required per observation")
    work = pd.DataFrame({
        "as_of_day": data["as_of_day"].to_numpy(),
        "actual": data["target"].to_numpy(),
        "risk": np.asarray(scores, dtype=float),
        "row_order": np.arange(len(data)),
    })
    if not np.isfinite(work["risk"]).all():
        raise ValueError("Non-finite scores")
    work = work.sort_values(
        ["as_of_day", "risk", "row_order"],
        ascending=[True, False, True], kind="mergesort",
    )
    work["position"] = work.groupby("as_of_day").cumcount() + 1
    size = work.groupby("as_of_day")["row_order"].transform("size")
    picked = work.loc[work["position"] <= np.ceil(size * fraction)]
    precision = float(picked["actual"].mean())
    recall = float(picked["actual"].sum() / max(work["actual"].sum(), 1))
    prevalence = float(work["actual"].mean())
    return {
        "selected": int(len(picked)),
        "precision_at_capacity": precision,
        "recall_at_capacity": recall,
        "lift_at_capacity": precision / prevalence if prevalence else np.nan,
    }


def classification_report(
    label: str, data: pd.DataFrame, scores, *, probabilistic: bool = True
) -> dict:
    stats = top_capacity_stats(data, scores)
    target = data["target"].to_numpy(dtype=int)
    result = {
        "model": label,
        "observations": len(data),
        "households": int(data["household_key"].nunique()),
        "lapse_rate": float(np.mean(target)),
        "roc_auc": np.nan,
        "avg_precision": np.nan,
        "brier": np.nan,
        **stats,
    }
    if len(np.unique(target)) == 2:
        result["roc_auc"] = float(roc_auc_score(target, scores))
        result["avg_precision"] = float(average_precision_score(target, scores))
    if probabilistic:
        result["brier"] = float(brier_score_loss(target, scores))
    return result


def fit_predict(estimator, train: pd.DataFrame, evaluation: pd.DataFrame,
                families: tuple[str, ...] = ALL_FAMILIES):
    x_train = features_frame(train, families)
    x_test = features_frame(evaluation, families, columns=x_train.columns.tolist())
    model = clone(estimator)
    model.fit(x_train, train["target"].astype(int))
    return model, model.predict_proba(x_test)[:, 1], x_train.columns.tolist()


def evaluate_horizon(data: pd.DataFrame, horizon: int) -> dict:
    splits = partition(data)
    train = splits["train"].copy()
    validation = splits["validation"].copy()
    for part in (train, validation):
        part["target"] = part[f"lapsed_{horizon}d"].astype(int)
    if train["target"].nunique() < 2 or validation["target"].nunique() < 2:
        raise ValueError(f"Horizon {horizon} has a single label class")
    _, probs, _ = fit_predict(make_lightgbm_model(), train, validation)
    return {"horizon_days": horizon, **classification_report(
        "LightGBM", validation, probs
    )}


def choose_horizon(rows: list[dict]) -> int:
    """Predeclared validation-only rule, with a meaningful event-rate floor.

    Prefer the largest validation Precision@20 lift where both classes are
    adequately represented. This is a heuristic decision rule, NOT proof of
    the economically optimal contact window.
    """
    eligible = [r for r in rows if 0.10 <= r["lapse_rate"] <= 0.75]
    pool = eligible or rows
    if not pool:
        raise ValueError("No horizon candidates")
    return int(max(pool, key=lambda r: (r["lift_at_capacity"], -r["horizon_days"]))[
        "horizon_days"
    ])


def ablation_study(train: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    experiments: dict[str, tuple[str, ...]] = {
        "behavioral only": ("behavioral",),
        "+ cadence": ("behavioral", "cadence"),
        "all families": ALL_FAMILIES,
    }
    for family in ALL_FAMILIES[1:]:
        experiments[f"all - {family}"] = tuple(
            name for name in ALL_FAMILIES if name != family
        )
    rows = []
    for label, families in experiments.items():
        _, probabilities, columns = fit_predict(
            make_lightgbm_model(), train, validation, families
        )
        result = classification_report(label, validation, probabilities)
        rows.append({"feature_families": ",".join(families),
                     "n_features": len(columns), **result})
    return pd.DataFrame(rows)


def bootstrap_model_differences(
    data: pd.DataFrame,
    probability_scores: dict[str, np.ndarray],
    *,
    reference: str,
    replicates: int = 500,
    seed: int = 20261027,
) -> pd.DataFrame:
    """Paired entire-household bootstrap; model fits are held fixed."""
    if reference not in probability_scores:
        raise ValueError("Reference method must have scores")
    if replicates < 1:
        raise ValueError("replicates must be positive")
    n = len(data)
    scores = {name: np.asarray(v, dtype=float) for name, v in probability_scores.items()}
    if any(len(v) != n for v in scores.values()):
        raise ValueError("Scores do not match holdout rows")
    codes, households = pd.factorize(data["household_key"], sort=True)
    if len(households) < 2:
        raise ValueError("Need multiple independent households")
    rng = np.random.default_rng(seed)
    indices = np.arange(n)
    point = {key: top_capacity_stats(data, val)["precision_at_capacity"]
             for key, val in scores.items()}
    samples = {key: [] for key in scores if key != reference}
    for _ in range(replicates):
        counts = np.bincount(
            rng.integers(len(households), size=len(households)),
            minlength=len(households),
        )
        selected = np.repeat(indices, counts[codes])
        drawn = data.iloc[selected].reset_index(drop=True)
        ref = top_capacity_stats(drawn, scores[reference][selected])[
            "precision_at_capacity"
        ]
        for key in samples:
            value = top_capacity_stats(drawn, scores[key][selected])[
                "precision_at_capacity"
            ]
            samples[key].append(value - ref)
    return pd.DataFrame([
        {
            "comparison": f"{name} minus {reference}",
            "precision_gap_pp": 100 * (point[name] - point[reference]),
            "ci_low_pp": 100 * np.quantile(draws, 0.025),
            "ci_high_pp": 100 * np.quantile(draws, 0.975),
            "bootstrap_households": len(households),
            "replicates": replicates,
        }
        for name, draws in samples.items()
    ])


def scenario_table(
    data: pd.DataFrame,
    model_scores,
    *,
    gross_margin: float = 15.0,
    offer_cost: float = 2.0,
) -> pd.DataFrame:
    """Assumption-only economics. Neither response uplift nor ROI was measured.

    Uniform incremental response per contacted household is a transparent
    sensitivity test; it cannot identify an empirically optimal capacity.
    """
    if gross_margin <= 0 or offer_cost < 0:
        raise ValueError("Margin must be positive and cost non-negative")
    rows = []
    for fraction in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 1.0):
        actual_selected = top_capacity_stats(data, model_scores, fraction)["selected"]
        for assumed_delta in (0.01, 0.03, 0.05, 0.10, 0.15, 0.20):
            rows.append({
                "capacity": fraction,
                "contacts": actual_selected,
                "assumed_incremental_response": assumed_delta,
                "assumed_margin_per_incremental_purchase": gross_margin,
                "assumed_cost_per_contact": offer_cost,
                "break_even_incremental_response": offer_cost / gross_margin,
                "hypothetical_net_value": round(
                    actual_selected * (assumed_delta * gross_margin - offer_cost), 2
                ),
                "note": "SCENARIO ONLY; not an estimated treatment effect or measured ROI",
            })
    return pd.DataFrame(rows)


def population_stability_index(reference, current) -> float:
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    bins = np.unique(np.quantile(ref, np.linspace(0, 1, 11)))
    if len(bins) < 3:
        return np.nan
    edges = np.r_[-np.inf, bins[1:-1], np.inf]
    a = np.histogram(ref, bins=edges)[0].astype(float)
    b = np.histogram(cur, bins=edges)[0].astype(float)
    a = np.maximum(a / len(ref), 1e-6)
    b = np.maximum(b / len(cur), 1e-6)
    return float(np.sum((b - a) * np.log(b / a)))


def run_evaluation(data: pd.DataFrame, *, horizon: int | None = None,
                   bootstraps: int = 500, gross_margin: float = 15.0,
                   contact_cost: float = 2.0) -> dict:
    """Pick horizon/model using validation, evaluate once on fixed holdout."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    data = data.copy()
    rows = [evaluate_horizon(data, h) for h in HORIZONS]
    candidate_report = pd.DataFrame(rows)
    candidate_report.to_csv(REPORTS / "retention_horizons.csv", index=False)
    chosen = choose_horizon(rows) if horizon is None else horizon
    if chosen not in HORIZONS:
        raise ValueError(f"Horizon must be one of {HORIZONS}")
    splits = partition(data)
    train = splits["train"].copy()
    validation = splits["validation"].copy()
    holdout = splits["holdout"].copy()
    for part in (train, validation, holdout):
        part["target"] = part[f"lapsed_{chosen}d"].astype(int)
    validation_scores = {}
    for name, estimator in (
        ("Logistic regression", make_logistic_model()),
        ("LightGBM", make_lightgbm_model()),
    ):
        _, pred, _ = fit_predict(estimator, train, validation)
        validation_scores[name] = classification_report(name, validation, pred)
    validation_table = pd.DataFrame(list(validation_scores.values()))
    validation_table.to_csv(REPORTS / "retention_model_selection.csv", index=False)
    # Require a practically non-trivial LightGBM precision advantage;
    # otherwise prefer the simpler transparent logistic model.
    ml_gap = (
        validation_scores["LightGBM"]["precision_at_capacity"]
        - validation_scores["Logistic regression"]["precision_at_capacity"]
    )
    selected_model = "LightGBM" if ml_gap >= 0.015 else "Logistic regression"
    selected_estimator = (
        make_lightgbm_model() if selected_model == "LightGBM"
        else make_logistic_model()
    )
    ablation = ablation_study(train, validation)
    ablation.to_csv(REPORTS / "retention_ablation.csv", index=False)

    development = pd.concat([train, validation], ignore_index=True)
    holdout_scores: dict[str, np.ndarray] = {
        "Recency": holdout["recency_days"].to_numpy(dtype=float),
        "Recency / visit interval": holdout["overdue_ratio"].fillna(
            holdout["recency_days"]
        ).to_numpy(dtype=float),
    }
    fitted_for_replay = None
    replay_columns = None
    for name, estimator in (
        ("Logistic regression", make_logistic_model()),
        ("LightGBM", make_lightgbm_model()),
    ):
        fitted, scores, columns = fit_predict(estimator, development, holdout)
        holdout_scores[name] = scores
        if name == selected_model:
            fitted_for_replay, replay_columns = fitted, columns
    holdout_report = pd.DataFrame([
        classification_report(
            name, holdout, scores,
            probabilistic=name in ("Logistic regression", "LightGBM"),
        )
        for name, scores in holdout_scores.items()
    ])
    holdout_report.to_csv(REPORTS / "retention_holdout.csv", index=False)
    paired = bootstrap_model_differences(
        holdout, holdout_scores, reference="Logistic regression",
        replicates=bootstraps,
    )
    paired.to_csv(REPORTS / "retention_paired_bootstrap.csv", index=False)
    scenario_table(
        holdout, holdout_scores[selected_model],
        gross_margin=gross_margin, offer_cost=contact_cost,
    ).to_csv(
        REPORTS / "retention_profit_scenarios.csv", index=False
    )
    reference_scores = fitted_for_replay.predict_proba(
        features_frame(validation, columns=replay_columns)
    )[:, 1]
    replay = []
    for day, subset in holdout.groupby("as_of_day", sort=True):
        values = holdout_scores[selected_model][
            holdout["as_of_day"].eq(day).to_numpy()
        ]
        stats = top_capacity_stats(subset, values)
        replay.append({
            "as_of_day": int(day),
            "households": len(subset),
            "observed_lapse_rate": float(subset["target"].mean()),
            "mean_predicted_risk": float(np.mean(values)),
            "prediction_psi_vs_validation": population_stability_index(
                reference_scores, values
            ),
            **stats,
            "model_trained_through_day": max(VALIDATION_DAYS),
        })
    pd.DataFrame(replay).to_csv(REPORTS / "retention_replay.csv", index=False)
    from .retention_data import coverage_summary
    coverage_summary(data).to_csv(REPORTS / "retention_coverage.csv", index=False)
    decision = {
        "selected_horizon_days": chosen,
        "horizon_selection": (
            "validation-only prevalence>=10% and <=75%, then best lift@20"
            if horizon is None else "explicitly supplied by user"
        ),
        "selected_model": selected_model,
        "model_selection": "validation Precision@20: LightGBM must exceed LR by >=1.5 pp",
        "holdout_days": [int(day) for day in sorted(holdout["as_of_day"].unique())],
        "holdout_n": len(holdout),
        "holdout_households": int(holdout["household_key"].nunique()),
        "train_end_day": 510,
        "validation_end_day": 570,
        "future_labels_available_through_day": 660 + chosen,
        "hypothetical_margin_per_incremental_purchase": gross_margin,
        "hypothetical_cost_per_contact": contact_cost,
        "note": "Observed lapse outcomes, not incremental promotion response or ROI",
    }
    (REPORTS / "retention_decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )
    print("\nHorizon comparison (VALIDATION only):")
    print(candidate_report[["horizon_days", "lapse_rate", "roc_auc",
                            "avg_precision", "precision_at_capacity",
                            "lift_at_capacity"]].round(3).to_string(index=False))
    print("\nPaired HOLDOUT comparison:")
    print(holdout_report[["model", "roc_auc", "avg_precision", "brier",
                           "precision_at_capacity", "recall_at_capacity"]]
          .round(3).to_string(index=False))
    print("\nPaired household bootstrap:")
    print(paired.round(2).to_string(index=False))
    print(f"\nSelected {chosen}-day lapse horizon and {selected_model} on validation.")
    return decision
