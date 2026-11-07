"""
Make the read-only database role's password equal to the one in .env.

Run this whenever you change POSTGRES_READONLY_PASSWORD (or see
"password authentication failed for user insightagent_ro"):

    python -m app.db.sync_readonly_password

It connects as the owner, so nothing about your data changes. The password is
never printed. Use letters and digits only.
"""

import os
import re
import sys

from sqlalchemy import text

from app.db.connection import engine


def main() -> int:
    user = (os.getenv("POSTGRES_READONLY_USER") or "").strip()
    password = (os.getenv("POSTGRES_READONLY_PASSWORD") or "").strip()

    if not user or not password:
        print("POSTGRES_READONLY_USER / POSTGRES_READONLY_PASSWORD are not set in .env")
        return 1

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user):
        print("POSTGRES_READONLY_USER has unexpected characters.")
        return 1

    if not re.fullmatch(r"[A-Za-z0-9]+", password):
        print("POSTGRES_READONLY_PASSWORD must contain letters and digits only "
              "(no spaces, quotes or symbols). Fix it in .env and run again.")
        return 1

    with engine.begin() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": user}
        ).scalar()

        if not exists:
            print(f"Role '{user}' does not exist. Run app/db/create_readonly_role.sql first.")
            return 1

        connection.execute(text(f"ALTER ROLE {user} LOGIN PASSWORD '{password}'"))

    print(f"Password for '{user}' now matches .env ({len(password)} characters).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
