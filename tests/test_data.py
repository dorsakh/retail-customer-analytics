import pandas as pd
import pytest

from retail_analytics.data import split_by_time


def test_temporal_split_boundaries():
    days = [180, 540, 570, 600, 630, 660, 690]

    data = pd.DataFrame({
        "as_of_day": days,
        "household_key": [f"h{i}" for i in range(len(days))],
    })

    splits = split_by_time(data)

    assert set(splits["train"]["as_of_day"]) == {180, 540}
    assert set(splits["validation"]["as_of_day"]) == {570, 600}
    assert set(splits["test"]["as_of_day"]) == {630, 660, 690}

    assert sum(len(split) for split in splits.values()) == len(data)


def test_prediction_windows_do_not_overlap():
    data = pd.DataFrame({
        "as_of_day": [180, 540, 570, 600, 630, 690],
    })

    splits = split_by_time(data)

    train_end = splits["train"]["as_of_day"].max()
    validation_start = splits["validation"]["as_of_day"].min()
    validation_end = splits["validation"]["as_of_day"].max()
    test_start = splits["test"]["as_of_day"].min()

    assert train_end + 7 < validation_start
    assert validation_end + 7 < test_start


def test_unassigned_observations_raise_error():
    data = pd.DataFrame({
        "as_of_day": [180, 570, 630, 720],
    })

    with pytest.raises(ValueError, match="not assigned"):
        split_by_time(data)