"""Holdout capacity analysis: how many future purchasers can a ranking find?

This is an offline ranking comparison, not an estimate of campaign uplift.
The final v1 artifact must NOT be used here: it has seen holdout labels.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .data import FEATURE_COLUMNS, TARGET_COLUMN, load_data, split_by_time
from .models import make_lightgbm_model


CAPACITIES = (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 1.00)
ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "tables"
FIGURE_DIR = ROOT / "reports" / "figures"


def _validate_scored(scored: pd.DataFrame, capacities) -> None:
    required = {
        "household_key", "as_of_day", "recency_days", "baskets_90d",
        TARGET_COLUMN, "model_score",
    }
    missing = required.difference(scored.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    # Legitimate no-history values in the two baseline features sort last,
    # matching the established evaluation in metrics.py.
    identity_and_label = [
        "household_key", "as_of_day", TARGET_COLUMN, "model_score"
    ]
    if scored.empty or scored[identity_and_label].isna().any().any():
        raise ValueError("Scored holdout data has missing keys or outcomes.")
    if not set(scored[TARGET_COLUMN].unique()).issubset({0, 1}):
        raise ValueError("Repurchase labels must be binary.")
    if not np.isfinite(scored["model_score"].to_numpy(dtype=float)).all():
        raise ValueError("Model scores must be finite.")
    if any(not np.isfinite(c) or c <= 0 or c > 1 for c in capacities):
        raise ValueError("Capacities must be greater than 0 and at most 1.")


def _sort_day(day: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if strategy == "model":
        return day.sort_values(
            ["model_score", "household_key"],
            ascending=[False, True], kind="mergesort",
        )
    return day.sort_values(
        ["recency_days", "baskets_90d", "household_key"],
        ascending=[True, False, True], kind="mergesort",
    )


def priority_curve(
    scored: pd.DataFrame,
    capacities=CAPACITIES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return pooled and per-day results with each day's quota rounded up.

    The same household may appear at different dates; its observations are
    kept separate. Bootstrap replicas may also contain duplicate households.
    """
    capacities = tuple(capacities)
    _validate_scored(scored, capacities)

    details = []
    for day, day_data in scored.groupby("as_of_day", sort=True):
        n = len(day_data)
        total_positive = int(day_data[TARGET_COLUMN].sum())
        baseline_rate = total_positive / n

        for strategy in ("baseline", "model"):
            ranked = _sort_day(day_data, strategy)
            cumulative = np.cumsum(
                ranked[TARGET_COLUMN].to_numpy(dtype=int)
            )
            for fraction in capacities:
                k = int(np.ceil(n * fraction))
                captured = int(cumulative[k - 1])
                precision = captured / k
                details.append({
                    "as_of_day": int(day),
                    "capacity_pct": int(round(100 * fraction)),
                    "strategy": strategy,
                    "households": n,
                    "selected": k,
                    "total_purchasers": total_positive,
                    "purchasers_identified": captured,
                    "precision": precision,
                    "capture_rate": (
                        captured / total_positive if total_positive else np.nan
                    ),
                    "lift": (
                        precision / baseline_rate if baseline_rate else np.nan
                    ),
                })

    by_day = pd.DataFrame(details)
    summary = []
    for fraction in capacities:
        percent = int(round(100 * fraction))
        subset = by_day.loc[by_day["capacity_pct"].eq(percent)]
        baseline = subset.loc[subset["strategy"].eq("baseline")]
        model = subset.loc[subset["strategy"].eq("model")]

        total_households = int(model["households"].sum())
        total_positive = int(model["total_purchasers"].sum())
        selected = int(model["selected"].sum())
        base_captured = int(baseline["purchasers_identified"].sum())
        model_captured = int(model["purchasers_identified"].sum())
        base_precision = base_captured / selected
        model_precision = model_captured / selected
        rate = total_positive / total_households

        summary.append({
            "capacity_pct": percent,
            "households": total_households,
            "selected": selected,
            "total_purchasers": total_positive,
            "baseline_purchasers_identified": base_captured,
            "model_purchasers_identified": model_captured,
            "extra_purchasers_identified": model_captured - base_captured,
            "baseline_precision": base_precision,
            "model_precision": model_precision,
            "precision_gap_pp": 100 * (model_precision - base_precision),
            "baseline_capture_rate": (
                base_captured / total_positive if total_positive else np.nan
            ),
            "model_capture_rate": (
                model_captured / total_positive if total_positive else np.nan
            ),
            "baseline_lift": base_precision / rate if rate else np.nan,
            "model_lift": model_precision / rate if rate else np.nan,
        })

    return pd.DataFrame(summary), by_day


