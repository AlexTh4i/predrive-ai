#!/usr/bin/env python3
"""Wrapper to run scripts/simulate_driver.py from backend/ directory."""
from pathlib import Path
import runpy
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if __name__ == "__main__":
    runpy.run_path(str(ROOT_DIR / "scripts" / "simulate_driver.py"), run_name="__main__")

