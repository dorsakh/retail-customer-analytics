import numpy as np
import pandas as pd

from .metrics import top_fraction_metrics


def household_bootstrap_precision(
    data: pd.DataFrame,
    probabilities,
    n_bootstrap: int = 1000,
    random_state: int = 42,
) -> pd.DataFrame:
    """Estimate precision uncertainty by resampling households."""

    probabilities = np.asarray(
        probabilities,
        dtype=float,
    )

    if probabilities.shape != (len(data),):
        raise ValueError(
            "Probabilities must match the number of observations."
        )

    if not np.isfinite(probabilities).all():
        raise ValueError("Probabilities must be finite.")

    if data.empty:
        raise ValueError("Evaluation data must not be empty.")

    if data["household_key"].isna().any():
        raise ValueError("Household keys must not be missing.")

    if n_bootstrap < 1:
        raise ValueError("n_bootstrap must be positive.")

    # Original point estimates
    baseline_precision, _ = top_fraction_metrics(
        data,
        use_frequency=True,
    )

    model_precision, _ = top_fraction_metrics(
        data,
        scores=probabilities,
    )

    point_estimates = np.array([
        baseline_precision,
        model_precision,
        model_precision - baseline_precision,
    ])

    # Assign one cluster identifier to each household.
    household_codes, unique_households = pd.factorize(
        data["household_key"],
        sort=True,
    )

    n_households = len(unique_households)
    row_indices = np.arange(len(data))

    rng = np.random.default_rng(random_state)

    bootstrap_results = np.empty(
        (n_bootstrap, 3),
        dtype=float,
    )

    for iteration in range(n_bootstrap):

        # Sample households with replacement.
        sampled_households = rng.integers(
            0,
            n_households,
            size=n_households,
        )

        household_counts = np.bincount(
            sampled_households,
            minlength=n_households,
        )

        # Repeat all rows belonging to each sampled household.
        sampled_indices = np.repeat(
            row_indices,
            household_counts[household_codes],
        )

        sampled_data = (
            data.iloc[sampled_indices]
            .reset_index(drop=True)
        )

        sampled_probabilities = probabilities[
            sampled_indices
        ]

        baseline, _ = top_fraction_metrics(
            sampled_data,
            use_frequency=True,
        )

        model, _ = top_fraction_metrics(
            sampled_data,
            scores=sampled_probabilities,
        )

        bootstrap_results[iteration] = [
            baseline,
            model,
            model - baseline,
        ]

    lower_bounds = np.quantile(
        bootstrap_results,
        0.025,
        axis=0,
    )

    upper_bounds = np.quantile(
        bootstrap_results,
        0.975,
        axis=0,
    )

    return pd.DataFrame({
        "metric": [
            "baseline_precision_at_20",
            "lightgbm_precision_at_20",
            "precision_gain_at_20",
        ],
        "estimate": point_estimates,
        "ci_lower_95": lower_bounds,
        "ci_upper_95": upper_bounds,
        "n_bootstrap": n_bootstrap,
        "random_state": random_state,
    })