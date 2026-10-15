#!/usr/bin/env python3
"""Копайлот на живом интервью. Код — в src/copilot (см. docs/architecture.md), флаги — scripts/copilot.py --help."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from copilot.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
