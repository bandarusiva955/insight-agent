"""Root-cause analysis: why did a metric change between two periods?

Everything here is deterministic SQL plus arithmetic, so every statement in
the report can be traced to a number. An optional LLM step (app.llm.narrator)
only rephrases these findings; it is never the source of a claim.

What the report can and cannot say: it shows WHERE a change happened (which
categories, states, and operational metrics moved). It shows association, not
proof of cause.
"""

import calendar
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import pandas as pd

from app.analytics.kpi import KpiFilters, _query, get_kpis

MIN_ORDERS_FOR_STATE_CLAIMS = 20


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # inclusive
    label: str = ""

    def as_filters(self, base: KpiFilters) -> KpiFilters:
        return replace(base, date_from=self.start, date_to=self.end)


def month_window(year: int, month: int) -> Window:
    last_day = calendar.monthrange(year, month)[1]

    return Window(
        date(year, month, 1),
        date(year, month, last_day),
        f"{calendar.month_abbr[month]} {year}",
    )


def previous_month_window(window: Window) -> Window:
    last_of_previous = window.start - timedelta(days=1)

    return month_window(last_of_previous.year, last_of_previous.month)


@dataclass
class RcaReport:
    current: Window
    baseline: Window
    metric: str
    current_kpis: dict
    baseline_kpis: dict
    change: float | None
    change_pct: float | None
    volume_effect: float | None
    value_effect: float | None
    categories: pd.DataFrame
    states: pd.DataFrame
    operations: pd.DataFrame
    state_delivery: pd.DataFrame
    findings: list = field(default_factory=list)

    def to_context(self) -> str:
        """Compact fact sheet for the narrator."""

        lines = [
            f"Metric: {self.metric}",
            f"Current period: {self.current.label}",
            f"Baseline period: {self.baseline.label}",
        ]
        lines += [f"- {finding}" for finding in self.findings]

        return "\n".join(lines)


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""

    return f"{sign}R$ {abs(value):,.0f}"


def _segment_revenue(window: Window, dimension: str, base: KpiFilters) -> pd.DataFrame:
    if dimension not in ("category", "state"):
        raise ValueError("dimension must be 'category' or 'state'")

    return _query(
        window.as_filters(base),
        f"""
        SELECT {dimension} AS segment, SUM(price) AS revenue
        FROM item_base
        WHERE order_status = 'delivered'
        GROUP BY {dimension}
        """,
    )


def _state_delivery(window: Window, base: KpiFilters) -> pd.DataFrame:
    return _query(
        window.as_filters(base),
        """
        SELECT
            state,
            COUNT(*) AS orders,
            AVG(EXTRACT(EPOCH FROM (delivered_at - purchased_at)) / 86400.0)
                AS avg_delivery_days
        FROM order_level
        WHERE order_status = 'delivered' AND delivered_at IS NOT NULL
        GROUP BY state
        """,
    )


