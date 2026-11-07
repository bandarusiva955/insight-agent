"""
Automatic, transparent data cleaning.

Every change is recorded as a step in a report so the user can see exactly
what happened. The original upload is never modified; cleaning works on a
copy. Rules that can destroy information (imputing, removing outliers) are
deliberately NOT applied: they are only reported.
"""

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MISSING_TOKENS = {
    "", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "#n/a", "missing",
}
TRUE_TOKENS = {"true", "yes", "y", "t"}
FALSE_TOKENS = {"false", "no", "n", "f"}
PARSE_SHARE = 0.9  # share of non-null values that must parse to convert a column
CATEGORY_MAX_UNIQUE = 60


@dataclass
class Step:
    kind: str
    detail: str
    count: int = 0
    column: str | None = None


@dataclass
class CleanResult:
    frame: pd.DataFrame
    steps: list = field(default_factory=list)
    rows_before: int = 0
    rows_after: int = 0
    outliers: dict = field(default_factory=dict)  # column -> count (reported only)
    missing: dict = field(default_factory=dict)  # column -> share (after cleaning)

    def add(self, kind, detail, count=0, column=None):
        self.steps.append(Step(kind, detail, int(count), column))


def snake_case(name) -> str:
    text = str(name).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()

    return text or "column"


def _unique_names(names: list) -> list:
    seen, result = {}, []

    for name in names:
        if name[:1].isdigit():
            name = f"c_{name}"

        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count + 1}")

    return result


def _is_text(series: pd.Series) -> bool:
    return not (
        pd.api.types.is_numeric_dtype(series)
        or pd.api.types.is_datetime64_any_dtype(series)
        or pd.api.types.is_bool_dtype(series)
    )


def _clean_strings(series: pd.Series):
    """Strip whitespace and turn missing-like tokens into NaN."""

    as_text = series.astype("object")
    is_str = as_text.map(lambda v: isinstance(v, str))
    stripped = as_text.where(~is_str, as_text.map(lambda v: v.strip() if isinstance(v, str) else v))
    trimmed = int((is_str & (stripped != as_text)).sum())

    def is_missing(value):
        return isinstance(value, str) and value.lower() in MISSING_TOKENS

    missing_mask = stripped.map(is_missing)
    converted = int(missing_mask.sum())

    return stripped.mask(missing_mask, np.nan), trimmed, converted


_NUMBER_STRIP = re.compile(r"[\s$€£₹¥%,]")
_NUMBER_FORM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _to_numeric(series: pd.Series):
    """Parse numbers written like '1,234', '$12.50', '45%', '(30)'."""

    text = series.dropna().astype(str)

    if text.empty:
        return None

    # Leading zeros ("007", zip codes, phone numbers) mean identifiers, not numbers.
    if text.str.match(r"^0\d+$").any():
        return None

    def parse(value: str):
        negative = value.startswith("(") and value.endswith(")")
        cleaned = _NUMBER_STRIP.sub("", value)

        if negative:
            cleaned = cleaned[1:-1]

        # Anything left that is not a plain number ("25/12/2024", "abc1") stays text.
        if not _NUMBER_FORM.match(cleaned):
            return np.nan

        number = float(cleaned)

        return -number if negative else number

    parsed = text.map(parse)
    share = parsed.notna().mean()

    if share < PARSE_SHARE:
        return None

    result = pd.Series(np.nan, index=series.index, dtype="float64")
    result.loc[parsed.index] = parsed

    return result, int(parsed.isna().sum())


_DATE_LIKE = re.compile(
    r"^\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}[ -][A-Za-z]{3,9}[ -,]*\d{2,4}"
    r"|[A-Za-z]{3,9}[ .]\d{1,2},?[ ]\d{2,4})([ T]\d{1,2}:\d{2}(:\d{2})?.*)?\s*$"
)


def _to_datetime(series: pd.Series):
    text = series.dropna().astype(str)

    if text.empty or text.str.match(_DATE_LIKE).mean() < PARSE_SHARE:
        return None

    dayfirst, note = False, None
    parts = text.str.extract(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}")

    if parts.notna().all(axis=1).any():
        first = pd.to_numeric(parts[0], errors="coerce")
        second = pd.to_numeric(parts[1], errors="coerce")

        if first.max() > 12:
            dayfirst = True
        elif second.max() > 12:
            dayfirst = False
        else:
            note = "ambiguous day/month order; assumed month first"

    parsed = pd.to_datetime(text, errors="coerce", format="mixed", dayfirst=dayfirst)

    if parsed.notna().mean() < PARSE_SHARE:
        return None

    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    result.loc[parsed.index] = parsed.dt.tz_localize(None) if parsed.dt.tz is not None else parsed

    return result, int(parsed.isna().sum()), dayfirst, note


def _to_bool(series: pd.Series):
    text = series.dropna().astype(str).str.lower()

    if text.empty:
        return None

    values = set(text.unique())

    if values <= (TRUE_TOKENS | FALSE_TOKENS) and len(values) >= 2:
        return series.map(
            lambda v: np.nan if pd.isna(v) else str(v).lower() in TRUE_TOKENS
        ).astype("object")

    return None


