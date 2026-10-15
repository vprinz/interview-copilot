#!/usr/bin/env python3
"""Шаг 3: живой захват звука → транскрипт. Код — в src/copilot/transcribe/live.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from copilot.transcribe.live import main  # noqa: E402

if __name__ == "__main__":
    main()
