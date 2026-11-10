#!/usr/bin/env python3
"""Wrapper script to run backend/scripts/seed.py from repo root."""
from pathlib import Path
import runpy
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

if __name__ == "__main__":
    runpy.run_path(str(BACKEND_DIR / "scripts" / "seed.py"), run_name="__main__")

