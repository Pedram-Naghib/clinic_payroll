"""Create or reset a login for the web app. Credentials don't belong in a
migration, so this is the bootstrap path for the first 'owner' account (and
for adding the accountant(s) afterward -- from the Owner dashboard once
Users & Access is built, or by running this again until then).

Usage:
    python -m app.db.create_user --username r.sadeghi --password '...' --role owner
    python -m app.db.create_user --username m.karimi --password '...' --role accountant
    python -m app.db.create_user --username a.hosseini --password '...' --role manager
"""
from __future__ import annotations
import argparse
import getpass
import sys

from app.db.database import get_connection
from webapp.auth import hash_password


def create_or_update_user(username: str, password: str, role: str) -> None:
    if role not in ("owner", "accountant", "manager"):
        raise ValueError(f"role must be 'owner', 'accountant' or 'manager', got {role!r}")
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        password_hash = hash_password(password)
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = ?, active = 1 WHERE id = ?",
                (password_hash, role, existing["id"]),
            )
            print(f"Updated existing user '{username}' (role={role}).")
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role),
            )
            print(f"Created user '{username}' (role={role}).")
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=["owner", "accountant", "manager"])
    parser.add_argument("--password", help="omit to be prompted (won't echo to the terminal)")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    create_or_update_user(args.username, password, args.role)


if __name__ == "__main__":
    main()
