"""The benchmark itself must be trustworthy: valid, runnable, well-formed."""

from collections import Counter
from decimal import Decimal

import pandas as pd
import pytest

from evaluation.benchmark import QUESTIONS
from evaluation.compare import results_match
from evaluation.run_eval import evaluate_one, markdown_report, summarise


def test_there_are_50_unique_questions_across_seven_categories():
    assert len(QUESTIONS) == 50
    assert len({q.id for q in QUESTIONS}) == 50
    assert len({q.question for q in QUESTIONS}) == 50

    counts = Counter(q.category for q in QUESTIONS)

    assert set(counts) == {
        "aggregation", "filtering", "join", "time", "ranking", "ratio", "multi_step"
    }
    assert min(counts.values()) >= 6


@pytest.mark.db
@pytest.mark.parametrize("item", QUESTIONS, ids=[q.id for q in QUESTIONS])
def test_reference_sql_passes_guardrails_and_returns_rows(seeded_db, item):
    from app.db.runner import run_query
    from app.db.schema_context import get_allowed_tables
    from app.sql.validator import validate_sql

    valid, message = validate_sql(item.sql, allowed_tables=get_allowed_tables())
    assert valid, message

    frame = run_query(item.sql)
    assert len(frame) >= 1


@pytest.mark.db
def test_reference_sql_is_deterministic(seeded_db):
    from app.db.runner import run_query

    for item in QUESTIONS:
        first, second = run_query(item.sql), run_query(item.sql)

        assert results_match(first, second, item.ordered), item.id


# ---- result comparison ---------------------------------------------------

def test_scalar_match_ignores_column_names_and_float_noise():
    expected = pd.DataFrame({"total": [Decimal("1233131.72")]})
    actual = pd.DataFrame({"total_sales": [1233131.7200000001]})

    assert results_match(expected, actual, ordered=False)


def test_different_values_do_not_match():
    expected = pd.DataFrame({"total": [100.0]})
    actual = pd.DataFrame({"total": [101.0]})

    assert not results_match(expected, actual, ordered=False)


def test_extra_helper_columns_are_allowed():
    expected = pd.DataFrame({"state": ["SP", "RJ"], "revenue": [10.0, 5.0]})
    actual = pd.DataFrame(
        {"state": ["SP", "RJ"], "orders": [3, 2], "revenue": [10.0, 5.0]}
    )

    assert results_match(expected, actual, ordered=True)


def test_row_order_matters_only_when_reference_is_ordered():
    expected = pd.DataFrame({"state": ["SP", "RJ"], "revenue": [10.0, 5.0]})
    shuffled = pd.DataFrame({"state": ["RJ", "SP"], "revenue": [5.0, 10.0]})

    assert results_match(expected, shuffled, ordered=False)
    assert not results_match(expected, shuffled, ordered=True)


def test_columns_must_stay_paired_row_by_row():
    expected = pd.DataFrame({"state": ["SP", "RJ"], "revenue": [10.0, 5.0]})
    mispaired = pd.DataFrame({"state": ["SP", "RJ"], "revenue": [5.0, 10.0]})

    assert not results_match(expected, mispaired, ordered=False)


def test_row_count_must_match():
    expected = pd.DataFrame({"n": [1, 2, 3]})

    assert not results_match(expected, pd.DataFrame({"n": [1, 2]}), ordered=False)


def test_dates_match_regardless_of_timestamp_type():
    expected = pd.DataFrame({"month": [pd.Timestamp("2018-03-01")], "n": [5]})
    actual = pd.DataFrame(
        {"m": [pd.Timestamp("2018-03-01", tz="UTC")], "count": [5]}
    )

    assert results_match(expected, actual, ordered=True)


def test_nulls_match_nulls_only():
    expected = pd.DataFrame({"x": [1.0, None]})

    assert results_match(expected, pd.DataFrame({"y": [None, 1.0]}), ordered=False)
    assert not results_match(expected, pd.DataFrame({"y": [0.0, 1.0]}), ordered=False)


def test_ordered_flag_comes_from_the_reference_sql():
    by_id = {q.id: q for q in QUESTIONS}

    assert by_id["Q01"].ordered is False
    assert by_id["Q17"].ordered is True


# ---- runner bookkeeping --------------------------------------------------

class FakeResult:
    def __init__(self, frame, attempts=1):
        self.dataframe = frame
        self.attempts = attempts
        self.latency_ms = 1200
        self.sql = "SELECT 1"


def _patch_reference(monkeypatch, frame):
    from evaluation import run_eval

    monkeypatch.setattr(run_eval, "run_reference", lambda sql: frame)


def test_evaluate_one_scores_correct_wrong_and_failed(monkeypatch):
    item = QUESTIONS[0]
    _patch_reference(monkeypatch, pd.DataFrame({"n": [2760]}))

    right = evaluate_one(item, lambda q: FakeResult(pd.DataFrame({"x": [2760]})))
    wrong = evaluate_one(item, lambda q: FakeResult(pd.DataFrame({"x": [1]})))

    def boom(question):
        raise ValueError("SQL rejected: nope")

    failed = evaluate_one(item, boom)

    assert (right["executed"], right["correct"]) == (True, True)
    assert (wrong["executed"], wrong["correct"]) == (True, False)
    assert (failed["executed"], failed["correct"]) == (False, False)
    assert "SQL rejected" in failed["error"]


