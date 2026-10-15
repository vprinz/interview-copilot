"""Копайлот на живом интервью: транскрипт → сессия nmt-chat → состояние панели.

Захват и распознавание звука идут отдельным процессом (scripts/live-transcribe.py), новые реплики
уходят в одну долгую сессию /nmt-chat раз в полминуты или по горячей клавише ⌃⌥H.
"""
import json
import re
import signal
import subprocess
import sys
import threading
import time

from copilot import context, contract, native, server
from copilot.paths import ROOT, new_call_folder
from copilot.session import Session

HEARD = re.compile(r"^\[(\d+):(\d\d)\] (Я|Респондент): (.*)$")


class Copilot:
    def __init__(self, args, folder=None):
        self.args = args
        self.folder = folder
        self.transcript = folder / "transcript.txt" if folder else None
        self.journal = folder / "panel.jsonl" if folder else None
        self.lock = threading.Lock()
        self.pending = []           # реплики, которые ещё не ушли в сессию
        self.skipped = []           # вопросы, пропущенные кнопкой, — уйдут в сессию со следующим сообщением
        self.capture_started = None  # когда пошёл звук (по часам компьютера)
        self.zero = 0.0             # с какой секунды звука считать начало интервью
        self.last_update = 0.0
        self.refresh = threading.Event()
        self.stopping = False
        self.finished = False       # прогон по записи дошёл до конца
        self.session = None
        self.children = []
        self.context_path = None    # folder/context.md — собирается до звонка (context.build)
        self.panel = contract.PanelState()
        self.state = {"status": "готовлюсь", "note": "читаю канон и контекст интервью", "minutes": args.minutes,
                      "elapsed": 0, "skipped": "", "focus": "", "heard": "", "updated": None, "took": None,
                      "context": 0, "changed": {}, "errors": []}

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

    def start_session(self, context_path):
        self.session = Session(self.args.model)
        self.children.append(self.session.process)
        kickoff = context.kickoff(context_path, self.args.minutes)
        (self.folder / "kickoff.md").write_text(kickoff)
        reply, info = self.session.ask(kickoff)
        if "ГОТОВ" not in reply.upper():
            print(f"сессия ответила неожиданно: {reply[:200]}", file=sys.stderr)
        focus = re.search(r"ФОКУС:\s*(.+)", reply)
        if focus:
            self.set(focus=focus[1].strip())
            print(f"фокус исследования: {focus[1].strip()}", file=sys.stderr)
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
                self.hear(line)

    def hear(self, line):
        heard = HEARD.match(line.strip())
        if not heard:
            return
        at = int(heard[1]) * 60 + int(heard[2])
        with self.lock:
            if at >= self.zero - 1:
                self.pending.append(heard[4] if self.args.mixed else f"{heard[3]}: {heard[4]}")
                self.state["heard"] = f"{heard[3]}: {heard[4]}"

    # --- сессия ---

    def apply(self, update):
        """Строка панели пришла и разобрана — отмечаем, когда поле менялось (подсветка на панели)."""
        self.state["changed"][update.key] = time.time()

    def skip(self):
        """Интервьюер пропустил предложенный вопрос: сразу просим другой."""
        with self.lock:
            question = self.panel.question
            if question and question not in self.skipped:
                self.skipped.append(question)
                self.state["skipped"] = question
        self.refresh.set()

    def update(self, forced):
        with self.lock:
            lines, self.pending = self.pending, []
            skipped, self.skipped = self.skipped, []
        if not lines and not forced:
            return
        elapsed = self.elapsed()
        left = max(0, self.args.minutes - int(elapsed // 60))
        head = f"[прошло {int(elapsed) // 60:02d}:{int(elapsed) % 60:02d} · осталось {left} мин]"
        body = "\n".join(lines) if lines else "(новых реплик нет — интервьюер просит подсказку сейчас)"
        body = "".join(f"ПРОПУЩЕН: {question}\n" for question in skipped) + body
        self.set(status="думаю")
        reply_parser = contract.Reply(self.panel, self.apply)

        def on_line(line):
            with self.lock:
                reply_parser.feed(line)

        try:
            reply, info = self.session.ask(f"{head}\n{body}", on_line)
        except (RuntimeError, OSError, ValueError) as error:
            self.set(status="ошибка", note=str(error))
            return
        with self.lock:
            errors = reply_parser.finish(reply) if info["ok"] else []
        if not info["ok"]:
            status, note = "ошибка", reply[:160]
        elif errors and not reply_parser.keys:
            status, note = "ответ не по формату", errors[-1][:160]
        else:
            status, note = "слушаю", ""
        self.set(status=status, note=note, updated=time.time(), took=info["took"], context=info["context"], errors=errors)
        with open(self.journal, "a") as journal:
            journal.write(json.dumps({"at": head, "sent": lines, "skipped": skipped, "reply": reply, "forced": forced, **info,
                                      "errors": errors, "panel": self.panel.as_dict()}, ensure_ascii=False) + "\n")

    def set(self, **fields):
        with self.lock:
            self.state.update(fields)

    def snapshot(self):
        with self.lock:
            now = time.time()
            wait = self.args.interval / self.args.speed - (now - self.last_update)
            return {**self.state, **self.panel.as_dict(), "elapsed": int(self.elapsed()), "now": now,
                    "next": max(0, round(wait)), "waiting": len(self.pending), "speed": self.args.speed}

    # --- окно ---

    def open_window(self):
        url = f"http://127.0.0.1:{self.args.port}/"
        try:
            binary = native.build("panel-window")
            self.children.append(subprocess.Popen([str(binary), url], start_new_session=True))
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"окно панели не открылось ({error}) — открой в браузере: {url}", file=sys.stderr)

    # --- главный цикл ---

    def run(self):
        server.serve(self, self.args.port)
        print(f"панель: http://127.0.0.1:{self.args.port}/  ·  обновить сейчас — ⌃⌥H  ·  Ctrl-C — закончить", file=sys.stderr)
        if not self.args.no_window:
            self.open_window()
        self.start_session(self.context_path)
        self.start_transcriber()
        print(f"звонок: {self.folder}", file=sys.stderr)

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


def run(args):
    """Подготовка до звонка (гайд, контекст) и сам звонок. Код выхода 2 — гайд не получен."""
    folder = new_call_folder()
    try:
        context_path, _ = context.build(folder, args.guide, args.context, args.no_defaults, args.allow_unknown)
    except context.NoGuide as error:
        print(f"\nСТОП: звонок не начат.\n{error}\nпапка: {folder}", file=sys.stderr)
        return 2
    copilot = Copilot(args, folder)
    copilot.context_path = context_path
    copilot.run()
    return 0