def _standardize_case(series: pd.Series):
    """Merge 'Male', 'male ', 'MALE' into the most common spelling."""

    values = series.dropna().astype(str)

    if values.nunique() > CATEGORY_MAX_UNIQUE * 3 or values.empty:
        return series, 0

    key = values.str.casefold().str.replace(r"\s+", " ", regex=True)
    frame = pd.DataFrame({"value": values, "key": key})
    best = (
        frame.groupby(["key", "value"]).size().reset_index(name="n")
        .sort_values(["key", "n"], ascending=[True, False])
        .drop_duplicates("key")
        .set_index("key")["value"]
    )
    mapped = key.map(best)
    changed = int((mapped != values).sum())

    if not changed:
        return series, 0

    result = series.copy()
    result.loc[values.index] = mapped

    return result, changed


def _iqr_outliers(series: pd.Series) -> int:
    values = series.dropna()

    if len(values) < 20:
        return 0

    q1, q3 = values.quantile([0.25, 0.75])
    spread = q3 - q1

    if spread == 0:
        return 0

    return int(((values < q1 - 3 * spread) | (values > q3 + 3 * spread)).sum())


def clean_dataframe(raw: pd.DataFrame) -> CleanResult:
    """Clean a raw upload and describe every change."""

    frame = raw.copy()
    result = CleanResult(frame=frame, rows_before=len(raw))

    # --- column names -------------------------------------------------------
    old_names = [str(c) for c in frame.columns]
    new_names = _unique_names([snake_case(c) for c in old_names])
    renamed = sum(1 for a, b in zip(old_names, new_names) if a != b)
    frame.columns = new_names

    if renamed:
        result.add("rename", f"Standardised {renamed} column name(s) to snake_case.", renamed)

    # --- empty rows / columns ----------------------------------------------
    frame = frame.replace(r"^\s*$", np.nan, regex=True)
    empty_cols = [c for c in frame.columns if frame[c].isna().all()]

    if empty_cols:
        frame = frame.drop(columns=empty_cols)
        result.add("drop_columns", f"Dropped {len(empty_cols)} completely empty column(s): "
                   + ", ".join(empty_cols), len(empty_cols))

    empty_rows = int(frame.isna().all(axis=1).sum())

    if empty_rows:
        frame = frame.dropna(how="all")
        result.add("drop_rows", f"Dropped {empty_rows} completely empty row(s).", empty_rows)

    # --- per-column: strings, types, categories ----------------------------
    for column in list(frame.columns):
        series = frame[column]

        if not _is_text(series) and series.dtype != object:
            continue

        series, trimmed, missing_tokens = _clean_strings(series)

        if trimmed:
            result.add("trim", f"Trimmed leading/trailing spaces in {trimmed} value(s).",
                       trimmed, column)

        if missing_tokens:
            result.add("missing_tokens",
                       f"Converted {missing_tokens} placeholder value(s) like 'N/A' or '-' to empty.",
                       missing_tokens, column)

        converted = False

        boolean = _to_bool(series)
        if boolean is not None:
            series, converted = boolean, True
            result.add("type", "Converted to true/false.", 0, column)

        if not converted:
            numeric = _to_numeric(series)
            if numeric is not None:
                series, failed = numeric
                converted = True
                result.add("type", "Converted text to numbers"
                           + (f"; {failed} unreadable value(s) became empty." if failed else "."),
                           failed, column)

        if not converted:
            dated = _to_datetime(series)
            if dated is not None:
                series, failed, dayfirst, note = dated
                converted = True
                detail = "Converted text to dates"
                detail += " (day first)" if dayfirst else ""
                detail += f"; {failed} unreadable value(s) became empty" if failed else ""
                detail += f"; note: {note}" if note else ""
                result.add("type", detail + ".", failed, column)

        if not converted and series.dropna().map(lambda v: isinstance(v, str)).all():
            series, changed = _standardize_case(series)

            if changed:
                result.add("standardize",
                           f"Unified {changed} value(s) that differed only by case or spacing.",
                           changed, column)

        frame[column] = series

    # --- duplicates ---------------------------------------------------------
    duplicates = int(frame.duplicated().sum())

    if duplicates:
        frame = frame.drop_duplicates().reset_index(drop=True)
        result.add("duplicates", f"Removed {duplicates} exact duplicate row(s).", duplicates)

    frame = frame.reset_index(drop=True)

    # --- reported only: outliers and missing values -------------------------
    for column in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[column]):
            count = _iqr_outliers(frame[column])

            if count:
                result.outliers[column] = count

        share = float(frame[column].isna().mean())

        if share > 0:
            result.missing[column] = share

    if result.outliers:
        result.add("outliers",
                   f"Flagged extreme values (not removed) in {len(result.outliers)} column(s): "
                   + ", ".join(f"{c} ({n})" for c, n in result.outliers.items()) + ".",
                   sum(result.outliers.values()))

    heavy = [c for c, s in result.missing.items() if s >= 0.5]

    if heavy:
        result.add("missing_warning",
                   "More than half the values are missing in: " + ", ".join(heavy)
                   + ". Results using these columns may be unreliable.", len(heavy))

    result.frame = frame
    result.rows_after = len(frame)

    if not result.steps:
        result.add("none", "The data was already clean; no changes were needed.")

    return result
