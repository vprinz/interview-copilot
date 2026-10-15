import pytest

from copilot import context, contract


def feed(text, state=None, ids=None):
    state = state or contract.PanelState()
    reply = contract.Reply(state, ids=ids)
    for line in text.split("\n"):
        reply.feed(line)
    return state, reply.finish(text)


def test_example_matches_format():
    state, errors = feed(contract.EXAMPLE)
    assert errors == []
    format_keys = [line.split(":", 1)[0] for line in contract.FORMAT.split("\n")]
    assert tuple(format_keys) == contract.KEYS
    assert state.question.startswith("По каким признакам") and state.topic == "3.1 · порог критерия"
    assert (state.topic_id, state.fills) == ("3.1", "порог критерия")
    assert (state.block_id, state.ahead_ids, state.cut_ids) == ("3.1", ["4.2", "6", "9", "10"], ["8", "7"])
    assert state.tasks == ["получать клиентов из блога", "регулярно выпускать ролики"]
    assert state.dig == 0 and state.why == "ближе к бизнес-цели"
    assert state.slots[0] == {"name": "результат", "mark": "✓", "text": "клиенты из блога"}
    assert state.slots[1]["mark"] == "≈"


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


# --- версия 2: id блоков ---

IDS = {"0", "1", "2", "3", "3.1", "3.5", "4", "4.2", "6", "7", "8", "9", "10", "ч2-вход"}


def test_v1_block_line_still_parses_without_ids():
    state, errors = feed("БЛОК: прокопка | продажа, рекомендации", ids=IDS)
    assert (state.block, state.ahead, state.block_id, state.ahead_ids) == ("прокопка", "продажа, рекомендации", "", [])
    assert errors == []


def test_block_line_with_ids():
    state, errors = feed("БЛОК: ч2-вход | впереди: 4.2, 6 и 9 | резать: —", ids=IDS)
    assert (state.block_id, state.ahead_ids, state.cut_ids) == ("ч2-вход", ["4.2", "6", "9"], [])
    assert errors == []


def test_unknown_id_is_an_error_but_text_stays():
    state, errors = feed("БЛОК: 3.7 | впереди: 4.2, 11 | резать: 8\nВОПРОС: 2.3 · уровень | Зачем тебе это?", ids=IDS)
    assert state.block == "3.7" and state.block_id == "" and state.ahead_ids == ["4.2"] and state.cut_ids == ["8"]
    assert state.question == "Зачем тебе это?" and state.topic == "2.3 · уровень" and state.topic_id == ""
    assert [e.split(":")[0] for e in errors] == ["блока 3.7 нет в гайде", "блока 11 нет в гайде", "блока 2.3 нет в гайде"]


def test_topic_without_dot_and_without_id():
    state, _ = feed("ВОПРОС: 3.5 Триггер | Когда?", ids=IDS)
    assert (state.topic_id, state.fills) == ("3.5", "")
    state, _ = feed("ВОПРОС: прокопка · триггер | Когда?", ids=IDS)
    assert (state.topic_id, state.fills) == ("", "триггер")


def test_without_guide_ids_any_id_is_accepted():
    state, errors = feed("БЛОК: 7.3 | впереди: 9")
    assert state.block_id == "7.3" and state.ahead_ids == ["9"] and errors == []


def test_schema_file_is_current():
    import json

    from copilot.paths import PACKAGE
    written = json.loads((PACKAGE / "web/panel-state.schema.json").read_text())
    assert written == contract.state_schema(), "перегенерируй: PYTHONPATH=src python3 -m copilot.contract"


@pytest.mark.parametrize("text, ids", [
    ("4.2, 6 и 9", ["4.2", "6", "9"]),
    ("4.2 ⭐, 10.", ["4.2", "10"]),
    ("ч2-вход; 3.5", ["ч2-вход", "3.5"]),
    ("3.1, 9 через 5 мин, 10", ["3.1", "10"]),
    ("продажа через 5 мин", []),
    ("—", []),
])
def test_find_ids_takes_whole_list_items_only(text, ids):
    assert contract.find_ids(text) == ids
