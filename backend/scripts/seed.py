#!/usr/bin/env python3
"""Idempotent database seed script for PreDrive AI Backend M3.

Creates:
- 1 organization ("Nhà xe Phương Trang - Chi nhánh Miền Nam")
- 1 manager (username: manager / password: manager123)
- 1 dispatcher (username: dispatcher / password: dispatcher123)
- 5 Vietnamese drivers (driver1..driver5 / password: driver123)
- 5 vehicles
- ~30 days of historical sessions & events with alerts concentrated around 02:00-04:00 AM VN time.
"""
import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.database import Base, SessionLocal, engine
from app.services.seed import seed_database


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        summary = seed_database(db)
    print("=== SEED DATABASE M3 COMPLETED (IDEMPOTENT) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\nTài khoản mẫu:")
    print("  - Quản lý (manager):     manager / manager123")
    print("  - Người trực (dispatch): dispatcher / dispatcher123")
    print("  - Tài xế 1..5 (driver):  driver1..driver5 / driver123")


if __name__ == "__main__":
    main()

