"""Шаг 1: страница Notion → guide.notion.md и guide.notion.json.

Страница берётся через Notion API целиком в enhanced markdown (GET /v1/pages/{id}/markdown).
Если страница пришла не полностью или с ошибкой, экспорт останавливается: звонок без гайда
лучше начать осознанно, чем с сообщением об ошибке вместо гайда (см. docs/architecture.md, П1).

Токен внутренней интеграции (только чтение): Keychain, сервис interview-copilot-notion,
или переменная NOTION_TOKEN.
"""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
KEYCHAIN_SERVICE = "interview-copilot-notion"
UNKNOWN = re.compile(r"<unknown\b[^>]*/?>")


class ExportError(Exception):
    """Экспорт не удался — звонок с этим гайдом начинать нельзя."""


def page_id(link):
    """Ссылка на страницу Notion или её id → id в виде 32 шестнадцатеричных символов."""
    path = re.sub(r"[?#].*$", "", link.strip())
    found = re.findall(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path, re.I)
    if not found:
        raise ExportError(f"в ссылке нет id страницы Notion: {link}")
    return found[-1].replace("-", "").lower()


def token():
    if os.environ.get("NOTION_TOKEN"):
        return os.environ["NOTION_TOKEN"]
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True)
    if found.returncode != 0 or not found.stdout.strip():
        raise ExportError(f"нет токена Notion: положи его в Keychain (сервис {KEYCHAIN_SERVICE}) или в NOTION_TOKEN")
    return found.stdout.strip()


class Client:
    """GET к Notion API. В тестах подменяется заглушкой с тем же методом get."""

    def __init__(self, secret):
        self.secret = secret

    def get(self, path):
        request = urllib.request.Request(f"{API}{path}", headers={
            "Authorization": f"Bearer {self.secret}", "Notion-Version": VERSION})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                body = error.read().decode(errors="replace")
                if error.code == 429 and attempt < 3:
                    time.sleep(float(error.headers.get("Retry-After") or 1))
                    continue
                try:
                    message = json.loads(body).get("message", body)
                except ValueError:
                    message = body
                raise ExportError(f"Notion ответил {error.code} на {path}: {message}{HINTS.get(error.code, '')}") from None
            except OSError as error:
                raise ExportError(f"Notion недоступен ({path}): {error}") from None
        raise ExportError(f"Notion ограничил частоту запросов: {path}")


HINTS = {
    401: " — токен неверный или отозван",
    403: " — у интеграции нет права читать содержимое",
    404: " — страницы нет или она не подключена к интеграции (… → Connections)",
}


@dataclass
class Page:
    id: str
    title: str
    edited: str
    markdown: str
    fetched: str

    @property
    def meta(self):
        data = self.markdown.encode()
        return {"page_id": self.id, "title": self.title, "edited": self.edited, "fetched": self.fetched,
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "api_version": VERSION}


def title_of(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return ""


def fetch(client, link, allow_unknown=False):
    """Скачивает страницу целиком. Всё, что не загрузилось, — ExportError со списком блоков."""
    pid = page_id(link)
    info = client.get(f"/pages/{pid}")
    body = client.get(f"/pages/{pid}/markdown")
    markdown = body.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise ExportError(f"Notion вернул пустую страницу: {link}")
    ids = list(body.get("unknown_block_ids") or [])
    if body.get("truncated") and not ids:
        raise ExportError("Notion обрезал страницу и не сказал, какие блоки пропущены — гайд неполный")
    markdown, unresolved = fill_unknown(client, markdown, ids)
    # Блок без тега на странице — потерянный кусок гайда: стоп всегда.
    # Тег <unknown> на месте — закладка или встраивание: стоп, если явно не разрешено.
    lost = [block for block, tag in unresolved if tag is None]
    left = [] if allow_unknown else UNKNOWN.findall(markdown)
    if lost or left:
        lines = [f"  {block} (содержимое не загрузилось)" for block in lost] + [f"  {tag}" for tag in left]
        raise ExportError("страница загрузилась не целиком:\n" + "\n".join(lines)
                          + ("\nесли это закладки или встраивания и они не нужны — запусти с --allow-unknown" if left and not lost else ""))
    return Page(id=pid, title=title_of(info), edited=info.get("last_edited_time", ""), markdown=markdown,
                fetched=time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def fill_unknown(client, markdown, ids):
    """Дочитывает пропущенные блоки и ставит их на место тегов <unknown url="…<id>">.

    Возвращает markdown и пары (id, тег или None) для блоков, которые дочитать не удалось."""
    unresolved = []
    for block in ids:
        key = block.replace("-", "")
        tag = next((t for t in UNKNOWN.findall(markdown) if key in t.replace("-", "")), None)
        try:
            part = client.get(f"/pages/{key}/markdown")
        except ExportError:
            unresolved.append((block, tag))
            continue
        if tag is None or part.get("truncated") or part.get("unknown_block_ids") or not part.get("markdown"):
            unresolved.append((block, tag))
            continue
        markdown = markdown.replace(tag, part["markdown"], 1)
    return markdown, unresolved


def save(page, folder):
    """Пишет guide.notion.md (страница без правок) и guide.notion.json (откуда и когда)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "guide.notion.md").write_text(page.markdown)
    (folder / "guide.notion.json").write_text(json.dumps(page.meta, ensure_ascii=False, indent=2) + "\n")
    return folder / "guide.notion.md"


def export(link, folder, allow_unknown=False, client=None):
    page = fetch(client or Client(token()), link, allow_unknown)
    return page, save(page, folder)
