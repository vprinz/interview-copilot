from pathlib import Path

import pytest

from copilot import guide

FIXTURES = Path(__file__).with_name("fixtures")
ONE = (FIXTURES / "guide-one-call.md").read_text()
TWO = (FIXTURES / "guide-two-calls.mcp.md").read_text()


def kinds(block):
    return [item.kind for item in block.items]


# --- заголовки блоков ---

@pytest.mark.parametrize("text, expected", [
    ("0. Контакт и правила — 3–5 мин", {"number": "0", "title": "Контакт и правила", "minutes": {"min": 3, "max": 5}}),
    ("3.1 [критерии успеха] ⭐ — 5 мин вместе с 3.6",
     {"number": "3.1", "title": "критерии успеха", "star": True, "minutes": {"min": 5, "max": 5}, "shared_with": ["3.6"]}),
    ("3. Детально изучаем задачу — ~15 мин", {"number": "3", "minutes": {"min": 15, "max": 15}}),
    ("6а. Что она видит как продавец — 3 мин ✂️", {"number": "6а", "cut": True, "star": False}),
    ("10. Рекомендации — 2–3 мин ⚠️ обязательно", {"number": "10", "must": True, "warning": "обязательно"}),
    ("9. Продажа — 5 мин ⚠️ не репетиция", {"must": False, "warning": "не репетиция"}),
    ("5. Переход: команда → ИИ — 8 мин ⭐ не резать", {"title": "Переход: команда → ИИ", "star": True, "must": True}),
    ("2. Решения и главная задача — 4 мин, по таймеру", {"minutes": {"min": 4, "max": 4}, "note": "по таймеру"}),
    ("8. Соседние задачи — если остаётся время", {"minutes": None, "note": "если остаётся время"}),
    ("2. Квалификация — до 10 мин", {"minutes": {"min": None, "max": 10}}),
    ("Вход — 2 мин", {"number": "", "title": "Вход"}),
])
def test_heading(text, expected):
    head = guide.parse_heading(text)
    assert {key: head[key] for key in expected} == expected


# --- гайд на один звонок (как шаблон) ---

def test_one_call_structure():
    g = guide.parse(ONE)
    assert g.errors == []
    assert [p.kind for p in g.parts] == ["call", "after"]
    assert g.parts[0].blocks == ["0", "2", "2.1", "3", "3.1", "3.2", "3.5", "3.7", "3.8", "3.9", "4", "8", "9", "10"]
    assert g.minutes == {"min": 45, "max": 50}
    assert g.blocks["3"].kind == "section" and g.blocks["3"].children == ["3.1", "3.2", "3.5", "3.7", "3.8", "3.9"]
    assert g.blocks["3.5"].parent == "3"
    assert g.title == ""  # у файла без метаданных заголовок даёт CLI


def test_one_call_items():
    g = guide.parse(ONE)
    assert kinds(g.blocks["2.1"]) == ["question", "alt", "trap"]
    assert kinds(g.blocks["3.1"]) == ["question", "check", "hint"]
    assert g.blocks["0"].items[1].text == "Привет! Удобно на ты? / Займёт минут сорок."
    trigger = g.blocks["3.5"]
    assert trigger.items[0].label == "[до]" and trigger.items[1].kind == "trap"
    assert [i.collapsed for i in trigger.items][-2:] == [True, True]  # тоггл со справкой
    assert g.blocks["8"].items[0].label == "[после]"
    assert g.blocks["9"].items[1].text == "Если я возьму на себя {шаг} за {X €} — начнём?"
    assert kinds(g.blocks["10"]) == ["quote"]
    assert g.blocks["4"].items[0].callout == "🧯"


def test_one_call_records_follow_titles_not_order():
    g = guide.parse(ONE)
    records = {key: [r.title for r in b.records] for key, b in g.blocks.items()}
    assert records["3.1"] == ["Критерии успеха"] and records["3.2"] == ["Бюджет"]  # справа в обратном порядке
    assert records["3.7"] == ["Позитивные эмоции"] and records["3.8"] == ["Негативные эмоции ДО"]
    assert records["3.9"] == []
    assert records["4"] == ["Числа"]  # колонки внутри раздела без своего блока
    assert g.blocks["2.1"].records[0].items[0].kind == "table"


def test_one_call_cut_rules():
    g = guide.parse(ONE)
    assert g.cut_order == ["8", "3.2", "3.9", "3.7", "3.8"]
    assert g.never_cut == ["3.1", "3.5", "4", "9", "10"]
    assert g.blocks["4"].must and g.blocks["10"].must


