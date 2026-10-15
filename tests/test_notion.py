import json

import pytest

from copilot import notion

PID = "3ec56be1403e8133a6afd32ba67b2764"
PAGE = {"properties": {"title": {"type": "title", "title": [{"plain_text": "Гайд — тест"}]}},
        "last_edited_time": "2026-10-15T17:25:00.000Z"}
BLOCK = "1111aaaa2222bbbb3333cccc4444dddd"


class Fake:
    """Отвечает на пути API из словаря; ExportError в словаре — как ошибка HTTP."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        answer = self.routes[path]
        if isinstance(answer, Exception):
            raise answer
        return answer


def routes(markdown, **extra):
    return {f"/pages/{PID}": PAGE, f"/pages/{PID}/markdown": {"markdown": markdown, "truncated": False, "unknown_block_ids": [], **extra}}


@pytest.mark.parametrize("link", [
    "https://app.notion.com/p/3ec56be1403e8133a6afd32ba67b2764",
    "https://app.notion.com/p/2026-10-13-primer-gaida-3ec56be1403e8133a6afd32ba67b2764?source=copy_link",
    "https://www.notion.so/team/Guide-3ec56be1403e8133a6afd32ba67b2764#abc",
    "3ec56be1-403e-8133-a6af-d32ba67b2764",
])
def test_page_id_from_any_link(link):
    assert notion.page_id(link) == PID


def test_page_id_missing_is_loud():
    with pytest.raises(notion.ExportError, match="нет id"):
        notion.page_id("https://app.notion.com/p/просто-страница")


def test_whole_page(tmp_path):
    page = notion.fetch(Fake(routes("# 1. Блок\n> 📖 «Вопрос?»")), PID)
    assert page.title == "Гайд — тест" and page.markdown.startswith("# 1. Блок")
    notion.save(page, tmp_path)
    assert (tmp_path / "guide.notion.md").read_text() == page.markdown
    meta = json.loads((tmp_path / "guide.notion.json").read_text())
    assert meta["page_id"] == PID and meta["bytes"] == len(page.markdown.encode()) and len(meta["sha256"]) == 64


def test_empty_page_is_loud():
    with pytest.raises(notion.ExportError, match="пустую"):
        notion.fetch(Fake(routes("  \n")), PID)


def test_http_error_is_loud():
    fake = Fake({f"/pages/{PID}": notion.ExportError("Notion ответил 404 …")})
    with pytest.raises(notion.ExportError, match="404"):
        notion.fetch(fake, PID)


def test_truncated_without_ids_is_loud():
    with pytest.raises(notion.ExportError, match="обрезал"):
        notion.fetch(Fake(routes("# 1. Блок", truncated=True)), PID)


def test_unknown_block_is_filled_in_place():
    tag = f'<unknown url="https://www.notion.so/x#{BLOCK}" alt="column_list"/>'
    fake = Fake(routes(f"до\n{tag}\nпосле", truncated=True, unknown_block_ids=[BLOCK]))
    fake.routes[f"/pages/{BLOCK}/markdown"] = {"markdown": "середина", "truncated": False, "unknown_block_ids": []}
    assert notion.fetch(fake, PID).markdown == "до\nсередина\nпосле"


def test_unknown_block_that_did_not_load_is_loud():
    tag = f'<unknown url="https://www.notion.so/x#{BLOCK}" alt="toggle"/>'
    fake = Fake(routes(f"до\n{tag}", unknown_block_ids=[BLOCK]))
    fake.routes[f"/pages/{BLOCK}/markdown"] = notion.ExportError("404")
    with pytest.raises(notion.ExportError, match="не целиком"):
        notion.fetch(fake, PID)


def test_lost_block_without_tag_is_loud_even_when_unknown_allowed():
    fake = Fake(routes("до", truncated=True, unknown_block_ids=[BLOCK]))
    fake.routes[f"/pages/{BLOCK}/markdown"] = {"markdown": "кусок", "truncated": False, "unknown_block_ids": []}
    with pytest.raises(notion.ExportError, match="не загрузилось"):
        notion.fetch(fake, PID, allow_unknown=True)


def test_bookmark_stops_unless_allowed():
    tag = f'<unknown url="https://www.notion.so/x#{BLOCK}" alt="bookmark"/>'
    fake = Fake(routes(f"текст\n{tag}", unknown_block_ids=[BLOCK]))
    fake.routes[f"/pages/{BLOCK}/markdown"] = {"markdown": tag, "truncated": False, "unknown_block_ids": [BLOCK]}
    with pytest.raises(notion.ExportError, match="--allow-unknown"):
        notion.fetch(fake, PID)
    assert tag in notion.fetch(fake, PID, allow_unknown=True).markdown
