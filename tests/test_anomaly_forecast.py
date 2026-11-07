"""Anomaly detection and forecasting on controlled inputs (no database)."""

import numpy as np
import pandas as pd
import pytest

from app.analytics.anomaly import describe_anomalies, detect_anomalies
from app.analytics.forecast import (
    forecast_series,
    trim_partial_months,
)


def _daily(values, start="2024-01-01"):
    return pd.DataFrame(
        {"day": pd.date_range(start, periods=len(values)), "orders": values}
    )


def test_flat_series_with_one_spike_is_flagged():
    rng = np.random.default_rng(1)
    values = list(rng.normal(100, 5, 40))
    values[30] = 400

    result = detect_anomalies(_daily(values), "orders")

    flagged = result[result.is_anomaly]
    assert list(flagged.index) == [30]
    assert flagged.iloc[0]["direction"] == "spike"


def test_drop_is_flagged_as_drop():
    rng = np.random.default_rng(2)
    values = list(rng.normal(100, 5, 40))
    values[25] = 5

    result = detect_anomalies(_daily(values), "orders")

    assert result.loc[25, "direction"] == "drop"


def test_false_alarm_rate_on_pure_noise_is_low():
    flagged = checked = 0

    for seed in range(100):
        rng = np.random.default_rng(seed)
        result = detect_anomalies(_daily(rng.normal(100, 5, 90)), "orders")
        flagged += int(result.is_anomaly.sum())
        checked += len(result) - 7

    assert flagged / checked < 0.01


def test_early_rows_are_never_flagged():
    values = [100] * 3 + [1000] + [100] * 30

    result = detect_anomalies(_daily(values), "orders", min_history=7)

    assert not result.loc[3, "is_anomaly"]


def test_constant_history_still_catches_a_jump():
    values = [50.0] * 20 + [80.0]

    result = detect_anomalies(_daily(values), "orders")

    assert result.iloc[-1]["is_anomaly"]


def test_describe_anomalies_text():
    rng = np.random.default_rng(1)
    values = list(rng.normal(100, 5, 40))
    values[30] = 400

    result = detect_anomalies(_daily(values), "orders")
    lines = describe_anomalies(result, "orders", "orders")

    assert len(lines) == 1
    assert "spike" in lines[0]
    assert "2024-01-31" in lines[0]


def _monthly(values, start="2017-01-01"):
    return pd.Series(
        values, index=pd.date_range(start, periods=len(values), freq="MS")
    )


def test_trim_partial_months_drops_tiny_edges_only():
    series = _monthly([5, 600, 700, 800, 900, 1000, 950, 3])

    trimmed = trim_partial_months(series)

    assert list(trimmed.values) == [600, 700, 800, 900, 1000, 950]


def test_trim_fills_interior_gaps():
    series = _monthly([100, 110, 120, 130, 140, 150])
    series = series.drop(series.index[2])

    trimmed = trim_partial_months(series)

    assert len(trimmed) == 6
    assert trimmed.iloc[2] == pytest.approx(120.0)  # midway between 110 and 130


def test_forecast_follows_a_linear_trend():
    series = _monthly([100 + 10 * i for i in range(18)])

    result = forecast_series(series, periods=3)

    expected = [100 + 10 * i for i in range(18, 21)]
    assert result.forecast["forecast"].tolist() == pytest.approx(expected, rel=0.03)
    assert (result.forecast["lower"] <= result.forecast["forecast"]).all()
    assert (result.forecast["upper"] >= result.forecast["forecast"]).all()
    assert result.forecast["month"].iloc[0] == pd.Timestamp("2018-07-01")
    assert result.beats_naive is True


def test_forecast_never_goes_negative():
    series = _monthly([200 - 25 * i for i in range(8)] + [10, 5, 3, 2])

    result = forecast_series(series, periods=4)

    assert (result.forecast[["forecast", "lower"]] >= 0).all().all()


def test_forecast_requires_enough_history():
    with pytest.raises(ValueError, match="At least"):
        forecast_series(_monthly([1, 2, 3, 4]))


def test_forecast_note_is_honest_about_noise():
    rng = np.random.default_rng(5)
    series = _monthly(list(rng.normal(1000, 300, 20)))

    result = forecast_series(series)

    assert result.backtest_mape is not None
    assert ("beat the naive" in result.note) or ("NOT beat" in result.note)
