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
