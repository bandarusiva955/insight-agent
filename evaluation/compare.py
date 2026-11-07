"""Result comparison for the benchmark.

Two result sets match when they hold the same values, regardless of column
names or extra helper columns, and (only when the reference query sorts its
output) in the same row order. Numbers are compared after rounding, dates
after dropping a midnight time part.
"""

import itertools
import math
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

MAX_COLUMN_COMBINATIONS = 200


def _normalise(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    if value is pd.NaT:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float, Decimal)):
        number = float(value)

        return round(number, 2) if abs(number) >= 1 else round(number, 4)

    if isinstance(value, (pd.Timestamp, datetime)):
        stamp = pd.Timestamp(value)

        if stamp.tz is not None:
            stamp = stamp.tz_convert(None)

        return stamp.date() if stamp == stamp.normalize() else stamp.to_pydatetime()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        return value.strip()

    return value


def _sort_key(value):
    return (value is None, str(type(value).__name__), str(value))


def _column_values(frame: pd.DataFrame, column) -> list:
    return [_normalise(value) for value in frame[column].tolist()]


def results_match(expected: pd.DataFrame, actual: pd.DataFrame, ordered: bool) -> bool:
    """True when `actual` contains the values of `expected` (see module doc)."""

    if len(expected) != len(actual):
        return False

    if expected.shape[1] == 0:
        return actual.shape[1] == 0 or len(actual) == 0

    expected_columns = [_column_values(expected, c) for c in expected.columns]
    actual_columns = {c: _column_values(actual, c) for c in actual.columns}

    def same_multiset(left, right):
        return sorted(left, key=_sort_key) == sorted(right, key=_sort_key)

    candidates = []

    for values in expected_columns:
        matching = [
            name for name, other in actual_columns.items()
            if same_multiset(values, other)
        ]

        if not matching:
            return False

        candidates.append(matching)

    expected_rows = list(zip(*expected_columns))

    for count, combination in enumerate(itertools.product(*candidates)):
        if count >= MAX_COLUMN_COMBINATIONS:
            break

        if len(set(combination)) != len(combination):
            continue

        actual_rows = list(zip(*[actual_columns[name] for name in combination]))

        if ordered:
            if actual_rows == expected_rows:
                return True
        elif sorted(actual_rows, key=lambda r: [_sort_key(v) for v in r]) == sorted(
            expected_rows, key=lambda r: [_sort_key(v) for v in r]
        ):
            return True

    return False