def test_summary_separates_first_try_from_repaired():
    records = [
        {"category": "join", "executed": True, "correct": True, "attempts": 1, "latency_ms": 1000},
        {"category": "join", "executed": True, "correct": True, "attempts": 2, "latency_ms": 3000},
        {"category": "time", "executed": True, "correct": False, "attempts": 1, "latency_ms": 2000},
        {"category": "time", "executed": False, "correct": False, "attempts": 0, "latency_ms": 500},
    ]

    summary = summarise(records)

    assert summary["questions"] == 4
    assert summary["executed"] == 0.75
    assert summary["correct"] == 0.5
    assert summary["first_try"] == 0.25
    assert summary["repaired"] == 0.25
    assert summary["by_category"]["join"]["rate"] == 1.0
    assert summary["by_category"]["time"]["rate"] == 0.0


def test_markdown_report_lists_failures_and_admits_missing_cost():
    records = [
        {"id": "Q01", "category": "join", "question": "How many?", "executed": True,
         "correct": False, "attempts": 1, "latency_ms": 1000, "error": None, "sql": "x"},
    ]
    meta = {"run_at": "now", "model": "m", "fallback_model": "f"}

    report = markdown_report(summarise(records), records, meta)

    assert "## Failures (1)" in report
    assert "Q01" in report
    assert "Cost per query is not measured" in report


# ---- API trouble must not be scored as wrong SQL --------------------------

from evaluation import run_eval  # noqa: E402


def test_infrastructure_errors_are_classified():
    quota = "gemini-3.6-flash: 429 RESOURCE_EXHAUSTED. You exceeded your current quota"
    busy = "gemini-3.6-flash: 503 UNAVAILABLE. high demand"

    assert run_eval.is_infrastructure_error(quota) and run_eval.is_quota_error(quota)
    assert run_eval.is_infrastructure_error(busy) and not run_eval.is_quota_error(busy)
    assert run_eval.is_infrastructure_error("[Errno 11001] getaddrinfo failed")
    assert not run_eval.is_infrastructure_error("SQL rejected: Table 'x' is not available")
    assert not run_eval.is_infrastructure_error(None)


def test_evaluate_one_marks_api_errors_not_evaluated():
    def boom(question):
        raise RuntimeError("Gemini models are currently unavailable. 429 RESOURCE_EXHAUSTED")

    def rejected(question):
        raise ValueError("SQL rejected: nope")

    assert evaluate_one(QUESTIONS[0], boom)["status"] == "not_evaluated"
    assert evaluate_one(QUESTIONS[0], rejected)["status"] == "failed"


def test_summary_excludes_not_evaluated_from_rates():
    ok = {"category": "join", "executed": True, "correct": True, "attempts": 1,
          "latency_ms": 1000, "status": "correct"}
    skipped = {"category": "join", "executed": False, "correct": False, "attempts": 0,
               "latency_ms": 500, "status": "not_evaluated", "error": "429"}

    summary = summarise([ok] * 10 + [skipped] * 40)

    assert summary["questions"] == 50
    assert summary["evaluated"] == 10
    assert summary["not_evaluated"] == 40
    assert summary["correct"] == 1.0  # of the 10 evaluated, not 20% of 50
    assert summary["by_category"]["join"]["questions"] == 10


def test_report_flags_partial_results():
    records = [
        {"id": "Q01", "category": "join", "question": "a", "executed": True, "correct": True,
         "attempts": 1, "latency_ms": 1, "status": "correct", "error": None, "sql": "x"},
        {"id": "Q02", "category": "join", "question": "b", "executed": False, "correct": False,
         "attempts": 0, "latency_ms": 1, "status": "not_evaluated", "error": "429", "sql": None},
    ]
    meta = {"run_at": "now", "model": "m", "fallback_model": "f"}

    report = markdown_report(summarise(records), records, meta)

    assert "Partial result" in report
    assert "Not evaluated (1)" in report
    assert "Failures (0)" in report


def test_retry_only_for_transient_errors():
    calls = {"n": 0}

    def busy_then_ok(question):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 UNAVAILABLE high demand")
        return FakeResult(pd.DataFrame({"x": [1]}))

    def quota(question):
        calls["n"] += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    import pandas as _pd  # noqa: F401

    from evaluation.run_eval import evaluate_with_retry

    calls["n"] = 0
    record = evaluate_with_retry(QUESTIONS[0], busy_then_ok, sleep=lambda s: None)
    assert calls["n"] == 2 and record["executed"]

    calls["n"] = 0
    record = evaluate_with_retry(QUESTIONS[0], quota, sleep=lambda s: None)
    assert calls["n"] == 1 and record["status"] == "not_evaluated"


def test_main_stops_on_quota_keeps_evaluated_and_resumes(monkeypatch, tmp_path):
    import json
    import sys

    import app.pipeline as pipeline

    ids = [q.id for q in QUESTIONS[:6]]
    state = {"n": 0, "quota": True}

    def fake_run(question, audit=True):
        state["n"] += 1
        if state["quota"] and state["n"] > 2:
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
        return FakeResult(pd.DataFrame({"x": [1]}))

    monkeypatch.setattr(pipeline, "run_pipeline_detailed", fake_run)
    monkeypatch.setattr(run_eval, "run_reference", lambda sql: pd.DataFrame({"n": [1]}))
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(run_eval.time, "sleep", lambda s: None)

    monkeypatch.setattr(sys, "argv", ["run_eval", "--ids", *ids, "--delay", "0"])
    run_eval.main()

    saved = json.loads((tmp_path / "state.json").read_text())
    assert set(saved) == set(ids[:2])                       # only evaluated ones kept
    assert state["n"] == 2 + run_eval.STOP_AFTER_QUOTA_ERRORS  # stopped early

    state.update(n=0, quota=False)
    monkeypatch.setattr(sys, "argv", ["run_eval", "--ids", *ids, "--delay", "0", "--resume"])
    run_eval.main()

    saved = json.loads((tmp_path / "state.json").read_text())
    assert set(saved) == set(ids)
    assert state["n"] == 4                                  # only the 4 missing re-run
    assert "Partial result" not in (tmp_path / "latest.md").read_text()
