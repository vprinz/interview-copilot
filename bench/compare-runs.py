#!/usr/bin/env python3
"""Сравнение двух прогонов по журналам панели: до и после изменения.

Ответы модели недетерминированы, поэтому журналы дословно не сравниваются — сравниваются
числа: сколько обновлений, как быстро, как растёт контекст, как часто меняется вопрос
и сколько раз подряд он повторялся. Смысл вопросов читается глазами по двум журналам рядом.

    bench/compare-runs.py recordings/baseline/2026-10-15-v15.10_panel.jsonl recordings/live/latest/panel.jsonl
"""
import json
import re
import statistics
import sys
from pathlib import Path


def field(reply, key):
    found = re.search(rf"^\s*{key}:\s*(.*)$", reply, re.M)
    return found[1].strip() if found else None


def metrics(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    took = [r["took"] for r in rows]
    questions, last = [], ""
    for r in rows:
        value = field(r["reply"], "ВОПРОС")
        last = last if value in (None, "=") else value
        questions.append(last)
    changes = sum(a != b for a, b in zip(questions, questions[1:], strict=False))
    streak = longest = 1
    for a, b in zip(questions, questions[1:], strict=False):
        streak = streak + 1 if a == b else 1
        longest = max(longest, streak)
    return {
        "обновлений": len(rows),
        "ответ, медиана, с": statistics.median(took),
        "ответ, максимум, с": max(took),
        "контекст в начале, тыс.": round(rows[0]["context"] / 1000),
        "контекст в конце, тыс.": round(rows[-1]["context"] / 1000),
        "смен вопроса": changes,
        "дольше всего один вопрос, обновлений": longest,
        "без вопроса": sum(not q for q in questions),
        "вопросов с блоком гайда": sum(" | " in q for q in questions),
        "без строки ЗАДАЧИ": sum(field(r["reply"], "ЗАДАЧИ") is None for r in rows),
        "ошибок сессии": sum(not r["ok"] for r in rows),
        "ошибок формата": sum(len(r.get("errors", [])) for r in rows),
    }


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    before, after = metrics(sys.argv[1]), metrics(sys.argv[2])
    width = max(map(len, before))
    print(f"{'':{width}}   до      после")
    for key in before:
        print(f"{key:{width}}   {before[key]!s:7} {after[key]!s}")


if __name__ == "__main__":
    main()
