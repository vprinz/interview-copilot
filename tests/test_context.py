from pathlib import Path

import pytest

from copilot import context

FIXTURES = Path(__file__).with_name("fixtures")


def test_context_with_guide_file(tmp_path):
    extra = tmp_path / "цель.md"
    extra.write_text("Бизнес-цель: проверить гипотезу.")
    path, parsed = context.build(tmp_path, str(FIXTURES / "guide-one-call.md"), [str(extra)], no_defaults=True)
    text = path.read_text()
    assert text.startswith("# цель.md\n\nБизнес-цель") and "\n\n---\n\n# Гайд под респондента — по блокам\n\n" in text
    assert "## [3] Детально изучаем задачу · 15 мин" in text and "### [3.5] триггер · ⭐" in text
    assert parsed.blocks and (tmp_path / "guide.json").exists()


def test_guide_that_does_not_parse_stops_the_call(tmp_path):
    bad = tmp_path / "ошибка.md"
    bad.write_text("Error: MCP tool response exceeds maximum allowed tokens")
    with pytest.raises(context.NoGuide, match="ни одного блока"):
        context.build(tmp_path / "call", str(bad), no_defaults=True)


def test_no_context_at_all_stops_the_call(tmp_path):
    with pytest.raises(context.NoGuide, match="нет контекста"):
        context.build(tmp_path, None, [], no_defaults=True)


def test_every_parsed_line_reaches_the_session():
    from copilot import guide
    parsed = guide.parse((FIXTURES / "guide-two-calls.mcp.md").read_text())
    text = guide.render(parsed)
    items = [i for b in parsed.blocks.values() for i in b.items + [x for r in b.records for x in r.items]]
    items += [i for n in parsed.notes for i in n.items] + parsed.traps
    missing = [i.text for i in items if i.text not in text]
    assert missing == []
    assert "# Часть 2 — 30–40 минут" in text and "## [ч2-вход] Вход · 2 мин" in text and "к 12-й мин" in text


def test_kickoff_lists_blocks_of_the_part(tmp_path):
    from copilot import guide
    parsed = guide.parse((FIXTURES / "guide-one-call.md").read_text())
    text = context.kickoff(context.ROOT / "recordings/x/context.md", 50, parsed)
    assert "- [3] Детально изучаем задачу · 15 мин\n  - [3.1] критерии успеха · ⭐" in text
    assert "резать в таком порядке: 8 Соседние задачи, 3.2 бюджет" in text
    assert "Не резать никогда: 3.1 критерии успеха, 3.5 триггер, 4 Числа против альтернатив" in text
    assert "{" + "blocks}" not in text and "{part}" not in text
    two = guide.parse((FIXTURES / "guide-two-calls.mcp.md").read_text())
    second = context.kickoff(context.ROOT / "recordings/x/context.md", 40, two, "ч2")
    assert "Блоки этого звонка (Часть 2 — 30–40 минут)" in second and "[ч2-закрытие]" in second and "[3.1]" not in second


def test_kickoff_without_guide_uses_canon():
    text = context.kickoff(context.ROOT / "recordings/x/context.md", 60)
    assert "- [4] Прокопка · 30–40 мин · ⭐" in text


def test_notes_stay_in_their_part():
    from copilot import guide
    text = guide.render(guide.parse((FIXTURES / "guide-two-calls.mcp.md").read_text()))
    part2, between, first_block_part2 = text.index("# Часть 2"), text.index("# Между созвонами"), text.index("## [ч2-вход]")
    assert part2 < text.index("За 8 минут до конца") < first_block_part2
    assert part2 < text.index("⏱ **40 минут:**") < first_block_part2
    assert between < text.index("Выписать места, где осталась оценка") < part2


def test_timeline_table_reaches_the_session():
    from copilot import guide
    text = guide.render(guide.parse((FIXTURES / "guide-two-calls.mcp.md").read_text()))
    assert "- к 12-й мин: 3.1 критерии успеха и 3.6 «чтобы что»" in text
