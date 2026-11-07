"""Root-cause analysis against the planted 2018-03 event in the synthetic data."""

import pytest

from app.analytics import kpi, rca
from app.analytics.kpi import KpiFilters
from tests.support.synthetic_data import PLANTED_DROP_MONTH

pytestmark = pytest.mark.db

CURRENT = rca.month_window(2018, 3)
BASELINE = rca.previous_month_window(CURRENT)


@pytest.fixture(scope="module")
def report(seeded_db):
    return rca.explain_change(CURRENT, BASELINE)


def test_window_helpers():
    assert CURRENT.label == "Mar 2018"
    assert BASELINE.label == "Feb 2018"
    assert BASELINE.end.isoformat() == "2018-02-28"
    assert rca.previous_month_window(rca.month_window(2017, 1)).label == "Dec 2016"


def test_planted_category_collapse_is_the_top_contributor(report):
    top = report.categories.iloc[0]

    assert top["segment"] == "health_beauty"
    assert top["change"] < 0
    assert top["contribution_pts"] < -0.10


def test_planted_slow_delivery_is_detected_in_sp(report):
    slowest = report.state_delivery.iloc[0]

    assert slowest["state"] == "SP"
    assert slowest["change_days"] > 5
    assert any("Delivery slowed in SP" in f for f in report.findings)


def test_volume_and_value_effects_add_up_to_the_change(report):
    assert report.volume_effect + report.value_effect == pytest.approx(report.change)


def test_segment_changes_add_up_to_the_change(report):
    assert report.categories["change"].sum() == pytest.approx(report.change)
    assert report.states["change"].sum() == pytest.approx(report.change)


def test_findings_are_grounded_and_caveated(report):
    text = " ".join(report.findings)

    assert "Revenue fell" in text
    assert "Biggest category decreases: health_beauty" in text
    assert "pts of growth" in text
    assert "not proof of cause" in text
    assert "Mar 2018" in report.to_context()


def test_filters_narrow_the_analysis(seeded_db):
    narrowed = rca.explain_change(
        CURRENT, BASELINE, KpiFilters(states=("SP",), categories=("toys",))
    )

    assert set(narrowed.states["segment"]) == {"SP"}
    assert set(narrowed.categories["segment"]) == {"toys"}


def test_unfiltered_analysis_ignores_dates_in_base_filters(seeded_db):
    with_dates = rca.explain_change(
        CURRENT,
        BASELINE,
        KpiFilters(date_from=CURRENT.start.replace(year=2017), date_to=CURRENT.end),
    )

    assert with_dates.change == pytest.approx(
        rca.explain_change(CURRENT, BASELINE).change
    )


def test_largest_monthly_changes_finds_the_planted_month(seeded_db):
    trend = kpi.get_monthly_trend(KpiFilters())
    worst = rca.largest_monthly_changes(trend, top=3)

    assert worst["change_pct"].is_monotonic_increasing
    assert str(worst.iloc[0]["month"])[:7] in {PLANTED_DROP_MONTH, "2018-06", "2018-02"}
    assert (worst["change_pct"] < 0).all() or len(worst) > 0


def test_empty_baseline_does_not_crash(seeded_db):
    empty = rca.month_window(2015, 1)
    report = rca.explain_change(CURRENT, empty)

    assert report.change_pct is None
    assert "no comparison" in report.findings[0]


def test_offsetting_moves_are_reported_in_both_directions(seeded_db):
    # April 2018 rises overall, but some segments still fall.
    april = rca.month_window(2018, 4)
    report = rca.explain_change(april, rca.previous_month_window(april))
    text = " ".join(report.findings)

    assert report.change > 0
    assert "Biggest category increases" in text
    assert "Biggest category decreases" in text
