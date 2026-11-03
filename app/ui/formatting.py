"""Display helpers for the dashboard. No Streamlit imports, so they are testable."""

from decimal import Decimal
from numbers import Number

import pandas as pd

from app.metrics import MONEY_KEYWORDS


def is_money_column(name: str) -> bool:
    lowered = str(name).lower()

    return any(keyword in lowered for keyword in MONEY_KEYWORDS)


def _is_numeric(series: pd.Series) -> bool:
    values = series.dropna()

    return len(values) > 0 and all(
        isinstance(value, (Number, Decimal)) and not isinstance(value, bool)
        for value in values
    )


def style_results(dataframe: pd.DataFrame):
    """
    Return a pandas Styler: money columns as R$ 1,234.56, other numeric
    columns with thousands separators. Formatting is display-only, so the
    underlying values still sort and chart correctly.
    """

    display = dataframe.copy()
    formats = {}

    for column in display.columns:
        if not _is_numeric(display[column]):
            continue

        display[column] = pd.to_numeric(display[column], errors="coerce")

        if is_money_column(column):
            formats[column] = "R$ {:,.2f}"
        elif pd.api.types.is_integer_dtype(display[column]):
            formats[column] = "{:,.0f}"
        else:
            formats[column] = "{:,.2f}"

    return display.style.format(formats, na_rep="")
