from pathlib import Path

from copilot import guide, timeline

FIXTURES = Path(__file__).with_name("fixtures")
ONE = guide.parse((FIXTURES / "guide-one-call.md").read_text())
TWO = guide.parse((FIXTURES / "guide-two-calls.mcp.md").read_text())


def by_id(state):
    return {item["id"]: item for item in state["items"]}


def test_windows_follow_minutes_and_sections():
    spans = timeline.windows(ONE, guide.part_of(ONE))
    # 0: 3 мин, 2: 5–10 → 10, 3: ~15, 4: 5, 8: без времени, 9: 5, 10: 2
    assert spans["0"] == (0, 3) and spans["2"] == (3, 13) and spans["3"] == (13, 28)
    assert spans["3.5"] == spans["3"] and spans["8"] == (33, 33) and spans["10"] == (38, 40)


def test_windows_use_deadlines_and_shared_time():
    part = guide.part_of(TWO, "ч1")
    spans = timeline.windows(TWO, part)
    assert spans["0"] == (0, 2) and spans["3.1"] == (2, 12) and spans["3.6"] == spans["3.1"] and spans["ч1-5"] == (12, 20)


def test_current_done_plan_and_behind():
    state = timeline.build(ONE, guide.part_of(ONE), 30 * 60, "3.5", cut_ids=["8"], ahead_ids=["4", "9", "77"])
    items = by_id(state)
    assert items["3.5"]["state"] == "current" and items["3"]["state"] == "current"
    assert items["2"]["state"] == "done" and items["3.1"]["state"] == "done" and items["3.7"]["state"] == "ahead"
    assert items["8"]["state"] == "cut" and items["4"]["plan"] and not items["3"]["plan"]
    assert state["behind"] == 2 and state["ahead"] == ["4", "9"] and state["cut"] == ["8"]
    assert items["4"]["must"] and items["3.5"]["star"] and items["3"]["time"] == "15"


def test_ahead_of_plan_is_negative():
    state = timeline.build(ONE, guide.part_of(ONE), 60, "3.1")
    assert state["behind"] == -12 and state["plan"] == "0"


def test_unknown_current_shows_plan_only():
    state = timeline.build(ONE, guide.part_of(ONE), 5 * 60, "")
    assert state["current"] == "" and state["plan"] == "2" and all(i["state"] == "ahead" for i in state["items"])


def test_second_part_and_deadline_label():
    state = timeline.build(TWO, guide.part_of(TWO, "ч2"), 0, "ч2-вход")
    assert [i["id"] for i in state["items"]][:2] == ["ч2-вход", "ч2-5"]
    first = timeline.build(TWO, guide.part_of(TWO, "ч1"), 0, "0")
    assert by_id(first)["3.6"]["time"] == "к 12-й"


def test_block_card_has_questions_with_alternatives():
    card = timeline.block_card(ONE, "2.1")
    assert card["questions"] == [{"text": "За что ты платишь, чтобы приходили клиенты?", "label": "",
                                  "alts": ["Кому или за что платишь?"]}]
    assert card["traps"] == ["Копать начинай с самой большой траты."] and timeline.block_card(ONE, "99") is None


def test_block_without_time_is_never_behind():
    state = timeline.build(ONE, guide.part_of(ONE), 40 * 60, "8")
    assert state["current"] == "8" and state["behind"] == 0
