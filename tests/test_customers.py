import numpy as np
import pandas as pd

from app.workspace import customers
from app.workspace.profile import profile_frame


def _orders():
    rng = np.random.default_rng(3)
    rows = []

    # 40 loyal recent customers: 8 orders each, latest in Dec 2024
    for i in range(40):
        for k in range(8):
            rows.append((f"loyal{i}", pd.Timestamp("2024-05-01") + pd.Timedelta(days=int(k * 28 + rng.integers(0, 5))), 100.0))

    # 40 customers who bought 3 times early in 2024 and then went silent
    for i in range(40):
        for k in range(3):
            rows.append((f"gone{i}", pd.Timestamp("2024-01-05") + pd.Timedelta(days=int(k * 20)), 50.0))

    # 40 brand new customers with a single recent order
    for i in range(40):
        rows.append((f"new{i}", pd.Timestamp("2024-12-20") + pd.Timedelta(days=int(rng.integers(0, 8))), 30.0))

    frame = pd.DataFrame(rows, columns=["customer_id", "order_date", "amount"])
    frame["order_id"] = [f"o{i}" for i in range(len(frame))]

    return frame


def _detect(frame):
    return customers.detect_columns(frame, profile_frame(frame))


def test_detects_columns_and_derives_amount_from_price_and_quantity():
    frame = _orders()

    assert _detect(frame).customer == "customer_id"
    assert _detect(frame).order == "order_id"

    derived = frame.rename(columns={"amount": "unit_price"}).assign(quantity=2)
    cols = _detect(derived)

    assert cols.amount_name == "quantity x unit_price"
    assert (cols.amount == derived["unit_price"] * 2).all()


def test_detection_fails_without_customer_or_date():
    frame = _orders()

    assert _detect(frame.drop(columns="customer_id")) is None
    assert _detect(frame.drop(columns="order_date")) is None


def test_rfm_segments_match_planted_behaviour():
    frame = _orders()
    table, summary = customers.rfm(frame, _detect(frame))
    segment = table.set_index("customer")["segment"]

    assert (segment[[f"loyal{i}" for i in range(40)]].isin(["Champions", "Loyal"])).all()
    assert (segment[[f"gone{i}" for i in range(40)]].isin(["Lost", "At risk"])).all()
    assert (segment[[f"new{i}" for i in range(40)]] == "New").mean() > 0.8
    assert abs(summary["revenue_share"].sum() - 1) < 1e-9
    assert summary["customers"].sum() == 120


def test_rfm_needs_enough_customers():
    frame = _orders()
    frame = frame[frame["customer_id"].isin([f"loyal{i}" for i in range(5)])]

    assert _detect(frame) is None  # fewer than 20 customers: nothing to segment


def test_headline_is_consistent_with_the_data():
    frame = _orders()
    table, summary = customers.rfm(frame, _detect(frame))
    lines = customers.headline(table, summary)

    assert any("at risk or lost" in line for line in lines)
    assert any("top 10%" in line for line in lines)


def test_cohort_retention_values():
    frame = _orders()
    matrix = customers.cohort_retention(frame, _detect(frame))

    assert matrix is not None
    assert (matrix[0] == 1.0).all()  # everyone is active in their first month
    january = matrix.loc["2024-01"]
    assert january["customers"] == 40
    assert january[1] == 1.0  # the "gone" group buys again 20 days later
    assert pd.isna(matrix.loc["2024-12", 1])  # that month has not happened yet


def test_panel_renders():
    from streamlit.testing.v1 import AppTest

    def app():
        from types import SimpleNamespace

        from app.ui import customers_panel
        from app.workspace.profile import profile_frame
        from tests.test_customers import _orders

        frame = _orders()
        customers_panel.render("orders", "o.csv", SimpleNamespace(frame=frame), profile_frame(frame))

    at = AppTest.from_function(app).run(timeout=60)

    assert not at.exception, [e.value for e in at.exception]
    assert any("Champions" in m.value or "customers" in m.value for m in at.markdown)
