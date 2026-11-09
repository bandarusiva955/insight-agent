"""Upload -> clean -> profile -> dashboard -> report, and workspace isolation."""

import pandas as pd
import pytest
from sqlalchemy import text

from app.workspace import ingest
from app.workspace.cleaning import clean_dataframe, snake_case
from app.workspace.dashboard import build_dashboard
from app.workspace.profile import by_role, profile_frame
from app.workspace.report import build_report
from tests.support.messy_data import messy_sales_csv


@pytest.fixture(scope="module")
def cleaned():
    raw = ingest.read_upload("Sales 2024.csv", messy_sales_csv())
    (name, frame), = raw.items()

    return name, clean_dataframe(frame)


def test_upload_table_name_and_limits():
    assert ingest.table_name_from("My Sales (2024).csv") == "my_sales_2024"
    assert ingest.table_name_from("2024.csv").startswith("t_")

    with pytest.raises(ingest.UploadError):
        ingest.read_upload("x.pdf", b"abc")

    with pytest.raises(ingest.UploadError):
        ingest.read_upload("x.csv", b"a" * (ingest.MAX_BYTES + 1))


def test_semicolon_and_latin1_csv():
    data = "naam;bedrag\nJosé;1,5\nZoë;2\n".encode("latin-1")
    (frame,) = ingest.read_upload("d.csv", data).values()

    assert list(frame.columns) == ["naam", "bedrag"]
    assert frame.iloc[0, 0] == "José"


def test_cleaning_matches_planted_mess(cleaned):
    _, result = cleaned
    frame = result.frame

    assert result.rows_before == 247  # 240 + 6 duplicates + 1 empty row
    assert result.rows_after == 240
    assert list(frame.columns) == [
        "order_id", "order_date", "region", "amount", "qty", "paid", "notes",
    ]
    assert pd.api.types.is_datetime64_any_dtype(frame["order_date"])
    assert pd.api.types.is_float_dtype(frame["amount"])
    assert frame["amount"].between(20, 500).all()
    assert set(frame["region"]) == {"North", "South", "East", "West"}
    assert set(frame["paid"].dropna()) <= {True, False}
    assert frame["notes"].isna().sum() == 48  # every 5th row was "N/A"

    kinds = {s.kind for s in result.steps}
    assert {"rename", "drop_columns", "drop_rows", "duplicates", "standardize"} <= kinds


def test_order_id_stays_text_and_original_untouched():
    raw = pd.DataFrame({"zip": ["01234", "02345", "00999"], "n": ["1", "2", "3"]})
    before = raw.copy()
    result = clean_dataframe(raw)

    assert result.frame["zip"].tolist() == ["01234", "02345", "00999"]
    assert pd.api.types.is_numeric_dtype(result.frame["n"])
    pd.testing.assert_frame_equal(raw, before)


def test_outliers_and_missing_reported_not_changed():
    values = [10.0 + i * 0.001 for i in range(40)] + [11.0 + i * 0.001 for i in range(40)] + [10_000.0]
    raw = pd.DataFrame({"v": [str(v) for v in values], "w": ["x"] * 80 + [None]})
    result = clean_dataframe(raw)

    assert result.outliers == {"v": 1}
    assert result.frame["v"].max() == 10_000.0
    assert result.frame["w"].isna().sum() == 1


def test_clean_data_has_no_changes_message():
    result = clean_dataframe(pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}))

    assert result.steps[0].kind == "none"


def test_date_day_first_detection():
    raw = pd.DataFrame({"d": ["25/12/2024", "01/02/2024", "13/03/2024"]})
    frame = clean_dataframe(raw).frame

    assert frame["d"].iloc[0] == pd.Timestamp("2024-12-25")
    assert frame["d"].iloc[1] == pd.Timestamp("2024-02-01")


def test_snake_case():
    assert snake_case("Amount ($)") == "amount"
    assert snake_case("OrderID") == "order_id"
    assert snake_case("   ") == "column"


def test_profile_roles(cleaned):
    profiles = profile_frame(cleaned[1].frame)

    assert "amount" in by_role(profiles, "numeric")
    assert "order_date" in by_role(profiles, "datetime")
    assert "region" in by_role(profiles, "category")
    assert "paid" in by_role(profiles, "boolean")
    assert "order_id" in by_role(profiles, "id") or "order_id" in by_role(profiles, "text")


def test_dashboard_numbers_match_pandas(cleaned):
    frame = cleaned[1].frame
    board = build_dashboard(frame, profile_frame(frame))
    kpis = dict(board.kpis)

    assert board.measure == "amount"
    assert kpis["Rows"] == "240"
    assert kpis["Total amount"].replace(",", "") == f"{frame['amount'].sum():,.0f}".replace(",", "")
    assert len(board.charts) >= 3
    assert any("Top region" in f for f in board.findings)


