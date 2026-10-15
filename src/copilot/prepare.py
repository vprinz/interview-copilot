"""Шаги 1–2 до звонка: источник гайда (ссылка на Notion или файл) → файлы в папке звонка и Guide."""
import hashlib
import re
import shutil
from pathlib import Path

from copilot import guide, notion


def is_link(source):
    return source.startswith(("http://", "https://")) or bool(re.fullmatch(r"[0-9a-f-]{32,36}", source))


def prepare(source, folder, allow_unknown=False):
    """Шаги 1–2: источник гайда → файлы в folder. Возвращает Guide; ExportError — экспорт не удался."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if is_link(source):
        page, path = notion.export(source, folder, allow_unknown)
        meta = {"kind": "notion", "url": source, **page.meta}
    else:
        path = Path(source).expanduser()
        if not path.is_file():
            raise notion.ExportError(f"нет файла гайда: {path}")
        copy = folder / "guide.md"
        if path.resolve() != copy.resolve():
            shutil.copyfile(path, copy)
        data = path.read_bytes()
        meta = {"kind": "file", "path": str(path), "title": path.stem, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        path = copy
    parsed = guide.parse(path.read_text(), meta)
    guide.save(parsed, folder)
    return parsed
