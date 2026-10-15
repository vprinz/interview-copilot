import json
from pathlib import Path

from copilot import cli, prepare

FIXTURES = Path(__file__).with_name("fixtures")


def test_guide_from_file(tmp_path, capsys):
    code = cli.guide_command([str(FIXTURES / "guide-one-call.md"), "--out", str(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["guide.json", "guide.md", "guide.report.txt"]
    data = json.loads((tmp_path / "guide.json").read_text())
    assert data["source"]["kind"] == "file" and data["title"] == "guide-one-call"
    assert "[3.5] триггер" in capsys.readouterr().out


def test_error_text_instead_of_guide_stops(tmp_path, capsys):
    bad = tmp_path / "bad.md"
    bad.write_text("Error: MCP tool response exceeds maximum allowed tokens")
    assert cli.guide_command([str(bad), "--out", str(tmp_path / "out")]) == 1
    assert "не начинать" in capsys.readouterr().out


def test_missing_file_stops(tmp_path, capsys):
    assert cli.guide_command([str(tmp_path / "нет.md"), "--out", str(tmp_path)]) == 2
    assert "СТОП" in capsys.readouterr().err


def test_link_detection():
    assert prepare.is_link("https://app.notion.com/p/x-3ec56be1403e8133a6afd32ba67b2764")
    assert prepare.is_link("3ec56be1403e8133a6afd32ba67b2764")
    assert not prepare.is_link("recordings/guide.md")
