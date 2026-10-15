from pathlib import Path

import pytest

from copilot import context

FIXTURES = Path(__file__).with_name("fixtures")


def test_context_with_guide_file(tmp_path):
    extra = tmp_path / "цель.md"
    extra.write_text("Бизнес-цель: проверить гипотезу.")
    path, parsed = context.build(tmp_path, str(FIXTURES / "guide-one-call.md"), [str(extra)], no_defaults=True)
    text = path.read_text()
    assert text.startswith("# цель.md\n\nБизнес-цель") and "\n\n---\n\n# guide-one-call.md\n\n" in text
    assert parsed.blocks and (tmp_path / "guide.json").exists()


def test_guide_that_does_not_parse_stops_the_call(tmp_path):
    bad = tmp_path / "ошибка.md"
    bad.write_text("Error: MCP tool response exceeds maximum allowed tokens")
    with pytest.raises(context.NoGuide, match="ни одного блока"):
        context.build(tmp_path / "call", str(bad), no_defaults=True)


def test_no_context_at_all_stops_the_call(tmp_path):
    with pytest.raises(context.NoGuide, match="нет контекста"):
        context.build(tmp_path, None, [], no_defaults=True)
