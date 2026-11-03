"""
Unit tests for the self-correction loop and display helpers.

The LLM, the database and the audit log are replaced with fakes, so these
tests run without Postgres or a Gemini key.
"""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import pandas as pd
import pytest
from sqlalchemy.exc import ProgrammingError

from app import pipeline
from app.llm.sql_generator import clean_sql
from app.ui.formatting import is_money_column, style_results


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "log_query", lambda **kwargs: calls.append(kwargs)
    )
    return calls


def _frame():
    return pd.DataFrame({"category_name": ["a"], "total_sales": [10.0]})


def test_success_on_first_attempt(monkeypatch, audit_calls):
    monkeypatch.setattr(pipeline, "generate_sql", lambda q: "SELECT 1")
    monkeypatch.setattr(pipeline, "execute_sql", lambda sql: _frame())

    result = pipeline.run_pipeline_detailed("top categories")

    assert result.sql == "SELECT 1"
    assert result.attempts == 1
    assert result.corrections == []
    assert audit_calls[0]["status"] == "success"


def test_rejected_sql_is_repaired(monkeypatch, audit_calls):
    seen = {}

    def fake_execute(sql):
        if "bad_table" in sql:
            raise ValueError("SQL rejected: Table 'bad_table' is not available.")
        return _frame()

    def fake_repair(question, failed_sql, error):
        seen["failed_sql"] = failed_sql
        seen["error"] = error
        return "SELECT * FROM orders"

    monkeypatch.setattr(
        pipeline, "generate_sql", lambda q: "SELECT * FROM bad_table"
    )
    monkeypatch.setattr(pipeline, "execute_sql", fake_execute)
    monkeypatch.setattr(pipeline, "repair_sql", fake_repair)

    result = pipeline.run_pipeline_detailed("anything")

    assert result.sql == "SELECT * FROM orders"
    assert result.attempts == 2
    assert result.corrections[0]["sql"] == "SELECT * FROM bad_table"
    assert "bad_table" in seen["error"]
    assert audit_calls[0]["status"] == "corrected"


def test_database_error_is_repaired(monkeypatch, audit_calls):
    class FakeOrig(Exception):
        pass

    db_error = ProgrammingError(
        "SELECT x", {}, FakeOrig('column "x" does not exist')
    )
    attempts = []

    def fake_execute(sql):
        attempts.append(sql)
        if len(attempts) == 1:
            raise db_error
        return _frame()

    monkeypatch.setattr(pipeline, "generate_sql", lambda q: "SELECT x")
    monkeypatch.setattr(pipeline, "execute_sql", fake_execute)

    repair_inputs = {}

    def fake_repair(question, failed_sql, error):
        repair_inputs["error"] = error
        return "SELECT 1"

    monkeypatch.setattr(pipeline, "repair_sql", fake_repair)

    result = pipeline.run_pipeline_detailed("anything")

    assert result.attempts == 2
    assert 'column "x" does not exist' in repair_inputs["error"]


def test_gives_up_after_max_attempts(monkeypatch, audit_calls):
    repairs = []

    monkeypatch.setattr(pipeline, "generate_sql", lambda q: "SELECT bad")
    monkeypatch.setattr(
        pipeline,
        "execute_sql",
        lambda sql: (_ for _ in ()).throw(ValueError("SQL rejected: nope")),
    )
    monkeypatch.setattr(
        pipeline,
        "repair_sql",
        lambda q, s, e: repairs.append(s) or "SELECT bad",
    )

    with pytest.raises(ValueError, match="SQL rejected"):
        pipeline.run_pipeline_detailed("anything", max_attempts=3)

    assert len(repairs) == 2
    assert audit_calls[0]["status"] == "failed"
    assert audit_calls[0]["attempts"] == 3


def test_non_retryable_error_is_not_repaired(monkeypatch, audit_calls):
    repairs = []

    monkeypatch.setattr(pipeline, "generate_sql", lambda q: "SELECT 1")
    monkeypatch.setattr(
        pipeline,
        "execute_sql",
        lambda sql: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        pipeline, "repair_sql", lambda q, s, e: repairs.append(s)
    )

    with pytest.raises(RuntimeError):
        pipeline.run_pipeline_detailed("anything")

    assert repairs == []
    assert audit_calls[0]["status"] == "failed"


def test_empty_question_is_rejected():
    with pytest.raises(ValueError):
        pipeline.run_pipeline_detailed("   ")


def test_run_pipeline_keeps_the_old_return_shape(monkeypatch, audit_calls):
    monkeypatch.setattr(pipeline, "generate_sql", lambda q: "SELECT 1")
    monkeypatch.setattr(pipeline, "execute_sql", lambda sql: _frame())

    sql, dataframe = pipeline.run_pipeline("top categories")

    assert sql == "SELECT 1"
    assert list(dataframe.columns) == ["category_name", "total_sales"]


def test_clean_sql_strips_markdown_fences():
    assert clean_sql("```sql\nSELECT 1;\n```") == "SELECT 1;"
    assert clean_sql("```\nSELECT 1;\n```") == "SELECT 1;"
    assert clean_sql("  SELECT 1;  ") == "SELECT 1;"
    assert clean_sql("") == ""


def test_money_column_detection():
    assert is_money_column("total_sales")
    assert is_money_column("avg_order_price")
    assert not is_money_column("total_orders")


def test_style_results_formats_money_and_counts():
    from decimal import Decimal

    frame = pd.DataFrame(
        {
            "category_name": ["health_beauty"],
            "total_sales": [Decimal("1233131.72")],
            "total_orders": [9670],
        }
    )

    html = style_results(frame).to_html()

    assert "R$ 1,233,131.72" in html
    assert "9,670" in html
