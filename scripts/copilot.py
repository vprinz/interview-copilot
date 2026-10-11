#!/usr/bin/env python3
"""Шаг 4: копайлот на живом интервью — транскрипт → подсказки nmt-chat → панель рядом со звонком.

Запускает захват и распознавание звука (scripts/live-transcribe.py), одну долгую сессию
/nmt-chat (она один раз читает канон и контекст интервью) и панель. Новые реплики уходят
в сессию раз в полминуты или по горячей клавише ⌃⌥H.

    scripts/copilot.py --guide https://app.notion.com/p/…      # гайд под респондента из Notion
    scripts/copilot.py --guide guide.md --headphones --minutes 45
    scripts/copilot.py --no-defaults --context recordings/step2/context.md --mixed \\
        --replay-sys recordings/work/andrey-16k.wav --speed 4   # прогон по записи

Цель и гипотезы берутся из product.md и research/design.md (см. DEFAULT_CONTEXT).
Всё, что относится к звонку, лежит в recordings/live/: транскрипт, контекст, журнал панели.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "recordings/live"
DEFAULT_CONTEXT = [Path.home() / "projects/curator-product/product.md",
                   Path.home() / "projects/curator-product/research/design.md"]
NOTION_FETCH = "mcp__claude_ai_Notion__notion-fetch"
SLOTS = ["результат", "критерии", "контекст", "триггер", "выше", "эмоции", "частота", "важность"]
LINE = re.compile(r"^\s*(БЛОК|ЗАДАЧИ|СОБРАНО|ВОПРОС|ФЛАЖКИ|КАНОН):\s*(.*?)\s*$")
HEARD = re.compile(r"^\[(\d+):(\d\d)\] (Я|Респондент): (.*)$")


def fetch_notion(url):
    """Достаёт страницу Notion отдельным коротким вызовом Claude и возвращает её текст как есть."""
    prompt = f"Вызови инструмент notion-fetch для страницы {url} и после этого ответь одним словом: готово."
    run = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--disable-slash-commands",
                          "--model", "claude-haiku-5-5", "--allowedTools", NOTION_FETCH],
                         input=prompt, capture_output=True, text=True, cwd=ROOT)
    for line in run.stdout.splitlines():
        event = json.loads(line)
        if event.get("type") != "user":
            continue
        for block in event["message"]["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result" and not block.get("is_error"):
                content = block["content"]
                text = content if isinstance(content, str) else "".join(part.get("text", "") for part in content)
                if len(text) > 500:
                    try:
                        return json.loads(text).get("text", text)
                    except ValueError:
                        return text
    raise SystemExit(f"не удалось получить страницу Notion: {url}")


class Copilot:
    def __init__(self, args):
        self.args = args
        self.stamp = time.strftime("%Y-%m-%d_%H%M")
        self.transcript = LIVE / f"{self.stamp}.txt"
        self.journal = LIVE / f"{self.stamp}_panel.jsonl"
        self.lock = threading.Lock()
        self.pending = []           # реплики, которые ещё не ушли в сессию
        self.capture_started = None  # когда пошёл звук (по часам компьютера)
        self.zero = 0.0             # с какой секунды звука считать начало интервью
        self.last_update = 0.0
        self.refresh = threading.Event()
        self.stopping = False
        self.finished = False       # прогон по записи дошёл до конца
        self.session = None
        self.children = []
        self.state = {"status": "готовлюсь", "note": "читаю канон и контекст интервью", "minutes": args.minutes,
                      "elapsed": 0, "block": "", "ahead": "", "tasks": [], "dig": None, "why": "",
                      "slots": [{"name": name, "mark": "✗", "text": ""} for name in SLOTS],
                      "question": "", "flags": [], "canon": "", "heard": "", "updated": None, "took": None,
                      "context": 0, "changed": {}}

    # --- время ---

    def audio_now(self):
        """Секунда звука, которая звучит сейчас. В прогоне по записи время идёт быстрее в speed раз."""
        return (time.time() - self.capture_started) * self.args.speed if self.capture_started else 0.0

    def elapsed(self):
        return max(0.0, self.audio_now() - self.zero)

    def restart_clock(self):
        with self.lock:
            self.zero = self.audio_now()
            self.pending.clear()

    # --- подготовка ---

    def build_context(self):
        sources = [] if self.args.no_defaults else [p for p in DEFAULT_CONTEXT if p.exists()]
        parts = []
        for source in sources + self.args.context + self.args.guide:
            if str(source).startswith("http"):
                print(f"читаю гайд из Notion: {source}", file=sys.stderr)
                parts.append(f"# Гайд под респондента (Notion)\n\n{fetch_notion(source)}")
            else:
                path = Path(source).expanduser()
                parts.append(f"# {path.name}\n\n{path.read_text()}")
        if not parts:
            raise SystemExit("нет контекста интервью: укажи --guide или --context")
        if not self.args.guide:
            print("внимание: гайд под респондента не задан (--guide) — подсказки пойдут только от цели и гипотез", file=sys.stderr)
        path = LIVE / f"{self.stamp}_context.md"
        path.write_text("\n\n---\n\n".join(parts))
        return path

    def start_session(self, context):
        self.session = subprocess.Popen(
            ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
             "--include-partial-messages", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
             "--tools", "Read", "--allowedTools", "Read", "--effort", "low", "--model", self.args.model],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={**os.environ, "NMT_NO_UPDATE_CHECK": "1"}, start_new_session=True)
        self.children.append(self.session)
        kickoff = (ROOT / "scripts/copilot-kickoff.md").read_text()
        kickoff = kickoff.replace("{context}", str(context.relative_to(ROOT))).replace("{minutes}", str(self.args.minutes))
        reply, info = self.ask(kickoff)
        if "ГОТОВ" not in reply.upper():
            print(f"сессия ответила неожиданно: {reply[:200]}", file=sys.stderr)
        print(f"сессия nmt-chat готова за {info['took']} с", file=sys.stderr)

    def start_transcriber(self):
        a = self.args
        cmd = [sys.executable, str(ROOT / "scripts/live-transcribe.py"), "--out", str(self.transcript)]
        cmd += ["--headphones"] * a.headphones + ["--keep-audio"] * a.keep_audio
        for flag, value in (("--replay-sys", a.replay_sys), ("--replay-mic", a.replay_mic)):
            if value:
                cmd += [flag, value]
        if a.replay_sys or a.replay_mic:
            cmd += ["--replay-from", str(a.replay_from), "--replay-seconds", str(a.replay_seconds), "--speed", str(a.speed)]
        transcriber = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, start_new_session=True)
        self.children.append(transcriber)
        threading.Thread(target=self.follow_transcript, args=(transcriber,), daemon=True).start()

    def follow_transcript(self, transcriber):
        while not self.transcript.exists():
            if transcriber.poll() is not None:
                self.set(status="ошибка", note="распознавание не запустилось — см. терминал")
                return
            time.sleep(0.2)
        self.capture_started = time.time()
        self.set(status="слушаю", note="")
        with open(self.transcript) as lines:
            while not self.stopping:
                line = lines.readline()
                if not line.endswith("\n"):
                    if transcriber.poll() is not None and not line:
                        self.finished = True
                        return
                    time.sleep(0.2)
                    continue
                heard = HEARD.match(line.strip())
                if not heard:
                    continue
                at = int(heard[1]) * 60 + int(heard[2])
                with self.lock:
                    if at >= self.zero - 1:
                        self.pending.append(heard[4] if self.args.mixed else f"{heard[3]}: {heard[4]}")
                        self.state["heard"] = f"{heard[3]}: {heard[4]}"

    # --- сессия ---

    def ask(self, text, on_line=None):
        """Отправляет сообщение в сессию. on_line вызывается для каждой готовой строки ответа."""
        started = time.time()
        message = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.session.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.session.stdin.flush()
        tail = ""
        for raw in self.session.stdout:
            event = json.loads(raw)
            kind = event.get("type")
            if kind == "stream_event" and on_line:
                delta = event["event"].get("delta", {})
                if delta.get("type") == "text_delta":
                    *done, tail = (tail + delta["text"]).split("\n")
                    for line in done:
                        on_line(line)
            elif kind == "result":
                if on_line and tail:
                    on_line(tail)
                usage = event.get("usage", {})
                info = {"took": round(time.time() - started, 1), "out": usage.get("output_tokens", 0),
                        "context": sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
                        "ok": event.get("subtype") == "success" and not event.get("is_error")}
                return event.get("result") or "", info
        raise RuntimeError("сессия nmt-chat закрылась")

    def apply(self, line):
        """Разбирает одну строку панели и кладёт её в состояние. «=» — строка не изменилась."""
        found = LINE.match(line)
        if not found or found[2] in ("=", ""):
            return
        key, value = found[1], found[2]
        with self.lock:
            s = self.state
            if key == "БЛОК":
                s["block"], _, s["ahead"] = (part.strip() for part in value.partition("|"))
            elif key == "ЗАДАЧИ":
                left, _, right = value.partition("→")
                s["tasks"] = [re.sub(r"^\d+[.)]?\s*", "", task.strip()) for task in left.split("|") if task.strip(" —")]
                choice = re.search(r"(\d)\s*[—–-]\s*(.*)", right)
                s["dig"], s["why"] = (int(choice[1]) - 1, choice[2].strip()) if choice else (None, right.replace("копать:", "").strip())
            elif key == "СОБРАНО":
                for part in value.split("|"):
                    slot = re.match(r"\s*(\S+)\s*(✓|≈|✗)\s*(.*?)\s*$", part)
                    if slot and slot[1] in SLOTS:
                        s["slots"][SLOTS.index(slot[1])] = {"name": slot[1], "mark": slot[2], "text": slot[3]}
            elif key == "ВОПРОС":
                s["question"] = value.strip("«»\"")
            elif key == "ФЛАЖКИ":
                s["flags"] = [] if value.strip() in ("—", "-") else [flag.strip() for flag in value.split("|") if flag.strip()]
            elif key == "КАНОН":
                s["canon"] = value
            s["changed"][key] = time.time()

    def update(self, forced):
        with self.lock:
            lines, self.pending = self.pending, []
        if not lines and not forced:
            return
        elapsed = self.elapsed()
        left = max(0, self.args.minutes - int(elapsed // 60))
        head = f"[прошло {int(elapsed) // 60:02d}:{int(elapsed) % 60:02d} · осталось {left} мин]"
        body = "\n".join(lines) if lines else "(новых реплик нет — интервьюер просит подсказку сейчас)"
        self.set(status="думаю")
        try:
            reply, info = self.ask(f"{head}\n{body}", self.apply)
        except (RuntimeError, OSError, ValueError) as error:
            self.set(status="ошибка", note=str(error))
            return
        note = "" if info["ok"] else reply[:160]
        self.set(status="слушаю" if info["ok"] else "ошибка", note=note, updated=time.time(), took=info["took"], context=info["context"])
        with open(self.journal, "a") as journal:
            journal.write(json.dumps({"at": head, "sent": lines, "reply": reply, "forced": forced, **info}, ensure_ascii=False) + "\n")

    def set(self, **fields):
        with self.lock:
            self.state.update(fields)

    def snapshot(self):
        with self.lock:
            now = time.time()
            wait = self.args.interval / self.args.speed - (now - self.last_update)
            return {**self.state, "elapsed": int(self.elapsed()), "now": now, "next": max(0, round(wait)),
                    "waiting": len(self.pending), "speed": self.args.speed}

    # --- панель ---

    def serve(self):
        copilot = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, body, kind):
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/state":
                    self.reply(json.dumps(copilot.snapshot(), ensure_ascii=False).encode(), "application/json")
                else:
                    self.reply((ROOT / "scripts/panel.html").read_bytes(), "text/html; charset=utf-8")

            def do_POST(self):
                if self.path == "/refresh":
                    copilot.refresh.set()
                elif self.path == "/restart-clock":
                    copilot.restart_clock()
                self.reply(b"{}", "application/json")

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", self.args.port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def open_window(self):
        url = f"http://127.0.0.1:{self.args.port}/"
        binary, source = ROOT / "bin/panel-window", ROOT / "scripts/panel-window.swift"
        try:
            if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
                print("собираю bin/panel-window…", file=sys.stderr)
                binary.parent.mkdir(exist_ok=True)
                subprocess.run(["swiftc", "-O", "-swift-version", "5", str(source), "-o", str(binary),
                                "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist",
                                "-Xlinker", str(ROOT / "scripts/panel-window.plist")], check=True)
            self.children.append(subprocess.Popen([str(binary), url], start_new_session=True))
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"окно панели не открылось ({error}) — открой в браузере: {url}", file=sys.stderr)

    # --- главный цикл ---

    def run(self):
        LIVE.mkdir(parents=True, exist_ok=True)
        self.serve()
        print(f"панель: http://127.0.0.1:{self.args.port}/  ·  обновить сейчас — ⌃⌥H  ·  Ctrl-C — закончить", file=sys.stderr)
        if not self.args.no_window:
            self.open_window()
        self.start_session(self.build_context())
        self.start_transcriber()
        print(f"транскрипт: {self.transcript}", file=sys.stderr)

        def stop(*_):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        try:
            while True:
                forced = self.refresh.wait(0.5)
                self.refresh.clear()
                due = time.time() - self.last_update >= self.args.interval / self.args.speed
                if forced or ((due or self.finished) and self.pending):
                    self.last_update = time.time()
                    self.update(forced)
                if self.finished and not self.pending:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.stopping = True
            for child in reversed(self.children):
                if child.poll() is None:
                    child.terminate()
            print(f"\nтранскрипт: {self.transcript}\nжурнал панели: {self.journal}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guide", action="append", default=[], help="гайд под респондента: файл или ссылка на страницу Notion")
    parser.add_argument("--context", action="append", default=[], help="ещё файл с контекстом интервью")
    parser.add_argument("--no-defaults", action="store_true", help="не подмешивать product.md и design.md")
    parser.add_argument("--minutes", type=int, default=60, help="на сколько минут рассчитан звонок")
    parser.add_argument("--interval", type=float, default=30, help="как часто обновлять панель, секунд")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-window", action="store_true", help="не открывать окно панели, только страницу в браузере")
    parser.add_argument("--headphones", action="store_true", help="я в наушниках: микрофон не слышит респондента")
    parser.add_argument("--keep-audio", action="store_true", help="сохранить звук обоих каналов рядом с транскриптом")
    parser.add_argument("--mixed", action="store_true", help="запись одной сведённой дорожкой: не помечать говорящих")
    parser.add_argument("--replay-sys", help="WAV вместо системного звука")
    parser.add_argument("--replay-mic", help="WAV вместо микрофона")
    parser.add_argument("--replay-from", type=float, default=0)
    parser.add_argument("--replay-seconds", type=float, default=1e9)
    parser.add_argument("--speed", type=float, default=1.0, help="скорость прогона записи; 1 — как вживую")
    Copilot(parser.parse_args()).run()


if __name__ == "__main__":
    main()
