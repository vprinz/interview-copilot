"""Оркестратор без звука и без модели: сессия подменена заглушкой."""
import io
import json
from types import SimpleNamespace

from copilot import app
from copilot.session import Session

ARGS = SimpleNamespace(minutes=60, interval=30, speed=1.0, mixed=False, model="m")


class FakeSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def ask(self, text, on_line=None):
        self.sent.append(text)
        reply, ok = self.replies.pop(0)
        if on_line:
            for line in reply.split("\n"):
                on_line(line)
        return reply, {"took": 1.0, "out": 10, "context": 1000, "ok": ok}


def copilot(tmp_path, replies):
    c = app.Copilot(ARGS, tmp_path)
    c.session = FakeSession(replies)
    return c


def journal(tmp_path):
    return [json.loads(line) for line in (tmp_path / "panel.jsonl").read_text().splitlines()]


def test_lines_go_to_session_with_time_and_speakers(tmp_path):
    c = copilot(tmp_path, [("ВОПРОС: 1 · квалификация | Где живёшь?", True)])
    c.hear("[00:05] Я: Привет\n")
    c.hear("[00:09] Респондент: Привет, рада\n")
    c.hear("мусор без времени\n")
    c.update(forced=False)
    assert c.session.sent == ["[прошло 00:00 · осталось 60 мин]\nЯ: Привет\nРеспондент: Привет, рада"]
    state = c.snapshot()
    assert state["question"] == "Где живёшь?" and state["topic"] == "1 · квалификация" and state["status"] == "слушаю"
    assert "ВОПРОС" in state["changed"]
    entry = journal(tmp_path)[0]
    assert entry["sent"] == ["Я: Привет", "Респондент: Привет, рада"] and entry["errors"] == []
    assert entry["panel"]["question"] == "Где живёшь?"


def test_nothing_new_and_not_forced_sends_nothing(tmp_path):
    c = copilot(tmp_path, [])
    c.update(forced=False)
    assert c.session.sent == []


def test_forced_without_lines_asks_now(tmp_path):
    c = copilot(tmp_path, [("ВОПРОС: Что ещё?", True)])
    c.update(forced=True)
    assert c.session.sent[0].endswith("(новых реплик нет — интервьюер просит подсказку сейчас)")


def test_skip_goes_to_session_once(tmp_path):
    c = copilot(tmp_path, [("ВОПРОС: 3.5 · триггер | Когда началось?", True), ("ВОПРОС: 3.1 · критерии | Как понимаешь?", True)])
    c.hear("[01:00] Респондент: ответ\n")
    c.update(forced=False)
    c.skip()
    c.skip()  # второй раз тот же вопрос не добавляется
    assert c.refresh.is_set() and c.snapshot()["skipped"] == "Когда началось?"
    c.update(forced=True)
    assert c.session.sent[1].split("\n")[1] == "ПРОПУЩЕН: Когда началось?"
    assert journal(tmp_path)[1]["skipped"] == ["Когда началось?"]
    assert c.snapshot()["question"] == "Как понимаешь?"


def test_restart_clock_drops_lines_before_zero(tmp_path):
    c = copilot(tmp_path, [])
    c.capture_started = 0.0  # звук идёт давно
    c.hear("[00:10] Я: до старта\n")
    c.restart_clock()
    assert c.pending == []
    c.zero = 120.0
    c.hear("[01:00] Я: старое\n")
    c.hear("[02:00] Я: новое\n")
    assert c.pending == ["Я: новое"]


def test_mixed_recording_has_no_speakers(tmp_path):
    c = app.Copilot(SimpleNamespace(**{**vars(ARGS), "mixed": True}), tmp_path)
    c.hear("[00:05] Респондент: текст\n")
    assert c.pending == ["текст"]


def test_reply_out_of_format_is_visible(tmp_path):
    c = copilot(tmp_path, [("Не могу ответить: лимит исчерпан.", True)])
    c.update(forced=True)
    state = c.snapshot()
    assert state["status"] == "ответ не по формату" and "нет ни одной строки панели" in state["note"]
    assert journal(tmp_path)[0]["errors"]


def test_failed_reply_is_an_error(tmp_path):
    c = copilot(tmp_path, [("Credit balance is too low", False)])
    c.update(forced=True)
    assert c.snapshot()["status"] == "ошибка" and c.snapshot()["note"] == "Credit balance is too low"


def test_session_reads_stream_by_lines():
    events = [
        {"type": "system"},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "БЛОК: прокопка\nВОП"}}},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "РОС: Что ещё?"}}},
        {"type": "result", "subtype": "success", "result": "БЛОК: прокопка\nВОПРОС: Что ещё?",
         "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}},
    ]
    process = SimpleNamespace(stdin=io.StringIO(), stdout=iter(json.dumps(e) + "\n" for e in events))
    lines = []
    reply, info = Session("m", process).ask("привет", lines.append)
    assert lines == ["БЛОК: прокопка", "ВОПРОС: Что ещё?"]
    assert reply.endswith("Что ещё?") and info["ok"] and info["context"] == 105 and info["out"] == 7
    sent = json.loads(process.stdin.getvalue())
    assert sent["message"]["content"][0]["text"] == "привет"
