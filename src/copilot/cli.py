"""Командная строка копайлота. Пока одна подкоманда — проверить гайд до звонка:

    scripts/copilot.py guide https://app.notion.com/p/…     # скачать из Notion, разобрать, показать сводку
    scripts/copilot.py guide guide.md                       # то же для файла

Файлы — в recordings/guides/<дата_время>/: guide.notion.md (или guide.md), guide.notion.json,
guide.json, guide.report.txt. Код выхода 0 — гайд годен, 1 — ошибки разбора, 2 — экспорт не удался.
"""
import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

from copilot import guide, notion

ROOT = Path(__file__).resolve().parents[2]


def is_link(source):
    return source.startswith(("http://", "https://")) or bool(notion.re.fullmatch(r"[0-9a-f-]{32,36}", source))


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


def guide_command(argv):
    parser = argparse.ArgumentParser(prog="copilot.py guide", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="ссылка на страницу Notion, её id или файл .md")
    parser.add_argument("--out", help="папка для файлов (по умолчанию recordings/guides/<дата_время>)")
    parser.add_argument("--allow-unknown", action="store_true", help="не останавливаться на закладках и встраиваниях")
    args = parser.parse_args(argv)
    folder = Path(args.out) if args.out else ROOT / "recordings/guides" / time.strftime("%Y-%m-%d_%H%M%S")
    try:
        parsed = prepare(args.source, folder, args.allow_unknown)
    except notion.ExportError as error:
        print(f"\nСТОП: гайд не получен.\n{error}", file=sys.stderr)
        return 2
    print(guide.report(parsed))
    print(f"\nфайлы: {folder}")
    return 1 if parsed.errors else 0


if __name__ == "__main__":
    sys.exit(guide_command(sys.argv[1:]))
