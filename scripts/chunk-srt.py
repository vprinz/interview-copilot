#!/usr/bin/env python3
"""Режет .srt на куски по N секунд — так транскрипт приходил бы вживую.

    scripts/chunk-srt.py recordings/andrey.srt recordings/step2/chunks [120]

Кусок NN.txt: первая строка — «[мм:сс–мм:сс]», дальше реплики, начавшиеся в этом окне.
"""
import re
import sys
from pathlib import Path

srt, out = Path(sys.argv[1]), Path(sys.argv[2])
step = int(sys.argv[3]) if len(sys.argv) > 3 else 120
out.mkdir(parents=True, exist_ok=True)

chunks = {}
for block in srt.read_text().strip().split("\n\n"):
    lines = block.split("\n")
    m = re.match(r"(\d+):(\d+):(\d+)", lines[1])
    start = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    chunks.setdefault(start // step, []).append(" ".join(l.strip() for l in lines[2:]))

mmss = lambda s: f"{s // 60:02d}:{s % 60:02d}"
for i in range(max(chunks) + 1):
    head = f"[{mmss(i * step)}–{mmss((i + 1) * step)}]"
    (out / f"{i:02d}.txt").write_text("\n".join([head] + chunks.get(i, ["(тишина)"])) + "\n")
print(f"{max(chunks) + 1} кусков по {step} с → {out}")