def test_report_is_self_contained_and_escaped(cleaned):
    frame = cleaned[1].frame
    board = build_dashboard(frame, profile_frame(frame))
    html = build_report("<b>Q1</b> report", "sales.csv", cleaned[1], board, profile_frame(frame))

    assert html.startswith("<!doctype html>")
    assert "&lt;b&gt;Q1&lt;/b&gt;" in html
    assert "Data cleaning log" in html and "Key findings" in html


# --------------------------- database: isolation -----------------------------

@pytest.fixture
def workspace(seeded_db, cleaned):
    from app.workspace import store

    ws = store.create_workspace({"sales": cleaned[1].frame}, db_engine=seeded_db)
    yield ws
    store.drop_workspace(ws.schema, seeded_db)


@pytest.mark.db
def test_workspace_query_runs_and_matches(workspace, cleaned, seeded_db):
    from app.workspace.store import execute_workspace_sql

    out = execute_workspace_sql(
        workspace, "SELECT region, SUM(amount) AS total FROM sales GROUP BY region",
        db_engine=seeded_db,
    )
    expected = cleaned[1].frame.groupby("region")["amount"].sum()

    assert dict(zip(out["region"], out["total"].astype(float))) == pytest.approx(expected.to_dict())


@pytest.mark.db
@pytest.mark.parametrize("sql", [
    "SELECT * FROM public.orders",
    "SELECT * FROM orders",                              # exists in public, not in workspace
    "SELECT * FROM app_meta.query_audit",
    "SELECT * FROM live.order_stream",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM sales; DROP TABLE sales",
    "DELETE FROM sales",
    "SELECT pg_sleep(5)",
])
def test_workspace_cannot_escape(workspace, seeded_db, sql):
    from app.workspace.store import execute_workspace_sql

    with pytest.raises(ValueError, match="SQL rejected"):
        execute_workspace_sql(workspace, sql, db_engine=seeded_db)


@pytest.mark.db
def test_two_workspaces_are_isolated(seeded_db, cleaned):
    from app.workspace import store

    one = store.create_workspace({"sales": cleaned[1].frame}, db_engine=seeded_db)
    two = store.create_workspace({"other": pd.DataFrame({"x": [1, 2]})}, db_engine=seeded_db)

    try:
        with pytest.raises(ValueError, match="SQL rejected"):
            store.execute_workspace_sql(two, "SELECT * FROM sales", db_engine=seeded_db)

        with pytest.raises(ValueError, match="SQL rejected"):
            store.execute_workspace_sql(one, f"SELECT * FROM {two.schema}.other", db_engine=seeded_db)
    finally:
        store.drop_workspace(one.schema, seeded_db)
        store.drop_workspace(two.schema, seeded_db)


@pytest.mark.db
def test_expiry_and_drop(seeded_db):
    from app.workspace import store

    ws = store.create_workspace({"t": pd.DataFrame({"x": [1]})}, db_engine=seeded_db)

    assert store.drop_expired(seeded_db, ttl_hours=6) == 0
    assert store.drop_expired(seeded_db, ttl_hours=-1) >= 1

    with seeded_db.connect() as c:
        gone = c.execute(
            text("SELECT count(*) FROM pg_namespace WHERE nspname = :s"), {"s": ws.schema}
        ).scalar()

    assert gone == 0


def test_drop_rejects_non_workspace_schema(seeded_db):
    from app.workspace import store

    with pytest.raises(ValueError):
        store.drop_workspace("public", seeded_db)


@pytest.mark.db
def test_pipeline_with_workspace_and_repair(workspace, monkeypatch, seeded_db):
    import app.pipeline as pipeline

    seen = {}

    def fake_generate(question, **kwargs):
        seen["schema"] = kwargs.get("schema")
        return "SELECT regionn FROM sales"  # wrong column -> DB error -> repair

    def fake_repair(question, sql, reason, **kwargs):
        return "SELECT COUNT(*) AS n FROM sales"

    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(pipeline, "repair_sql", fake_repair)
    from app.workspace import store

    real = store.execute_workspace_sql
    monkeypatch.setattr(
        store, "execute_workspace_sql", lambda ws, sql: real(ws, sql, db_engine=seeded_db)
    )

    result = pipeline.run_pipeline_detailed("how many?", workspace=workspace, audit=False)

    assert result.attempts == 2
    assert int(result.dataframe.iloc[0, 0]) == 240
    assert "TABLE: sales" in seen["schema"]



def test_dashboard_monthly_trend_for_long_date_span():
    # A span over ~400 days switches the trend to monthly; this broke on pandas 3
    # ("M" offset alias removed), so keep it covered.
    frame = pd.DataFrame(
        {
            "order_date": pd.date_range("2024-01-01", periods=700, freq="D"),
            "revenue": range(700),
            "category": ["a", "b"] * 350,
        }
    )
    board = build_dashboard(frame, profile_frame(frame))
    assert board is not None
