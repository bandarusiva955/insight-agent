"""Work out what each column is, and which charts make sense for the data."""

from dataclasses import dataclass, field

import pandas as pd

ID_HINTS = ("id", "key", "code", "uuid", "sku", "number", "no")
CATEGORY_MAX_UNIQUE = 30


@dataclass
class ColumnProfile:
    name: str
    role: str  # id | numeric | datetime | category | boolean | text
    dtype: str
    nunique: int
    missing_share: float
    examples: list = field(default_factory=list)


def _looks_like_id(name: str) -> bool:
    parts = name.lower().split("_")

    return any(hint in parts for hint in ID_HINTS) or name.lower().endswith("id")


def profile_frame(frame: pd.DataFrame) -> list:
    profiles = []
    rows = max(len(frame), 1)

    for column in frame.columns:
        series = frame[column]
        values = series.dropna()
        nunique = int(values.nunique())

        if pd.api.types.is_bool_dtype(series) or (
            series.dtype == object and set(values.unique()) <= {True, False} and len(values)
        ):
            role = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(series):
            role = "datetime"
        elif pd.api.types.is_numeric_dtype(series):
            is_integer_like = bool((values % 1 == 0).all()) if len(values) else False

            if _looks_like_id(column) and nunique / rows > 0.9 and is_integer_like:
                role = "id"
            else:
                role = "numeric"
        else:
            unique_ratio = nunique / max(len(values), 1)

            if nunique / rows > 0.95 and (_looks_like_id(column) or nunique > CATEGORY_MAX_UNIQUE):
                role = "id" if _looks_like_id(column) else "text"
            elif nunique <= CATEGORY_MAX_UNIQUE or unique_ratio < 0.2:
                role = "category"
            else:
                role = "text"

        profiles.append(
            ColumnProfile(
                name=column,
                role=role,
                dtype=str(series.dtype),
                nunique=nunique,
                missing_share=float(series.isna().mean()),
                examples=[str(v) for v in values.drop_duplicates().head(5)],
            )
        )

    return profiles


def by_role(profiles: list, role: str) -> list:
    return [p.name for p in profiles if p.role == role]


def schema_text(table: str, profiles: list, include_examples: bool) -> str:
    """Compact description of the table for the LLM prompt."""

    lines = [f"TABLE: {table}", "COLUMNS:"]

    for p in profiles:
        sql_type = {
            "numeric": "numeric", "datetime": "timestamp", "boolean": "boolean",
        }.get(p.role, "text")
        extra = f" ({p.role})"

        if include_examples and p.role in ("category", "boolean") and p.examples:
            extra += " e.g. " + ", ".join(repr(v) for v in p.examples[:5])

        lines.append(f"- {p.name}: {sql_type}{extra}")

    return "\n".join(lines)
