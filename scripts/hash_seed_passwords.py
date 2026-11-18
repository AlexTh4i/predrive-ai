#!/usr/bin/env python3
"""Hash '!UNSET' seed user passwords in dev/demo databases (blocked in production)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
for p in (str(ROOT_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import get_config, normalize_database_url  # noqa: E402
from app.core.security import hash_password  # noqa: E402


ROLE_DEFAULT_DEV_PASSWORDS = {
    "manager": "manager123",
    "dispatcher": "dispatcher123",
    "driver": "driver123",
}


def hash_unset_passwords(database_url: str | None = None) -> int:
    env = os.getenv("ENV", "development").strip().lower()
    if env == "production":
        raise RuntimeError("Blocked: hash_seed_passwords.py must never run with ENV=production")

    raw_url = database_url or os.getenv("DATABASE_URL") or get_config().database_url
    url = normalize_database_url(raw_url)
    engine = create_engine(url, future=True)

    hashes = {role: hash_password(pwd) for role, pwd in ROLE_DEFAULT_DEV_PASSWORDS.items()}
    updated = 0
    with engine.begin() as conn:
        for role, pwd_hash in hashes.items():
            res = conn.execute(
                text(
                    "UPDATE users SET password_hash = :pwd_hash "
                    "WHERE password_hash = '!UNSET' AND role = :role"
                ),
                {"pwd_hash": pwd_hash, "role": role},
            )
            updated += int(res.rowcount or 0)
    engine.dispose()
    return updated


def main() -> None:
    count = hash_unset_passwords()
    print(f"Updated {count} seed user password(s) for local dev/demo.")


if __name__ == "__main__":
    main()
