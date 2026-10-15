import pytest

from copilot import context, contract


def feed(text, state=None):
    state = state or contract.PanelState()
    reply = contract.Reply(state)
    for line in text.split("\n"):
        reply.feed(line)
    return state, reply.finish(text)


def test_example_matches_format():
    state, errors = feed(contract.EXAMPLE)
    assert errors == []
    format_keys = [line.split(":", 1)[0] for line in contract.FORMAT.split("\n")]
    assert tuple(format_keys) == contract.KEYS
    assert state.question.startswith("По каким признакам") and state.topic == "3.1 Критерии успеха · порог"
    assert state.tasks == ["получать клиентов из блога", "регулярно выпускать ролики"]
    assert state.dig == 0 and state.why == "ближе к бизнес-цели"
    assert state.slots[0] == {"name": "результат", "mark": "✓", "text": "клиенты из блога"}
    assert state.slots[1]["mark"] == "≈"
    assert state.block == "прокопка" and state.ahead == "продажа, рекомендации"


def test_kickoff_contains_format_and_no_placeholders(tmp_path):
    path = context.ROOT / "recordings/x/context.md"
    text = context.kickoff(path, 45)
    assert contract.FORMAT in text and "recordings/x/context.md" in text and "на 45 минут" in text
    assert "{" + "format}" not in text and "{context}" not in text and "{minutes}" not in text
    assert text.startswith("/nmt-chat ")


def test_equals_keeps_previous_value():
    state, _ = feed("ВОПРОС: 2 · решения | Что ещё?\nФЛАЖКИ: абстракция")
    feed("ВОПРОС: 2 · решения | Что ещё?\nФЛАЖКИ: =\nЗАДАЧИ: =", state)
    assert state.flags == ["абстракция"]


@pytest.mark.parametrize("value, topic, question", [
    ("Что ещё?", "", "Что ещё?"),                                  # формат до 15.10 — без блока
    ("3.5 Триггер · событие | «Когда это началось?»", "3.5 Триггер · событие", "Когда это началось?"),
    ("a | b | В какой момент?", "a | b", "В какой момент?"),
])
def test_question_with_and_without_topic(value, topic, question):
    state, _ = feed(f"ВОПРОС: {value}")
    assert (state.topic, state.question) == (topic, question)


def test_tasks_numbered_and_without_choice():
    state, _ = feed("ЗАДАЧИ: 1. получать клиентов | 2) вести блог → копать: пока не выбрана")
    assert state.tasks == ["получать клиентов", "вести блог"] and state.dig is None and state.why == "пока не выбрана"
    state, _ = feed("ЗАДАЧИ: —")
    assert state.tasks == []


def test_flags_dash_clears():
    state, _ = feed("ФЛАЖКИ: одно | другое")
    feed("ФЛАЖКИ: —", state)
    assert state.flags == []


def test_unknown_slot_is_ignored_known_are_kept():
    state, _ = feed("СОБРАНО: результат ✓ клиенты | цена ✓ 100 | триггер ≈ переезд")
    assert state.slots[3] == {"name": "триггер", "mark": "≈", "text": "переезд"}
    assert [s["name"] for s in state.slots] == contract.SLOTS


def test_unknown_field_is_an_error_but_panel_stays():
    state, errors = feed("ВОПРОС: Что ещё?\nПОДСКАЗКА: что-то новое")
    assert state.question == "Что ещё?" and errors == ["незнакомое поле ПОДСКАЗКА: ПОДСКАЗКА: что-то новое"]


def test_reply_without_panel_is_an_error():
    state, errors = feed("Извините, я не могу продолжить: лимит исчерпан.")
    assert state == contract.PanelState() and "нет ни одной строки панели" in errors[0]


def test_reply_of_only_equals_is_fine():
    _, errors = feed("БЛОК: =\nЗАДАЧИ: =\nВОПРОС: =")
    assert errors == []


def test_plain_text_lines_are_not_errors():
    _, errors = feed("Вот панель:\nВОПРОС: Что ещё?")
    assert errors == []