def _contributions(current: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    merged = current.merge(
        baseline, on="segment", how="outer", suffixes=("_current", "_baseline")
    ).fillna(0.0)

    merged["change"] = merged["revenue_current"] - merged["revenue_baseline"]

    # Contribution to growth: this segment's change as a share of the TOTAL
    # baseline revenue. Unlike "share of the net change", it stays meaningful
    # when segments offset each other and the net change is small.
    baseline_total = merged["revenue_baseline"].sum()
    merged["contribution_pts"] = (
        merged["change"] / baseline_total if baseline_total else 0.0
    )

    return merged.reindex(
        merged["change"].abs().sort_values(ascending=False).index
    ).reset_index(drop=True)


def _operations_table(current: dict, baseline: dict) -> pd.DataFrame:
    rows = [
        ("Avg delivery days", "avg_delivery_days", "{:.1f}"),
        ("On-time delivery rate", "on_time_rate", "{:.1%}"),
        ("Cancel rate", "cancel_rate", "{:.1%}"),
        ("Avg review score", "avg_review_score", "{:.2f}"),
    ]
    records = []

    for label, key, fmt in rows:
        new, old = current.get(key), baseline.get(key)

        records.append(
            {
                "metric": label,
                "baseline": None if old is None else fmt.format(old),
                "current": None if new is None else fmt.format(new),
                "change": None if new is None or old is None else new - old,
                "key": key,
            }
        )

    return pd.DataFrame(records)


def explain_change(
    current: Window,
    baseline: Window,
    filters: KpiFilters | None = None,
) -> RcaReport:
    """Compare two periods and attribute the revenue change."""

    base = filters or KpiFilters()
    base = replace(base, date_from=None, date_to=None)

    current_kpis = get_kpis(current.as_filters(base))
    baseline_kpis = get_kpis(baseline.as_filters(base))

    revenue_now, revenue_before = current_kpis["revenue"], baseline_kpis["revenue"]
    change = revenue_now - revenue_before
    change_pct = change / revenue_before if revenue_before else None

    orders_now, orders_before = current_kpis["orders"], baseline_kpis["orders"]
    aov_now, aov_before = current_kpis["aov"], baseline_kpis["aov"]

    if aov_now is not None and aov_before is not None:
        volume_effect = (orders_now - orders_before) * aov_before
        value_effect = (aov_now - aov_before) * orders_now
    else:
        volume_effect = value_effect = None

    categories = _contributions(
        _segment_revenue(current, "category", base),
        _segment_revenue(baseline, "category", base),
    )
    states = _contributions(
        _segment_revenue(current, "state", base),
        _segment_revenue(baseline, "state", base),
    )
    operations = _operations_table(current_kpis, baseline_kpis)

    delivery_now = _state_delivery(current, base)
    delivery_before = _state_delivery(baseline, base)
    state_delivery = delivery_now.merge(
        delivery_before, on="state", suffixes=("_current", "_baseline")
    )
    state_delivery["change_days"] = (
        state_delivery["avg_delivery_days_current"]
        - state_delivery["avg_delivery_days_baseline"]
    )
    state_delivery = state_delivery.sort_values(
        "change_days", ascending=False
    ).reset_index(drop=True)

    report = RcaReport(
        current=current,
        baseline=baseline,
        metric="revenue",
        current_kpis=current_kpis,
        baseline_kpis=baseline_kpis,
        change=change,
        change_pct=change_pct,
        volume_effect=volume_effect,
        value_effect=value_effect,
        categories=categories,
        states=states,
        operations=operations,
        state_delivery=state_delivery,
    )
    report.findings = _write_findings(report)

    return report


def _segment_sentence(table: pd.DataFrame, noun: str) -> list:
    """Biggest decreases and increases, so offsetting moves are both visible."""

    sentences = []

    for label, subset, ascending in (
        ("decreases", table[table["change"] < 0], True),
        ("increases", table[table["change"] > 0], False),
    ):
        top = subset.sort_values("change", ascending=ascending).head(3)

        if top.empty:
            continue

        parts = [
            f"{row.segment} ({_money(row.change)}, "
            f"{row.contribution_pts * 100:+.1f} pts of growth)"
            for row in top.itertuples()
        ]
        sentences.append(
            f"Biggest {noun} {label}: " + "; ".join(parts) + "."
        )

    return sentences


def _write_findings(report: RcaReport) -> list:
    findings = []
    current, baseline = report.current.label, report.baseline.label

    if report.change_pct is None:
        return [f"No delivered revenue in {baseline}, so no comparison is possible."]

    verb = "rose" if report.change >= 0 else "fell"
    findings.append(
        f"Revenue {verb} {abs(report.change_pct):.1%} from {baseline} to "
        f"{current} ({_money(report.baseline_kpis['revenue'])} -> "
        f"{_money(report.current_kpis['revenue'])}, {_money(report.change)})."
    )

    if report.volume_effect is not None:
        orders_before = report.baseline_kpis["orders"]
        orders_now = report.current_kpis["orders"]
        dominant = (
            "order volume"
            if abs(report.volume_effect) >= abs(report.value_effect)
            else "average order value"
        )
        findings.append(
            f"Delivered orders went {orders_before:,} -> {orders_now:,} "
            f"({_money(report.volume_effect)} effect) and average order value "
            f"{_money(report.baseline_kpis['aov'])} -> "
            f"{_money(report.current_kpis['aov'])} "
            f"({_money(report.value_effect)} effect); {dominant} explains most "
            f"of the change."
        )

    for table, noun in ((report.categories, "category"), (report.states, "state")):
        findings.extend(_segment_sentence(table, noun))

    slow_states = report.state_delivery[
        (report.state_delivery["change_days"] >= 2.0)
        & (
            report.state_delivery[["orders_current", "orders_baseline"]].min(axis=1)
            >= MIN_ORDERS_FOR_STATE_CLAIMS
        )
    ].head(3)

    for row in slow_states.itertuples():
        findings.append(
            f"Delivery slowed in {row.state}: "
            f"{row.avg_delivery_days_baseline:.1f} -> "
            f"{row.avg_delivery_days_current:.1f} days "
            f"({row.change_days:+.1f})."
        )

    ops = report.operations.set_index("key")["change"]

    if ops.get("cancel_rate") is not None and abs(ops["cancel_rate"]) >= 0.01:
        findings.append(
            f"Cancel rate moved {ops['cancel_rate'] * 100:+.1f} percentage points."
        )

    if ops.get("avg_review_score") is not None and abs(ops["avg_review_score"]) >= 0.1:
        findings.append(
            f"Average review score moved {ops['avg_review_score']:+.2f}."
        )

    findings.append(
        "These are associations in the data, not proof of cause; confirm with "
        "the business before acting."
    )

    return findings


def largest_monthly_changes(
    trend: pd.DataFrame,
    top: int = 5,
    min_revenue_share: float = 0.25,
) -> pd.DataFrame:
    """
    Month-over-month revenue changes, biggest drops first.

    Months whose revenue is below `min_revenue_share` of the median month are
    treated as partial data (for example the sparse first and last months of
    a dataset) and are not suggested, so a half-empty month is not reported
    as a collapse. Any month can still be analysed by choosing it manually.
    """

    frame = trend.sort_values("month").copy()
    floor = frame["revenue"].median() * min_revenue_share

    frame["previous_revenue"] = frame["revenue"].shift(1)
    frame["change_pct"] = (
        frame["revenue"] - frame["previous_revenue"]
    ) / frame["previous_revenue"]

    usable = frame[(frame["revenue"] >= floor) & (frame["previous_revenue"] >= floor)]

    return (
        usable.dropna(subset=["change_pct"])
        .sort_values("change_pct")
        .head(top)
        .reset_index(drop=True)
    )
