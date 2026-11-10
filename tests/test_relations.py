import pandas as pd

from app.workspace import relations
from app.workspace.store import Workspace


def _tables():
    customers = pd.DataFrame({
        "customer_id": [f"c{i}" for i in range(1, 21)],
        "city": ["Pune", "Delhi"] * 10,
    })
    products = pd.DataFrame({
        "product_id": list(range(1, 11)),
        "category": ["a", "b"] * 5,
        "price": range(10, 20),
    })
    orders = pd.DataFrame({
        "order_id": range(1, 101),
        "customer_id": [f"c{(i % 20) + 1}" for i in range(100)],
        "product_id": [(i % 10) + 1 for i in range(100)],
        "amount": range(100, 200),
    })

    return {"orders": orders, "customers": customers, "products": products}


def test_finds_many_to_one_relationships():
    found = relations.find_relationships(_tables())
    pairs = {(r.many_table, r.many_column, r.key_table) for r in found}

    assert pairs == {
        ("orders", "customer_id", "customers"),
        ("orders", "product_id", "products"),
    }
    assert all(r.match_share == 1.0 and r.orphan_rows == 0 for r in found)


def test_no_relationship_when_values_do_not_overlap():
    frames = _tables()
    frames["customers"]["customer_id"] = [f"x{i}" for i in range(20)]

    found = relations.find_relationships(frames)

    assert {r.key_table for r in found} == {"products"}


def test_orphans_are_counted():
    frames = _tables()
    frames["orders"].loc[:9, "customer_id"] = "missing"

    rel = next(r for r in relations.find_relationships(frames) if r.key_table == "customers")

    assert rel.orphan_rows == 10 and rel.match_share == 0.9


def test_combine_keeps_every_fact_row_and_adds_columns():
    frames = _tables()
    frames["orders"].loc[:4, "customer_id"] = "missing"
    rels = relations.find_relationships(frames)

    combined, fact = relations.combine(frames, rels)

    assert fact == "orders" and len(combined) == 100
    assert {"city", "category", "price"} <= set(combined.columns)
    assert combined["city"].isna().sum() == 5  # orphans stay, as nulls


def test_combine_handles_column_name_collisions():
    frames = _tables()
    frames["customers"]["amount"] = 1
    combined, _ = relations.combine(frames, relations.find_relationships(frames))

    assert "customers_amount" in combined.columns and "amount" in combined.columns


def test_combine_without_relationships():
    assert relations.combine(_tables(), []) == (None, None)


def test_duplicate_keys_never_duplicate_rows():
    frames = _tables()
    frames["products"] = pd.concat([frames["products"], frames["products"].head(1)])
    combined, _ = relations.combine(frames, relations.find_relationships(frames))

    assert len(combined) == 100


def test_schema_context_lists_relationships():
    rels = relations.find_relationships(_tables())
    workspace = Workspace(schema="ws_000000000000", relationships=rels)

    assert "orders.customer_id = customers.customer_id" in workspace.schema_context()


def test_multi_file_workspace_answers_join_questions(seeded_db):
    from app.workspace import store

    frames = _tables()
    rels = relations.find_relationships(frames)
    combined, _ = relations.combine(frames, rels)
    workspace = store.create_workspace({"combined": combined, **frames}, seeded_db, relationships=rels)

    try:
        out = store.execute_workspace_sql(
            workspace,
            "SELECT c.city, SUM(o.amount) AS total FROM orders o "
            "JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.city ORDER BY 1",
            seeded_db,
        )
        assert list(out["city"]) == ["Delhi", "Pune"]
        assert out["total"].sum() == sum(range(100, 200))

        flat = store.execute_workspace_sql(
            workspace, "SELECT category, COUNT(*) AS n FROM combined GROUP BY 1 ORDER BY 1", seeded_db
        )
        assert flat["n"].sum() == 100
    finally:
        store.drop_workspace(workspace.schema, seeded_db)
