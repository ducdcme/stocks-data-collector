from __future__ import annotations

from app.db import migrate, ping


def main() -> None:
    info = ping()
    print(f"database ok: {info.get('database')}")
    applied = migrate()
    if applied:
        print("applied migrations:")
        for version in applied:
            print(f"- {version}")
    else:
        print("database schema already up to date")


if __name__ == "__main__":
    main()
