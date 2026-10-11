#!/usr/bin/env python3
"""Шаг 2: прогон подсказок nmt-chat по готовому транскрипту, как будто вживую.

Одна долгая headless-сессия Claude Code: первым сообщением запускается /nmt-chat
(он один раз читает канон и контекст интервью), дальше в ту же сессию по одному
уходят куски транскрипта. Для каждого куска меряется время до первого символа
ответа и до полной панели.

    scripts/copilot-replay.py --label sonnet [--model sonnet] [--effort low] [--limit N]

Пишет recordings/step2/run-<label>/panels.md и timings.jsonl.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--label", required=True)
ap.add_argument("--model")
ap.add_argument("--effort", default="low")
ap.add_argument("--chunks", default="recordings/step2/chunks")
ap.add_argument("--context", default="recordings/step2/context.md")
ap.add_argument("--minutes", type=int, default=60)
ap.add_argument("--limit", type=int, help="сколько кусков прогнать (по умолчанию все)")
args = ap.parse_args()

out = ROOT / "recordings/step2" / f"run-{args.label}"
out.mkdir(parents=True, exist_ok=True)

cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
       "--verbose", "--include-partial-messages",
       "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
       "--tools", "Read", "--allowedTools", "Read", "--effort", args.effort]
if args.model:
    cmd += ["--model", args.model]
proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                        env={**os.environ, "NMT_NO_UPDATE_CHECK": "1"})


def ask(text):
    """Отправляет сообщение в сессию, возвращает (ответ, замеры)."""
    t0 = time.time()
    msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    first = None
    tools = 0
    model = None
    for line in proc.stdout:
        e = json.loads(line)
        if e["type"] == "system" and e.get("subtype") == "init":
            model = e.get("model")
        elif e["type"] == "stream_event":
            ev = e["event"]
            if first is None and ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                first = time.time() - t0
        elif e["type"] == "assistant":
            tools += sum(b["type"] == "tool_use" for b in e["message"]["content"])
        elif e["type"] == "result":
            u = e.get("usage", {})
            return e.get("result", ""), {
                "first_s": round(first or 0, 1), "total_s": round(time.time() - t0, 1),
                "api_s": round(e.get("duration_api_ms", 0) / 1000, 1), "tools": tools,
                "in": u.get("input_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0),
                "cost_usd": round(e.get("total_cost_usd", 0), 4), "model": model, "ok": e.get("subtype") == "success",
            }
    raise SystemExit("сессия закрылась без ответа")


kickoff = (ROOT / "scripts/copilot-kickoff.md").read_text()
kickoff = kickoff.replace("{context}", args.context).replace("{minutes}", str(args.minutes))
reply, m = ask(kickoff)
print(f"подготовка: {m['total_s']} с, чтений файлов: {m['tools']}, модель: {m['model']}, ответ: {reply.strip()[:80]}", flush=True)

panels = [f"# Прогон «{args.label}» — модель {m['model']}, effort {args.effort}\n",
          f"Подготовка (скилл читает канон и контекст): {m['total_s']} с.\n"]
with open(out / "timings.jsonl", "w") as log:
    log.write(json.dumps({"chunk": "kickoff", **m}, ensure_ascii=False) + "\n")
    prev_cost = m["cost_usd"]
    files = sorted((ROOT / args.chunks).glob("*.txt"))[: args.limit]
    for f in files:
        text = f.read_text()
        reply, m = ask(text)
        m["cost_usd"], prev_cost = round(m["cost_usd"] - prev_cost, 4), m["cost_usd"]
        head = text.split("\n", 1)[0]
        if f is files[0]:
            panels[1] = panels[1].rstrip("\n") + f" Контекст сессии к первому куску: {m['in'] + m['cache_read'] + m['cache_write']} токенов.\n"
        log.write(json.dumps({"chunk": f.stem, "time": head, "words": len(reply.split()), **m}, ensure_ascii=False) + "\n")
        log.flush()
        panels.append(f"## {head} — первая строка через {m['first_s']} с, вся панель через {m['total_s']} с\n\n{reply.strip()}\n")
        (out / "panels.md").write_text("\n".join(panels))
        print(f"{head} первая строка {m['first_s']:>5} с | вся {m['total_s']:>5} с | {m['out']} ток. | чтений {m['tools']}", flush=True)

proc.stdin.close()
proc.wait(timeout=30)
