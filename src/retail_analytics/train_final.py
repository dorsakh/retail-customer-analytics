import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .data import FEATURE_COLUMNS, TARGET_COLUMN, load_data
from .models import make_lightgbm_model


MODEL_VERSION = "v1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = (
    PROJECT_ROOT
    / "artifacts"
    / "models"
    / MODEL_VERSION
)

MODEL_PATH = MODEL_DIR / "repurchase_model.txt"
METADATA_PATH = MODEL_DIR / "metadata.json"


def main() -> None:
    # Do not overwrite an existing model version.
    if MODEL_PATH.exists() or METADATA_PATH.exists():
        raise FileExistsError(
            f"Model version {MODEL_VERSION} already exists. "
            "Use a new version name for retraining."
        )

    data = load_data()

    X = data[FEATURE_COLUMNS]
    y = data[TARGET_COLUMN]

    if y.nunique() != 2:
        raise ValueError("Training data must contain both target classes.")

    # Train the production candidate using all labeled history.
    model = make_lightgbm_model()
    model.fit(X, y)

    if model.booster_.feature_name() != FEATURE_COLUMNS:
        raise ValueError("Model feature names do not match the feature contract.")

    # Save the fitted model.
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(MODEL_PATH))

    # Reload it and verify that predictions are unchanged.
    loaded_model = lgb.Booster(model_file=str(MODEL_PATH))

    sample = X.head(100)

    original_predictions = model.predict_proba(sample)[:, 1]
    loaded_predictions = loaded_model.predict(
        sample,
        validate_features=True,
    )

    np.testing.assert_allclose(
        original_predictions,
        loaded_predictions,
        rtol=1e-10,
        atol=1e-12,
    )

    # Store information needed to identify and reproduce this model.
    metadata = {
        "model_version": MODEL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_file": MODEL_PATH.name,
        "model_sha256": hashlib.sha256(
            MODEL_PATH.read_bytes()
        ).hexdigest(),
        "target_column": TARGET_COLUMN,
        "prediction_horizon_days": 7,
        "feature_window_days": 90,
        "feature_columns": FEATURE_COLUMNS,
        "training_observations": len(data),
        "training_households": int(data["household_key"].nunique()),
        "max_training_as_of_day": int(data["as_of_day"].max()),
        "model_parameters": model.get_params(),
        "python_version": platform.python_version(),
        "lightgbm_version": lgb.__version__,
        "pandas_version": pd.__version__,
        "training_scope": "all_labeled_historical_snapshots",
    }

    METADATA_PATH.write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Model version: {MODEL_VERSION}")
    print(f"Training observations: {len(data):,}")
    print(f"Features: {len(FEATURE_COLUMNS)}")
    print(f"Model saved to: {MODEL_PATH}")
    print(f"Metadata saved to: {METADATA_PATH}")
    print("Saved-model prediction check passed.")


if __name__ == "__main__":
    main()