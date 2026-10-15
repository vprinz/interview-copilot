"""Копайлот на живом интервью: транскрипт → подсказки nmt-chat → панель рядом со звонком.

    scripts/copilot.py --guide https://app.notion.com/p/…      # гайд под респондента из Notion
    scripts/copilot.py --guide guide.md --headphones --minutes 45
    scripts/copilot.py --no-defaults --context recordings/step2/context.md --mixed \\
        --replay-sys recordings/work/andrey-16k.wav --speed 4   # прогон по записи
    scripts/copilot.py guide <ссылка или файл>                 # только проверить гайд до звонка

Цель и гипотезы берутся из product.md и research/design.md (~/projects/curator-product).
Всё по звонку лежит в recordings/live/<дата_время>/: гайд, контекст, стартовое сообщение,
транскрипт, журнал панели. Устройство — docs/architecture.md.
"""
import argparse
import sys
import time
from pathlib import Path

from copilot import guide, notion
from copilot.paths import ROOT
from copilot.prepare import prepare

GUIDE_HELP = """Проверить гайд до звонка: скачать (Notion) или прочитать (файл), разобрать на блоки, показать сводку.
Файлы — в recordings/guides/<дата_время>/: guide.notion.md (или guide.md), guide.notion.json,
guide.json, guide.report.txt. Код выхода 0 — гайд годен, 1 — ошибки разбора, 2 — экспорт не удался."""


def guide_command(argv):
    parser = argparse.ArgumentParser(prog="copilot.py guide", description=GUIDE_HELP,
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


def run_command(argv):
    parser = argparse.ArgumentParser(prog="copilot.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guide", help="гайд под респондента: ссылка на страницу Notion или файл .md")
    parser.add_argument("--allow-unknown", action="store_true", help="не останавливаться на закладках и встраиваниях в гайде")
    parser.add_argument("--context", action="append", default=[], help="ещё файл с контекстом интервью")
    parser.add_argument("--no-defaults", action="store_true", help="не подмешивать product.md и design.md")
    parser.add_argument("--minutes", type=int, default=60, help="на сколько минут рассчитан звонок")
    parser.add_argument("--interval", type=float, default=30, help="как часто обновлять панель, секунд")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-window", action="store_true", help="не открывать окно панели, только страницу в браузере")
    parser.add_argument("--headphones", action="store_true", help="я в наушниках: микрофон не слышит респондента")
    parser.add_argument("--keep-audio", action="store_true", help="сохранить звук обоих каналов рядом с транскриптом")
    parser.add_argument("--mixed", action="store_true", help="запись одной сведённой дорожкой: не помечать говорящих")
    parser.add_argument("--replay-sys", help="WAV вместо системного звука")
    parser.add_argument("--replay-mic", help="WAV вместо микрофона")
    parser.add_argument("--replay-from", type=float, default=0)
    parser.add_argument("--replay-seconds", type=float, default=1e9)
    parser.add_argument("--speed", type=float, default=1.0, help="скорость прогона записи; 1 — как вживую")
    from copilot import app
    return app.run(parser.parse_args(argv))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["guide"]:
        return guide_command(argv[1:])
    return run_command(argv)


if __name__ == "__main__":
    sys.exit(main())