def test_one_call_guide_level_parts():
    g = guide.parse(ONE)
    assert [t.text for t in g.traps][1].startswith("**1. Съезд в упражнения.**")
    assert g.stop_list == [{"pattern": "Вопрос про будущее", "why": "Ответ будет фантазией"},
                           {"pattern": "Наводящий вопрос", "why": "Получишь поддакивание"}]
    assert ("🪪", "") in [(n.icon, n.after) for n in g.notes]
    card = next(n for n in g.notes if n.title.startswith("Карточка задачи"))
    assert card.after == "3.9" and card.items[-1].text == "- **хочу**:"
    assert next(i for n in g.notes for i in n.items if i.text.startswith("Изменено")).kind == "hint"


# --- гайд на два созвона, из ответа MCP ---

def test_two_calls_parts_and_ids():
    g = guide.parse(TWO)
    assert g.errors == []
    assert g.title == "2026-10-01 — Тестовый респондент / тренер"
    assert [(p.id, p.kind) for p in g.parts] == [("ч1", "call"), ("между-созвонами", "break"), ("ч2", "call"),
                                                 ("после-интервью", "after")]
    assert g.parts[0].blocks == ["0", "3.1", "3.6", "ч1-5"]
    assert g.parts[2].blocks == ["ч2-вход", "ч2-5", "6а", "9", "ч2-закрытие"]
    assert g.parts[2].minutes == {"min": 30, "max": 40}  # ⏱ внутри части не трогает весь гайд
    assert g.minutes is None


def test_two_calls_timeline_and_shared_time():
    g = guide.parse(TWO)
    assert [(t["minute"], t["blocks"]) for t in g.timeline] == [(2, ["0"]), (12, ["3.1", "3.6"]), (20, ["ч1-5"])]
    assert g.blocks["3.6"].deadline_minute == 12 and g.blocks["3.1"].shared_with == ["3.6"]
    assert not any("3.6" in w and "без времени" in w for w in g.warnings)


def test_two_calls_line_numbers_point_into_the_file():
    g = guide.parse(TWO)
    lines = TWO.split("\n")
    contact = g.blocks["0"]
    assert lines[contact.line - 1].strip() == "## 0. Контакт и правила — 2 мин"
    assert lines[contact.records[0].items[0].line - 1].strip() == "- Запись: да. 📝 «конечно, пиши»"


def test_two_calls_cleaning_and_warnings():
    g = guide.parse(TWO)
    first = g.notes[0].items[0].text
    assert "2026-10-01 15:00" in first and "<mention" not in first
    assert any("без markdown (bookmark)" in w for w in g.warnings)
    assert any("«Вход» без номера → id ч2-вход" in w for w in g.warnings)
    assert g.blocks["9"].warning == "не репетиция" and not g.blocks["9"].must


# --- ничего не теряется, ошибки громкие ---

@pytest.mark.parametrize("text", [ONE, TWO, guide.CANON.read_text()])
def test_every_line_is_placed(text):
    g = guide.parse(text)
    assert not [w for w in g.warnings if "потерялась" in w]
    assert g.lines > 0


def test_lost_line_is_reported():
    g = guide.parse("## 1. Блок — 2 мин\n> 📖 «Вопрос»")
    nonempty = {1: "## 1. Блок — 2 мин", 2: "> 📖 «Вопрос»", 3: "хвост"}
    guide.check(g, nonempty, set(), {1, 2})
    assert any("строка 3 потерялась" in w for w in g.warnings)


def test_not_a_guide_is_an_error():
    g = guide.parse("Error: MCP tool response exceeds maximum allowed tokens (31337)")
    assert any("ни одного блока" in e for e in g.errors)


def test_duplicate_number_in_one_part_is_an_error():
    g = guide.parse("## 1. Один — 2 мин\n## 1. Опять — 2 мин")
    assert any("повторяется" in e for e in g.errors)


def test_canon_guide():
    g = guide.canon()
    assert g.errors == [] and list(g.blocks) == ["1", "2", "3", "4", "5", "6"]
    assert g.blocks["2"].minutes == {"min": None, "max": 10}
    assert g.never_cut == ["4", "5", "6"]


def test_save_and_load_roundtrip(tmp_path):
    g = guide.parse(TWO, {"kind": "notion", "title": "x"})
    guide.save(g, tmp_path)
    assert guide.load(tmp_path / "guide.json") == g
    assert "[ч2-вход] Вход" in (tmp_path / "guide.report.txt").read_text()
