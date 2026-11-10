"""Customer analytics for any uploaded transactions: RFM segments and cohort retention.

Pure pandas, so every number is exact and checkable. Columns are detected from
their names and types; when they cannot be found the functions return None.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.workspace.profile import by_role

CUSTOMER_HINTS = ("customer", "client", "user", "buyer", "member", "account")
AMOUNT_HINTS = ("revenue", "sales", "amount", "total", "spend", "value")
PRICE_HINTS = ("price", "rate", "cost")
QUANTITY_HINTS = ("quantity", "qty", "units")
ORDER_HINTS = ("order", "invoice", "transaction", "txn", "bill")
MIN_CUSTOMERS = 20
COHORT_MONTHS = 12
MAX_COHORTS = 12

SEGMENT_ORDER = ["Champions", "Loyal", "New", "Needs attention", "At risk", "Lost"]


@dataclass
class Columns:
    customer: str
    date: str
    amount: pd.Series  # per-row value
    amount_name: str
    order: str | None


def _find(names, hints, exact_id=False):
    for name in names:
        parts = name.lower().split("_")

        if any(h in parts for h in hints) and (not exact_id or "id" in parts or "key" in parts or "code" in parts):
            return name

    return None


def detect_columns(frame: pd.DataFrame, profiles: list) -> Columns | None:
    ids = by_role(profiles, "id") + by_role(profiles, "category") + by_role(profiles, "text")
    customer = _find([c for c in ids if frame[c].nunique() >= MIN_CUSTOMERS], CUSTOMER_HINTS, exact_id=True)
    dates = by_role(profiles, "datetime")

    if customer is None or not dates:
        return None

    numeric = by_role(profiles, "numeric")
    amount_name = _find(numeric, AMOUNT_HINTS)

    if amount_name:
        amount = frame[amount_name]
    else:
        price = _find(numeric, PRICE_HINTS)
        quantity = _find(numeric, QUANTITY_HINTS)

        if price is None:
            return None

        amount = frame[price] * (frame[quantity] if quantity else 1)
        amount_name = f"{quantity} x {price}" if quantity else price

    order = _find(by_role(profiles, "id") + by_role(profiles, "text"), ORDER_HINTS, exact_id=True)

    return Columns(customer, dates[0], pd.to_numeric(amount, errors="coerce"), amount_name, order)


def _score(series: pd.Series, ascending: bool) -> pd.Series:
    """1-5 quintile score; customers with equal values always get equal scores."""

    ranks = series.rank(method="average", ascending=ascending, pct=True)

    return np.ceil(ranks * 5).clip(1, 5).astype(int)


def _segment(row) -> str:
    r, f = row["r_score"], row["f_score"]

    if r >= 4 and f >= 4:
        return "Champions"
    if f >= 4:
        return "Loyal"
    if r >= 4 and f <= 2:
        return "New"
    if r <= 2 and f >= 3:
        return "At risk"
    if r <= 2:
        return "Lost"

    return "Needs attention"


def rfm(frame: pd.DataFrame, columns: Columns):
    """Return (customer table, segment summary) or (None, None) if too little data."""

    data = pd.DataFrame({
        "customer": frame[columns.customer],
        "date": frame[columns.date],
        "amount": columns.amount,
        "order": frame[columns.order] if columns.order else np.arange(len(frame)),
    }).dropna(subset=["customer", "date"])

    if data["customer"].nunique() < MIN_CUSTOMERS:
        return None, None

    snapshot = data["date"].max() + pd.Timedelta(days=1)
    table = data.groupby("customer").agg(
        recency_days=("date", lambda d: (snapshot - d.max()).days),
        frequency=("order", "nunique"),
        monetary=("amount", "sum"),
    )
    table["r_score"] = _score(table["recency_days"], ascending=False)
    table["f_score"] = _score(table["frequency"], ascending=True)
    table["m_score"] = _score(table["monetary"], ascending=True)
    table["segment"] = table.apply(_segment, axis=1)

    total = table["monetary"].sum()
    summary = table.groupby("segment").agg(
        customers=("monetary", "size"),
        revenue=("monetary", "sum"),
        avg_orders=("frequency", "mean"),
        avg_days_since_last=("recency_days", "mean"),
    )
    summary["customer_share"] = summary["customers"] / len(table)
    summary["revenue_share"] = summary["revenue"] / total if total else 0.0
    order = [s for s in SEGMENT_ORDER if s in summary.index]

    return table.reset_index(), summary.loc[order].reset_index()


def cohort_retention(frame: pd.DataFrame, columns: Columns):
    """Share of each first-purchase-month cohort that buys again in later months."""

    data = frame[[columns.customer, columns.date]].dropna()
    data = data.assign(month=data[columns.date].dt.to_period("M"))
    first = data.groupby(columns.customer)["month"].min().rename("cohort")
    data = data.join(first, on=columns.customer)
    data["offset"] = (data["month"] - data["cohort"]).apply(lambda x: x.n)
    data = data[data["offset"] <= COHORT_MONTHS]
    counts = data.groupby(["cohort", "offset"])[columns.customer].nunique().unstack(fill_value=0)

    if counts.empty or 0 not in counts.columns:
        return None

    sizes = counts[0]
    keep = sizes[sizes >= MIN_CUSTOMERS].index

    if len(keep) < 2:
        return None

    last_month = frame[columns.date].max().to_period("M")
    matrix = counts.loc[keep].div(sizes.loc[keep], axis=0)

    for cohort in matrix.index:
        for offset in matrix.columns:
            if cohort + offset > last_month:
                matrix.loc[cohort, offset] = np.nan  # month has not happened yet

    matrix = matrix.tail(MAX_COHORTS)
    matrix.index = [str(c) for c in matrix.index]
    matrix.insert(0, "customers", sizes.loc[keep].tail(MAX_COHORTS).to_numpy())

    return matrix


def headline(table: pd.DataFrame, summary: pd.DataFrame) -> list:
    """Plain-English takeaways computed from the RFM result."""

    lines = []
    champions = summary[summary["segment"] == "Champions"]

    if not champions.empty:
        row = champions.iloc[0]
        lines.append(
            f"Champions are {row['customer_share']:.0%} of customers but bring "
            f"{row['revenue_share']:.0%} of revenue."
        )

    risk = summary[summary["segment"].isin(["At risk", "Lost"])]

    if not risk.empty:
        lines.append(
            f"{int(risk['customers'].sum()):,} customers ({risk['customer_share'].sum():.0%}) are "
            f"at risk or lost, worth {risk['revenue_share'].sum():.0%} of past revenue. "
            "A win-back campaign should start here."
        )

    top = table.sort_values("monetary", ascending=False).head(max(1, len(table) // 10))
    lines.append(
        f"The top 10% of customers ({len(top):,}) generate {top['monetary'].sum() / table['monetary'].sum():.0%} of revenue."
        if table["monetary"].sum() else "Revenue values are missing, so spend-based segments are not shown."
    )

    return lines