def household_bootstrap_curve(
    scored: pd.DataFrame,
    capacities=CAPACITIES,
    n_bootstrap: int = 500,
    random_state: int = 42,
) -> pd.DataFrame:
    """Paired household bootstrap with fixed scores and identical day quotas.

    Resample each household as a cluster across all observation days, while
    retaining the original ordering of its duplicate rows in a replica.
    """
    capacities = tuple(capacities)
    _validate_scored(scored, capacities)
    if n_bootstrap < 2:
        raise ValueError("At least two bootstrap replicates are required.")

    scored = scored.reset_index(drop=True)
    codes, households = pd.factorize(scored["household_key"], sort=True)
    positives = scored[TARGET_COLUMN].to_numpy(dtype=int)
    day_indices = []

    for _, day_data in scored.groupby("as_of_day", sort=True):
        day_indices.append({
            strategy: _sort_day(day_data, strategy).index.to_numpy(dtype=int)
            for strategy in ("baseline", "model")
        })

    fractions = np.asarray(capacities, dtype=float)
    samples = np.empty((n_bootstrap, len(capacities), 3), dtype=float)
    rng = np.random.default_rng(random_state)

    for iteration in range(n_bootstrap):
        drawn = rng.integers(0, len(households), size=len(households))
        household_weights = np.bincount(
            drawn, minlength=len(households)
        )
        row_weights = household_weights[codes]
        selected_totals = np.zeros(len(capacities), dtype=int)
        captured_totals = {
            "baseline": np.zeros(len(capacities), dtype=int),
            "model": np.zeros(len(capacities), dtype=int),
        }

        for day in day_indices:
            base_indices = day["baseline"]
            n = int(row_weights[base_indices].sum())
            if n == 0:
                continue
            limits = np.ceil(fractions * n).astype(int)
            selected_totals += limits

            for strategy, indices in day.items():
                w = row_weights[indices]
                y = positives[indices]
                cumulative_n = np.cumsum(w)
                cumulative_positive = np.cumsum(w * y)
                ending = np.searchsorted(cumulative_n, limits, side="left")
                previous = np.maximum(ending - 1, 0)
                n_before = np.where(ending > 0, cumulative_n[previous], 0)
                positive_before = np.where(
                    ending > 0, cumulative_positive[previous], 0
                )
                captured_totals[strategy] += (
                    positive_before + (limits - n_before) * y[ending]
                )

        baseline_precision = captured_totals["baseline"] / selected_totals
        model_precision = captured_totals["model"] / selected_totals
        samples[iteration, :, 0] = baseline_precision
        samples[iteration, :, 1] = model_precision
        samples[iteration, :, 2] = 100 * (
            model_precision - baseline_precision
        )

    intervals = []
    for i, fraction in enumerate(capacities):
        confidence = np.percentile(samples[:, i, :], [2.5, 97.5], axis=0)
        intervals.append({
            "capacity_pct": int(round(100 * fraction)),
            "baseline_precision_ci_low": confidence[0, 0],
            "baseline_precision_ci_high": confidence[1, 0],
            "model_precision_ci_low": confidence[0, 1],
            "model_precision_ci_high": confidence[1, 1],
            "precision_gap_pp_ci_low": confidence[0, 2],
            "precision_gap_pp_ci_high": confidence[1, 2],
            "bootstrap_replicates": n_bootstrap,
        })
    return pd.DataFrame(intervals)


def save_figure(curve: pd.DataFrame) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Figure skipped: install the reporting extra for matplotlib.")
        return False

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    x = curve["capacity_pct"].to_numpy()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), constrained_layout=True)
    colors = {"baseline": "#8A919D", "model": "#146B7A"}

    for key, name in (("baseline", "Recency + frequency"),
                      ("model", "LightGBM")):
        axes[0].plot(
            x, 100 * curve[f"{key}_precision"], marker="o",
            lw=2.3, ms=5, color=colors[key], label=name,
        )
        axes[1].plot(
            x, 100 * curve[f"{key}_capture_rate"], marker="o",
            lw=2.3, ms=5, color=colors[key], label=name,
        )

    for axis, ylabel in zip(
        axes, ("Precision among selected (%)", "Share of purchasers found (%)")
    ):
        axis.set_xlabel("Households selected per observation day (%)")
        axis.set_ylabel(ylabel)
        axis.set_xticks(x)
        axis.grid(axis="y", alpha=0.22)
        axis.spines[["top", "right"]].set_visible(False)

    axes[0].set_title("How accurate is the shortlist?")
    axes[1].set_title("How many purchasers does it cover?")
    axes[0].legend(frameon=False, loc="lower left")
    fig.suptitle("Holdout purchasing behavior — fixed-capacity ranking")
    fig.savefig(FIGURE_DIR / "business_priority_curve.png", dpi=170)
    plt.close(fig)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    splits = split_by_time(load_data())
    development = pd.concat(
        [splits["train"], splits["validation"]], ignore_index=True
    )
    holdout = splits["test"].copy()

    model = make_lightgbm_model()
    model.fit(development[FEATURE_COLUMNS], development[TARGET_COLUMN])
    holdout["model_score"] = model.predict_proba(
        holdout[FEATURE_COLUMNS]
    )[:, 1]

    curve, by_day = priority_curve(holdout)
    confidence = household_bootstrap_curve(
        holdout, n_bootstrap=args.bootstrap
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    curve.to_csv(REPORT_DIR / "business_priority_curve.csv", index=False)
    by_day.to_csv(REPORT_DIR / "business_priority_by_day.csv", index=False)
    confidence.to_csv(REPORT_DIR / "business_priority_uncertainty.csv", index=False)

    if not args.no_plot:
        save_figure(curve)

    displayed = curve.merge(
        confidence[["capacity_pct", "precision_gap_pp_ci_low",
                    "precision_gap_pp_ci_high"]],
        on="capacity_pct",
    )
    print(f"Train + validation observations: {len(development):,}")
    print(f"Unseen holdout observations: {len(holdout):,}")
    print(f"Bootstrap samples (whole households): {args.bootstrap:,}")
    print("\nHoldout capacity comparison (descriptive purchasing outcomes):")
    print(displayed[[
        "capacity_pct", "selected", "baseline_precision", "model_precision",
        "precision_gap_pp", "precision_gap_pp_ci_low",
        "precision_gap_pp_ci_high", "extra_purchasers_identified",
    ]].round(3).to_string(index=False))
    print(f"\nReports: {REPORT_DIR}/business_priority_*.csv")
    print("These are observed purchasers found by each ranking, NOT incremental")
    print("conversions or financial returns from targeting them.")


if __name__ == "__main__":
    main()
