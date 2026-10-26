from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TABLE_DIR = PROJECT_ROOT / "reports" / "tables"
FIGURE_DIR = PROJECT_ROOT / "reports" / "figures"

COLORS = {
    "Recency + frequency": "#94A3B8",
    "Logistic regression": "#E69F00",
    "LightGBM": "#0072B2",
    "XGBoost": "#009E73",
    "HistGradientBoosting": "#CC79A7",
}

plt.rcParams.update({
    "figure.dpi": 120,
    "savefig.dpi": 200,
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.2,
})


def save_figure(fig, filename):
    fig.savefig(
        FIGURE_DIR / filename,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


def plot_rolling_origin(backtest):
    fig, ax = plt.subplots(figsize=(9, 5))

    folds = (
        backtest[
            ["train_end_day", "validation_days"]
        ]
        .drop_duplicates()
        .sort_values("train_end_day")
    )

    x = np.arange(len(folds))

    for model_name, color in COLORS.items():
        model_data = (
            backtest.loc[
                backtest["model"] == model_name
            ]
            .sort_values("train_end_day")
        )

        ax.plot(
            x,
            model_data["precision_at_20"],
            marker="o",
            linewidth=2,
            markersize=6,
            color=color,
            label=model_name,
        )

    labels = [
        value.replace("[", "").replace("]", "")
        for value in folds["validation_days"]
    ]

    ax.set_xticks(x, labels)
    ax.set_ylim(0.70, 1.0)

    ax.yaxis.set_major_formatter(
        PercentFormatter(xmax=1)
    )

    ax.set_title(
        "Model Performance Across Rolling-Origin Folds"
    )
    ax.set_xlabel("Validation days")
    ax.set_ylabel("Precision@20%")

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.38),
        ncol=3,
        frameon=False,
    )

    save_figure(
        fig,
        "rolling_origin_comparison.png",
    )


def plot_holdout_precision(uncertainty):
    results = uncertainty.set_index("metric")

    models = [
        (
            "Recency + frequency",
            "baseline_precision_at_20",
        ),
        (
            "LightGBM",
            "lightgbm_precision_at_20",
        ),
    ]

    fig, ax = plt.subplots(figsize=(8, 3.8))

    for position, (name, metric) in enumerate(models):
        row = results.loc[metric]

        estimate = row["estimate"]
        lower = row["ci_lower_95"]
        upper = row["ci_upper_95"]

        ax.barh(
            position,
            estimate,
            height=0.48,
            color=COLORS[name],
        )

        ax.errorbar(
            estimate,
            position,
            xerr=[
                [estimate - lower],
                [upper - estimate],
            ],
            fmt="none",
            color="#111827",
            capsize=4,
        )

        ax.text(
            estimate - 0.04,
            position,
            f"{estimate:.1%}",
            va="center",
            ha="right",
            color=(
                "#111827"
                if name == "Recency + frequency"
                else "white"
            ),
            fontweight="bold",
        )

    ax.set_yticks(
        [0, 1],
        ["Recency + frequency", "LightGBM"],
    )

    ax.invert_yaxis()
    ax.set_xlim(0, 1)

    ax.xaxis.set_major_formatter(
        PercentFormatter(xmax=1)
    )

    ax.set_title(
        "Holdout Precision@20% with 95% Confidence Intervals"
    )
    ax.set_xlabel("Precision@20%")

    gain = results.loc["precision_gain_at_20"]

    fig.text(
        0.18,
        0.02,
        (
            f"Paired precision gain: "
            f"+{100 * gain['estimate']:.1f} pp "
            f"(95% CI: "
            f"+{100 * gain['ci_lower_95']:.1f} to "
            f"+{100 * gain['ci_upper_95']:.1f} pp)"
        ),
        fontsize=9,
    )

    fig.subplots_adjust(bottom=0.22)

    save_figure(
        fig,
        "holdout_precision_ci.png",
    )


def plot_calibration(calibration):
    fig, ax = plt.subplots(figsize=(6, 6))

    ax.plot(
        [0, 1],
        [0, 1],
        linestyle="--",
        color="#94A3B8",
        label="Perfect calibration",
    )

    ax.plot(
        calibration["predicted_probability"],
        calibration["observed_rate"],
        marker="o",
        linewidth=2,
        color=COLORS["LightGBM"],
        label="LightGBM",
    )

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.set_title("Holdout Probability Calibration")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed repurchase rate")

    ax.legend(frameon=False)

    save_figure(
        fig,
        "holdout_calibration.png",
    )


def plot_feature_importance(importance):
    top_features = (
        importance
        .sort_values(
            "gain_share_pct",
            ascending=False,
        )
        .head(10)
        .iloc[::-1]
    )

    fig, ax = plt.subplots(figsize=(9, 5.5))

    ax.barh(
        top_features["feature"],
        top_features["gain_share_pct"],
        color=COLORS["LightGBM"],
    )

    ax.set_title("Top 10 Features by LightGBM Gain")
    ax.set_xlabel("Share of total gain (%)")

    ax.set_xlim(
        0,
        top_features["gain_share_pct"].max() * 1.18,
    )

    for position, value in enumerate(
        top_features["gain_share_pct"]
    ):
        ax.text(
            value + 0.5,
            position,
            f"{value:.1f}%",
            va="center",
            fontsize=9,
        )

    save_figure(
        fig,
        "feature_importance.png",
    )


def plot_propensity_deciles(deciles):
    data = deciles.sort_values("score_decile")

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(
        data["score_decile"],
        data["avg_predicted_probability"],
        marker="o",
        linewidth=2,
        color=COLORS["LightGBM"],
        label="Predicted probability",
    )

    ax.plot(
        data["score_decile"],
        data["actual_repurchase_rate"],
        marker="s",
        linewidth=2,
        color=COLORS["XGBoost"],
        label="Observed repurchase rate",
    )

    ax.set_xticks(range(1, 11))
    ax.set_ylim(0, 1)

    ax.yaxis.set_major_formatter(
        PercentFormatter(xmax=1)
    )

    ax.set_title(
        "Repurchase Probability Across Customer Deciles"
    )
    ax.set_xlabel(
        "Propensity decile (10 = highest predicted probability)"
    )
    ax.set_ylabel("Repurchase probability")

    ax.legend(frameon=False)

    save_figure(
        fig,
        "propensity_deciles.png",
    )


def main():
    required_files = {
        "backtest": "rolling_origin_folds.csv",
        "uncertainty": "holdout_uncertainty.csv",
        "calibration": "holdout_calibration.csv",
        "importance": "holdout_feature_importance.csv",
        "deciles": "holdout_propensity_deciles.csv",
    }

    tables = {}

    for name, filename in required_files.items():
        path = TABLE_DIR / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path}. Run the evaluation scripts first."
            )

        tables[name] = pd.read_csv(path)

    FIGURE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    plot_rolling_origin(tables["backtest"])
    plot_holdout_precision(tables["uncertainty"])
    plot_calibration(tables["calibration"])
    plot_feature_importance(tables["importance"])
    plot_propensity_deciles(tables["deciles"])

    print("\nFigures saved to:")
    print(FIGURE_DIR)

    for path in sorted(FIGURE_DIR.glob("*.png")):
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
