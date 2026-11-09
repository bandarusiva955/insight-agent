import numpy as np
import pandas as pd

from app.workspace import insights
from app.workspace.profile import profile_frame


def _frame(seed=0, n=3000):
    rng = np.random.default_rng(seed)
    group = rng.choice(["a", "b", "c"], n)
    base = pd.Series(group).map({"a": 100.0, "b": 100.0, "c": 300.0}).to_numpy()
    units = rng.integers(1, 10, n)

    return pd.DataFrame(
        {
            "region": rng.choice(["north", "south", "east", "west"], n),
            "tier": group,
            "units": units,
            "revenue": base + rng.normal(0, 20, n) + units * 10,
            "noise": rng.normal(0, 1, n),
            "order_date": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
        }
    )


def test_compare_groups_detects_real_difference():
    result = insights.compare_groups(_frame(), "revenue", "tier")

    assert result.significant and result.effect > 0.5
    assert "c" in result.verdict


def test_compare_groups_no_difference_for_noise():
    result = insights.compare_groups(_frame(), "noise", "region")

    assert not result.significant
    assert "No reliable difference" in result.verdict


def test_correlation_strong_and_absent():
    frame = _frame()

    assert insights.correlate(frame, "units", "revenue").effect > 0.1
    assert abs(insights.correlate(frame, "units", "noise").effect) < 0.1


def test_association_independent_columns():
    result = insights.association(_frame(), "region", "tier")

    assert not result.significant


def test_ab_test_reports_interval_and_significance():
    frame = _frame()
    result = insights.ab_test(frame, "tier", "revenue", "a", "c")

    assert result.significant and "95% confidence interval" in result.verdict
    assert not insights.ab_test(frame, "tier", "revenue", "a", "b").significant


def test_ab_test_small_group_returns_none():
    frame = _frame()
    frame.loc[frame.index[:5], "tier"] = "tiny"

    assert insights.ab_test(frame, "tier", "revenue", "a", "tiny") is None


def test_find_insights_ranks_real_effects_and_skips_noise():
    frame = _frame()
    found = insights.find_insights(frame, profile_frame(frame))
    text = " ".join(item.title + item.detail for item in found).lower()

    assert any(item.kind == "difference" and "tier" in item.title.lower() for item in found)
    assert "noise" not in text
    assert "region" not in " ".join(i.title.lower() for i in found if i.kind == "difference")


def test_find_insights_handles_tiny_or_empty_data():
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    assert insights.find_insights(frame, profile_frame(frame)) == []


def test_insights_panel_renders_and_runs_a_test():
    from streamlit.testing.v1 import AppTest

    def app():
        import numpy as np
        import pandas as pd
        from types import SimpleNamespace

        from app.ui import insights_panel
        from app.workspace.profile import profile_frame

        rng = np.random.default_rng(1)
        n = 2000
        tier = rng.choice(["a", "b", "c"], n)
        frame = pd.DataFrame({
            "tier": tier,
            "units": rng.integers(1, 9, n),
            "revenue": pd.Series(tier).map({"a": 100.0, "b": 100.0, "c": 300.0}).to_numpy()
            + rng.normal(0, 20, n),
        })
        insights_panel.render("sales", "f.csv", SimpleNamespace(frame=frame), profile_frame(frame))

    at = AppTest.from_function(app).run(timeout=60)

    assert not at.exception
    assert any("Revenue differs by tier" in m.value for m in at.markdown)

    at.button[0].click().run(timeout=60)

    assert not at.exception
    assert len(at.success) + len(at.info) >= 1
