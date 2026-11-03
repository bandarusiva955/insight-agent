from sqlalchemy import inspect
from app.db.connection import engine


def get_schema_context():
    inspector = inspect(engine)
    schema_details = []

    tables = inspector.get_table_names(schema="public")

    for table_name in tables:
        schema_details.append(f"\nTABLE: {table_name}")

        columns = inspector.get_columns(
            table_name,
            schema="public"
        )

        schema_details.append("COLUMNS:")

        for column in columns:
            schema_details.append(
                f"- {column['name']}: {column['type']}, "
                f"nullable={column['nullable']}"
            )

        primary_key = inspector.get_pk_constraint(
            table_name,
            schema="public"
        )

        pk_columns = primary_key.get("constrained_columns") or []

        if pk_columns:
            schema_details.append(
                f"PRIMARY KEY: {', '.join(pk_columns)}"
            )

        foreign_keys = inspector.get_foreign_keys(
            table_name,
            schema="public"
        )

        for fk in foreign_keys:
            source = ", ".join(fk["constrained_columns"])
            target = fk["referred_table"]
            target_columns = ", ".join(fk["referred_columns"])

            schema_details.append(
                f"FOREIGN KEY: {source} -> "
                f"{target}({target_columns})"
            )

    return "\n".join(schema_details)


if __name__ == "__main__":
    print(get_schema_context())
