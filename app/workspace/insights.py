"""Automatic findings and statistical tests for an uploaded dataset.

Everything here is computed with pandas/scipy, so every sentence can be checked
against the data. No language model is involved: it cannot invent a number.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from app.workspace.dashboard import MEASURE_HINTS, _fmt, _pick_measure
from app.workspace.profile import by_role

MIN_GROUP_ROWS = 30
MAX_SEGMENT_COLUMNS = 4
EFFECT_SIZE_MIN = 0.02  # eta squared; below this a "significant" gap is trivial
CORRELATION_MIN = 0.5
ALPHA = 0.01


@dataclass
class Insight:
    kind: str  # concentration | difference | correlation | trend | quality
    title: str
    detail: str
    score: float  # used to rank, higher is more interesting


@dataclass
class TestResult:
    name: str
    p_value: float
    effect: float | None
    effect_label: str
    verdict: str
    notes: list = field(default_factory=list)

    @property
    def significant(self) -> bool:
        return self.p_value < ALPHA


def _p_text(p_value: float) -> str:
    return "p < 0.001" if p_value < 0.001 else f"p = {p_value:.3f}"


def _readable(name: str) -> str:
    return name.replace("_", " ")


def _eta_squared(groups: list) -> float:
    values = np.concatenate(groups)
    grand = values.mean()
    total = ((values - grand) ** 2).sum()

    if total == 0:
        return 0.0

    between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)

    return float(between / total)


def _groups(frame, measure, category):
    data = frame[[category, measure]].dropna()
    grouped = {
        key: group[measure].to_numpy(dtype=float)
        for key, group in data.groupby(category, observed=True)
        if len(group) >= MIN_GROUP_ROWS
    }

    return grouped


def compare_groups(frame: pd.DataFrame, measure: str, category: str) -> TestResult | None:
    """Does the average of ``measure`` differ between the groups of ``category``?"""

    groups = _groups(frame, measure, category)

    if len(groups) < 2:
        return None

    arrays = list(groups.values())
    effect = _eta_squared(arrays)
    label = f"eta squared = {effect:.3f}"

    if len(arrays) == 2:
        statistic = stats.ttest_ind(arrays[0], arrays[1], equal_var=False)
        test = "Welch t-test"
    else:
        statistic = stats.f_oneway(*arrays)
        test = "One-way ANOVA"

    p_value = float(statistic.pvalue)
    means = {str(key): float(values.mean()) for key, values in groups.items()}
    high = max(means, key=means.get)
    low = min(means, key=means.get)

    if p_value >= ALPHA:
        verdict = (
            f"No reliable difference in {_readable(measure)} between "
            f"{_readable(category)} groups ({_p_text(p_value)})."
        )
    elif effect < EFFECT_SIZE_MIN:
        verdict = (
            f"The difference is statistically detectable ({_p_text(p_value)}) but "
            f"tiny ({label}), so it is unlikely to matter in practice."
        )
    else:
        verdict = (
            f"{_readable(measure).capitalize()} differs by {_readable(category)} "
            f"({_p_text(p_value)}, {label}). Highest: {high} ({_fmt(means[high])}), "
            f"lowest: {low} ({_fmt(means[low])})."
        )

    notes = [f"{test} on {len(arrays)} groups with at least {MIN_GROUP_ROWS} rows each."]
    skipped = frame[category].nunique() - len(groups)

    if skipped > 0:
        notes.append(f"{skipped} very small group(s) were left out.")

    return TestResult(test, p_value, effect, label, verdict, notes)


def correlate(frame: pd.DataFrame, first: str, second: str) -> TestResult | None:
    """Spearman rank correlation, which does not assume a straight line."""

    data = frame[[first, second]].dropna()

    if len(data) < MIN_GROUP_ROWS or data[first].nunique() < 3 or data[second].nunique() < 3:
        return None

    rho, p_value = stats.spearmanr(data[first], data[second])
    strength = abs(rho)
    word = (
        "strong" if strength >= 0.7 else "moderate" if strength >= 0.4
        else "weak" if strength >= 0.2 else "almost no"
    )
    direction = "positive" if rho > 0 else "negative"

    if strength < 0.2:
        verdict = f"There is almost no relationship between {_readable(first)} and {_readable(second)} (rho = {rho:.2f})."
    else:
        verdict = (
            f"{_readable(first).capitalize()} and {_readable(second)} have a {word} "
            f"{direction} relationship (rho = {rho:.2f}, {_p_text(float(p_value))}). "
            "Correlation does not prove one causes the other."
        )

    return TestResult(
        "Spearman correlation", float(p_value), float(rho), f"rho = {rho:.2f}", verdict,
        [f"Based on {len(data):,} rows with both values."],
    )


def association(frame: pd.DataFrame, first: str, second: str) -> TestResult | None:
    """Chi-square test of independence between two categorical columns."""

    table = pd.crosstab(frame[first], frame[second])
    table = table.loc[table.sum(axis=1) >= MIN_GROUP_ROWS, table.sum(axis=0) >= MIN_GROUP_ROWS]

    if table.shape[0] < 2 or table.shape[1] < 2:
        return None

    chi2, p_value, _, _ = stats.chi2_contingency(table)
    n = table.to_numpy().sum()
    cramers_v = float(np.sqrt(chi2 / (n * (min(table.shape) - 1))))
    label = f"Cramer's V = {cramers_v:.2f}"

    if p_value >= ALPHA:
        verdict = f"No reliable link between {_readable(first)} and {_readable(second)} ({_p_text(float(p_value))})."
    elif cramers_v < 0.1:
        verdict = f"A link exists ({_p_text(float(p_value))}) but it is very weak ({label})."
    else:
        verdict = f"{_readable(first).capitalize()} and {_readable(second)} are linked ({_p_text(float(p_value))}, {label})."

    return TestResult("Chi-square test", float(p_value), cramers_v, label, verdict,
                      [f"Based on {int(n):,} rows."])


def ab_test(frame: pd.DataFrame, group_column: str, metric: str, group_a, group_b) -> TestResult | None:
    """Compare two named groups on a numeric metric, with a confidence interval."""

    a = frame.loc[frame[group_column] == group_a, metric].dropna().to_numpy(dtype=float)
    b = frame.loc[frame[group_column] == group_b, metric].dropna().to_numpy(dtype=float)

    if len(a) < MIN_GROUP_ROWS or len(b) < MIN_GROUP_ROWS:
        return None

    result = stats.ttest_ind(b, a, equal_var=False)
    difference = float(b.mean() - a.mean())
    interval = result.confidence_interval(0.95)
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    cohens_d = difference / pooled if pooled else 0.0
    lift = difference / a.mean() if a.mean() else float("nan")
    p_value = float(result.pvalue)

    verdict = (
        f"{group_b} averages {_fmt(float(b.mean()))} vs {_fmt(float(a.mean()))} for {group_a} "
        f"({difference:+,.2f}, {lift:+.1%}). 95% confidence interval for the difference: "
        f"{_fmt(float(interval.low))} to {_fmt(float(interval.high))}. "
    )
    verdict += (
        f"This is statistically significant ({_p_text(p_value)})."
        if p_value < ALPHA
        else f"This is not statistically significant ({_p_text(p_value)}), so it could be chance."
    )

    return TestResult(
        "Welch t-test", p_value, float(cohens_d), f"Cohen's d = {cohens_d:.2f}", verdict,
        [f"{group_a}: {len(a):,} rows. {group_b}: {len(b):,} rows."],
    )


def _segment_columns(profiles) -> list:
    by_name = {p.name: p for p in profiles}
    columns = [n for n in by_role(profiles, "category") if 2 <= by_name[n].nunique <= 20]

    return sorted(columns, key=lambda n: by_name[n].missing_share)[:MAX_SEGMENT_COLUMNS]


def _numeric_columns(profiles, frame) -> list:
    return [n for n in by_role(profiles, "numeric") if frame[n].nunique() > 2]


def _concentration(frame, measure, category, aggregate):
    totals = frame.groupby(category, observed=True)[measure].agg(aggregate).dropna()

    if aggregate != "sum" or len(totals) < 3 or totals.sum() <= 0:
        return None

    ranked = totals.sort_values(ascending=False)
    top_n = 3 if len(ranked) > 5 else 1
    share = float(ranked.head(top_n).sum() / ranked.sum())
    names = ", ".join(str(n) for n in ranked.head(top_n).index)
    expected = top_n / len(ranked)

    if share < expected * 2:
        return None

    subject = f"The top {top_n} {_readable(category)} values" if top_n > 1 else f"The top {_readable(category)}"
    verb = "account" if top_n > 1 else "accounts"

    return Insight(
        "concentration",
        f"{share:.0%} of {_readable(measure)} comes from {names}",
        f"{subject} ({names}) {verb} for {share:.0%} of total {_readable(measure)}, "
        f"out of {len(ranked)} {_readable(category)} values.",
        share / expected,
    )


def _trend(frame, measure, date_column, aggregate):
    data = frame[[date_column, measure]].dropna()

    if len(data) < 60:
        return None

    monthly = data.set_index(date_column)[measure].resample("MS").agg(aggregate)
    monthly = monthly.iloc[1:-1] if len(monthly) > 4 else monthly

    if len(monthly) < 4 or monthly.mean() == 0:
        return None

    x = np.arange(len(monthly))
    fit = stats.linregress(x, monthly.to_numpy(dtype=float))
    change = float(fit.slope * (len(monthly) - 1) / abs(monthly.iloc[0])) if monthly.iloc[0] else 0.0

    if fit.pvalue >= ALPHA or abs(change) < 0.1:
        return None

    direction = "rising" if fit.slope > 0 else "falling"

    return Insight(
        "trend",
        f"Monthly {_readable(measure)} is steadily {direction}",
        f"Across {len(monthly)} full months, monthly {_readable(measure)} is {direction} "
        f"(about {change:+.0%} from first to last month, {_p_text(float(fit.pvalue))}).",
        abs(change) * 5,
    )


def find_insights(frame: pd.DataFrame, profiles: list, limit: int = 8) -> list:
    """Return the most interesting, statistically supported findings, best first."""

    insights = []
    numeric = _numeric_columns(profiles, frame)
    measure = _pick_measure(frame, numeric)
    segments = _segment_columns(profiles)
    dates = by_role(profiles, "datetime")
    aggregate = "sum" if measure and any(h in measure.split("_") for h in MEASURE_HINTS) else "mean"

    if measure:
        for category in segments:
            found = _concentration(frame, measure, category, "sum" if aggregate == "sum" else "mean")

            if found:
                insights.append(found)

            test = compare_groups(frame, measure, category)

            if test and test.significant and (test.effect or 0) >= EFFECT_SIZE_MIN:
                insights.append(Insight("difference", f"{_readable(measure).capitalize()} differs by {_readable(category)}",
                                        test.verdict, 1 + (test.effect or 0) * 20))

        if dates:
            found = _trend(frame, measure, dates[0], "sum" if aggregate == "sum" else "mean")

            if found:
                insights.append(found)

    others = [n for n in numeric]

    for index, first in enumerate(others):
        for second in others[index + 1:]:
            test = correlate(frame, first, second)

            if test and abs(test.effect or 0) >= CORRELATION_MIN and test.significant:
                insights.append(Insight(
                    "correlation",
                    f"{_readable(first).capitalize()} and {_readable(second)} move together",
                    test.verdict, abs(test.effect) * 3,
                ))

    for profile in profiles:
        if profile.missing_share >= 0.05:
            insights.append(Insight(
                "quality",
                f"{_readable(profile.name).capitalize()} is {profile.missing_share:.0%} empty",
                f"{profile.missing_share:.0%} of {_readable(profile.name)} values are missing. "
                "Results that use this column cover fewer rows than the full file.",
                0.5 + profile.missing_share,
            ))

    insights.sort(key=lambda item: item.score, reverse=True)

    return insights[:limit]
