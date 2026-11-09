"""
Automatic dashboard and plain-English findings from a cleaned DataFrame.

Everything here is computed with pandas from the data itself (no LLM, no SQL),
so the numbers are exact and the same function feeds the on-screen dashboard
and the downloadable report.
"""

from dataclasses import dataclass, field

import pandas as pd
import plotly.express as px

from app.workspace.profile import by_role

MEASURE_HINTS = (
    "revenue", "sales", "amount", "total", "price", "cost", "profit", "income",
    "spend", "value", "quantity", "qty", "units", "salary", "score",
)
SUM_HINTS = ("revenue", "sales", "amount", "total", "cost", "profit", "income",
             "spend", "quantity", "qty", "units")


@dataclass
class Dashboard:
    kpis: list = field(default_factory=list)  # (label, value text)
    charts: list = field(default_factory=list)  # (title, plotly figure)
    findings: list = field(default_factory=list)  # plain-English lines
    measure: str | None = None
    date_column: str | None = None


def _fmt(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    if abs(value) >= 10_000:
        return f"{value:,.0f}"

    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _pick_measure(frame, numeric: list):
    if not numeric:
        return None

    for hint in MEASURE_HINTS:
        for name in numeric:
            if hint in name.split("_"):
                return name

    return max(numeric, key=lambda n: frame[n].notna().sum())


def _aggregation(measure: str) -> str:
    return "sum" if any(h in measure.split("_") for h in SUM_HINTS) else "mean"


def build_dashboard(frame: pd.DataFrame, profiles: list) -> Dashboard:
    board = Dashboard()
    numeric = by_role(profiles, "numeric")
    dates = by_role(profiles, "datetime")
    categories = [c for c in by_role(profiles, "category") if frame[c].nunique() >= 2]

    board.kpis.append(("Rows", f"{len(frame):,}"))
    board.kpis.append(("Columns", f"{frame.shape[1]}"))

    measure = _pick_measure(frame, numeric)
    board.measure = measure

    if measure:
        series = frame[measure].dropna()
        how = _aggregation(measure)
        label = measure.replace("_", " ")

        if how == "sum":
            board.kpis.append((f"Total {label}", _fmt(series.sum())))

        board.kpis.append((f"Average {label}", _fmt(series.mean())))
        board.kpis.append((f"Median {label}", _fmt(series.median())))

    for name in numeric[:6]:
        if name != measure and len(board.kpis) < 6:
            board.kpis.append((f"Average {name.replace('_', ' ')}", _fmt(frame[name].mean())))

    # --- trend over time ----------------------------------------------------
    if dates:
        date_col = dates[0]
        board.date_column = date_col
        valid = frame.dropna(subset=[date_col])
        span_days = (valid[date_col].max() - valid[date_col].min()).days if len(valid) else 0

        if span_days >= 1:
            freq = "D" if span_days <= 90 else ("W" if span_days <= 400 else "MS")
            period_name = {"D": "day", "W": "week", "MS": "month"}[freq]
            grouped = valid.set_index(date_col)

            if measure:
                how = _aggregation(measure)
                trend = grouped[measure].resample(freq).agg(how).reset_index()
                title = f"{how.title() if how == 'mean' else 'Total'} {measure.replace('_', ' ')} by {period_name}"
                y = measure
            else:
                trend = grouped.iloc[:, 0].resample(freq).size().reset_index()
                trend.columns = [date_col, "rows"]
                title, y = f"Rows by {period_name}", "rows"

            trend.columns = [date_col, y]

            if len(trend) >= 3:
                board.charts.append((title, px.line(trend, x=date_col, y=y, markers=True, title=title)))

                best = trend.loc[trend[y].idxmax()]
                worst = trend.loc[trend[y].idxmin()]
                board.findings.append(
                    f"Peak {period_name}: {best[date_col]:%Y-%m-%d} ({_fmt(best[y])}); "
                    f"lowest: {worst[date_col]:%Y-%m-%d} ({_fmt(worst[y])})."
                )

                if len(trend) >= 4 and trend[y].iloc[-2] not in (0, None):
                    last, prev = trend[y].iloc[-1], trend[y].iloc[-2]
                    board.findings.append(
                        f"Latest {period_name} ({trend[date_col].iloc[-1]:%Y-%m-%d}) is "
                        f"{(last - prev) / abs(prev):+.1%} vs the {period_name} before "
                        "(the latest period may be incomplete)."
                    )

    # --- top categories -----------------------------------------------------
    for category in categories[:3]:
        if measure:
            how = _aggregation(measure)
            top = (frame.groupby(category)[measure].agg(how)
                   .sort_values(ascending=False).head(10).reset_index())
            value = measure
            title = f"{'Total' if how == 'sum' else 'Average'} {measure.replace('_', ' ')} by {category}"
        else:
            top = frame[category].value_counts().head(10).reset_index()
            top.columns = [category, "rows"]
            value, title = "rows", f"Rows by {category}"

        board.charts.append(
            (title, px.bar(top.sort_values(value), x=value, y=category,
                           orientation="h", title=title))
        )

        if measure and _aggregation(measure) == "sum" and top[value].sum() > 0:
            share = top[value].iloc[0] / frame[measure].sum()
            board.findings.append(
                f"Top {category}: '{top[category].iloc[0]}' contributes "
                f"{share:.1%} of total {measure.replace('_', ' ')}."
            )
        elif len(top):
            board.findings.append(f"Highest {value.replace('_', ' ')} by {category}: "
                                  f"'{top[category].iloc[0]}' ({_fmt(top[value].iloc[0])}).")

    # --- distribution and correlation ---------------------------------------
    if measure and frame[measure].nunique() > 5:
        board.charts.append((
            f"Distribution of {measure}",
            px.histogram(frame, x=measure, nbins=30, title=f"Distribution of {measure.replace('_', ' ')}"),
        ))

    if len(numeric) >= 2:
        corr = frame[numeric].corr(numeric_only=True)
        pairs = []

        for i, a in enumerate(numeric):
            for b in numeric[i + 1:]:
                value = corr.loc[a, b]
                if pd.notna(value):
                    pairs.append((abs(value), value, a, b))

        pairs.sort(reverse=True)

        if pairs and pairs[0][0] >= 0.5:
            _, value, a, b = pairs[0]
            direction = "rise together" if value > 0 else "move in opposite directions"
            board.findings.append(
                f"{a.replace('_', ' ').title()} and {b.replace('_', ' ')} {direction} "
                f"(correlation {value:+.2f}). Correlation does not prove cause."
            )

    # --- data quality -------------------------------------------------------
    gaps = [(p.name, p.missing_share) for p in profiles if p.missing_share >= 0.2]

    if gaps:
        board.findings.append(
            "Data gaps: " + ", ".join(f"{n} ({s:.0%} missing)" for n, s in gaps) + "."
        )

    return board
