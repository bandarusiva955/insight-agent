"""Find how uploaded tables relate (shared keys) and join them safely.

A relationship is only reported when one side is a real key (almost all values
unique) and most values on the other side exist in it. Joins are LEFT joins from
the fact table, so a join can never drop or duplicate fact rows.
"""

from dataclasses import dataclass

import pandas as pd

KEY_UNIQUE_MIN = 0.98
MATCH_MIN = 0.5
MIN_ROWS = 5
MAX_COMBINED_COLUMNS = 100
COMBINED_NAME = "combined"


@dataclass
class Relationship:
    many_table: str  # table holding the foreign key
    many_column: str
    key_table: str  # table where the column is a unique key
    key_column: str
    match_share: float  # share of foreign-key values found in the key table
    orphan_rows: int  # foreign-key rows whose value is missing from the key table

    def describe(self) -> str:
        return (
            f"{self.many_table}.{self.many_column} -> {self.key_table}.{self.key_column} "
            f"(many-to-one, {self.match_share:.0%} of values match)"
        )


def _values(series: pd.Series) -> pd.Series:
    return series.dropna().astype(str).str.strip()


def _is_key(series: pd.Series) -> bool:
    values = _values(series)

    return len(values) >= MIN_ROWS and values.nunique() / len(values) >= KEY_UNIQUE_MIN


def find_relationships(frames: dict) -> list:
    """Look for same-named columns where one table holds the key for another."""

    found = []
    names = list(frames)

    for i, first in enumerate(names):
        for second in names[i + 1:]:
            for column in set(frames[first].columns) & set(frames[second].columns):
                for key_table, many_table in ((first, second), (second, first)):
                    key_side = frames[key_table][column]
                    many_side = frames[many_table][column]

                    if not _is_key(key_side) or _is_key(many_side):
                        continue

                    keys = set(_values(key_side))
                    many = _values(many_side)

                    if many.empty:
                        continue

                    matched = many.isin(keys)
                    share = float(matched.mean())

                    if share >= MATCH_MIN:
                        found.append(Relationship(
                            many_table, column, key_table, column, share,
                            int((~matched).sum()),
                        ))

    return found


def combine(frames: dict, relationships: list):
    """LEFT-join the dimension tables onto the fact table.

    Returns (frame, fact_table) or (None, None) when there is nothing to join.
    """

    if not relationships:
        return None, None

    fact = max({r.many_table for r in relationships}, key=lambda t: len(frames[t]))
    result = frames[fact].copy()
    joined = {fact}
    pending = list(relationships)
    progress = True

    while pending and progress:
        progress = False

        for rel in list(pending):
            if rel.many_table in joined and rel.key_table not in joined and rel.many_column in result.columns:
                dim = frames[rel.key_table]
                extra = [c for c in dim.columns if c != rel.key_column]
                rename = {c: f"{rel.key_table}_{c}" for c in extra if c in result.columns}
                dim = dim[[rel.key_column] + extra].rename(columns=rename).drop_duplicates(rel.key_column)
                left = result[rel.many_column].astype(str).str.strip().where(result[rel.many_column].notna())
                right = dim.assign(**{rel.key_column: dim[rel.key_column].astype(str).str.strip()})
                merged = result.assign(_join_key=left).merge(
                    right.rename(columns={rel.key_column: "_join_key"}),
                    on="_join_key", how="left",
                ).drop(columns="_join_key")

                if len(merged) != len(result) or merged.shape[1] > MAX_COMBINED_COLUMNS:
                    pending.remove(rel)
                    continue

                result = merged
                joined.add(rel.key_table)
                pending.remove(rel)
                progress = True

    if len(joined) < 2:
        return None, None

    return result, fact


def relationship_text(relationships: list) -> str:
    if not relationships:
        return ""

    return "RELATIONSHIPS (use these joins):\n" + "\n".join(
        f"- {r.many_table}.{r.many_column} = {r.key_table}.{r.key_column} (many-to-one)"
        for r in relationships
    )
