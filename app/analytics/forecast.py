"""Monthly forecasting with Holt's linear trend and an honest backtest.

The model is deliberately simple. The backtest compares it with a naive
"next month = last month" baseline so the UI can say plainly when the
forecast is no better than that.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_POINTS = 8


@dataclass
class ForecastResult:
    history: pd.Series
    forecast: pd.DataFrame  # month, forecast, lower, upper
    alpha: float
    beta: float
    backtest_mape: float | None
    naive_mape: float | None
    note: str

    @property
    def beats_naive(self) -> bool | None:
        if self.backtest_mape is None or self.naive_mape is None:
            return None

        return self.backtest_mape < self.naive_mape


def trim_partial_months(series: pd.Series, min_share: float = 0.25) -> pd.Series:
    """
    Drop leading/trailing months that are mostly empty (partial coverage).

    A month below `min_share` of the median month is treated as incomplete.
    Gaps are filled by interpolation so the series is contiguous.
    """

    series = series.sort_index().astype(float)

    if series.empty:
        return series

    floor = series.median() * min_share

    while len(series) and series.iloc[0] < floor:
        series = series.iloc[1:]

    while len(series) and series.iloc[-1] < floor:
        series = series.iloc[:-1]

    if len(series) < 2:
        return series

    full_index = pd.date_range(series.index[0], series.index[-1], freq="MS")

    return series.reindex(full_index).interpolate()


def _holt_fit(values: np.ndarray, alpha: float, beta: float):
    level = values[0]
    trend = values[1] - values[0]
    errors = []

    for observed in values[1:]:
        predicted = level + trend
        errors.append(observed - predicted)
        new_level = alpha * observed + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        level = new_level

    return level, trend, np.array(errors)


def _best_params(values: np.ndarray):
    best = None

    for alpha in np.arange(0.1, 1.0, 0.1):
        for beta in np.arange(0.05, 0.55, 0.1):
            _, _, errors = _holt_fit(values, alpha, beta)
            sse = float(np.sum(errors**2))

            if best is None or sse < best[0]:
                best = (sse, float(alpha), float(beta))

    return best[1], best[2]


def _project(values: np.ndarray, alpha: float, beta: float, periods: int):
    level, trend, errors = _holt_fit(values, alpha, beta)
    sigma = float(np.std(errors, ddof=1)) if len(errors) > 2 else 0.0
    steps = np.arange(1, periods + 1)

    point = np.maximum(level + steps * trend, 0.0)
    margin = 1.96 * sigma * np.sqrt(steps)

    return point, np.maximum(point - margin, 0.0), point + margin


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    mask = actual != 0

    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])))


def forecast_series(
    series: pd.Series,
    periods: int = 3,
    holdout: int = 3,
) -> ForecastResult:
    """Forecast the next `periods` months of a monthly series."""

    series = series.sort_index().astype(float)

    if len(series) < MIN_POINTS:
        raise ValueError(
            f"At least {MIN_POINTS} complete months are needed to forecast "
            f"(got {len(series)})."
        )

    values = series.to_numpy()
    alpha, beta = _best_params(values)
    point, lower, upper = _project(values, alpha, beta, periods)

    future = pd.date_range(
        series.index[-1] + pd.offsets.MonthBegin(1), periods=periods, freq="MS"
    )
    forecast = pd.DataFrame(
        {"month": future, "forecast": point, "lower": lower, "upper": upper}
    )

    backtest_mape = naive_mape = None

    if len(series) >= MIN_POINTS + holdout:
        train, actual = values[:-holdout], values[-holdout:]
        train_alpha, train_beta = _best_params(train)
        predicted, _, _ = _project(train, train_alpha, train_beta, holdout)

        backtest_mape = _mape(actual, predicted)
        naive_mape = _mape(actual, np.full(holdout, train[-1]))

    if backtest_mape is None:
        note = "Too little history for a backtest."
    elif backtest_mape < naive_mape:
        note = (
            f"On the last {holdout} months the model's error "
            f"({backtest_mape:.1%}) beat the naive baseline ({naive_mape:.1%})."
        )
    else:
        note = (
            f"On the last {holdout} months the model's error "
            f"({backtest_mape:.1%}) did NOT beat the naive baseline "
            f"({naive_mape:.1%}); treat this forecast with caution."
        )

    return ForecastResult(
        history=series,
        forecast=forecast,
        alpha=alpha,
        beta=beta,
        backtest_mape=backtest_mape,
        naive_mape=naive_mape,
        note=note,
    )
