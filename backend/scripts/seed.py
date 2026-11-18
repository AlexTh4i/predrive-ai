#!/usr/bin/env python3
"""Idempotent dev/demo seed script for PreDrive AI Backend (blocked in production)."""
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.config import get_config  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.services.seed import seed_database  # noqa: E402


def main() -> None:
    cfg = get_config()
    if cfg.is_production:
        print("ERROR: Seeding is strictly disabled when ENV=production.", file=sys.stderr)
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        summary = seed_database(db)
    print("=== SEED DATABASE COMPLETED (IDEMPOTENT, DEV/DEMO ONLY) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\nTài khoản mẫu (Công ty 1 - Vận tải Bình Minh):")
    print("  - Quản lý (manager):     manager / manager123")
    print("  - Người trực (dispatch): dispatcher / dispatcher123")
    print("  - Tài xế 1..5 (driver):  driver1..driver5 / driver123")


if __name__ == "__main__":
    main()
