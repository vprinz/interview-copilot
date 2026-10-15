"""Шаг 3: что прочитает сессия — context.md и стартовое сообщение kickoff.md.

Контекст интервью: цель и гипотезы (product.md, research/design.md из ~/projects/curator-product),
дополнительные файлы --context и гайд под респондента. Гайд проходит шаги 1–2 (prepare.py):
если он не скачался целиком или не разобрался, звонок не начинается.
"""
import sys
from pathlib import Path

from copilot import contract, guide, notion
from copilot.paths import PACKAGE, ROOT
from copilot.prepare import is_link, prepare

DEFAULT_CONTEXT = [Path.home() / "projects/curator-product/product.md",
                   Path.home() / "projects/curator-product/research/design.md"]
KICKOFF = PACKAGE / "prompts/kickoff.md"


class NoGuide(Exception):
    """Гайд не получен или не разобрался — звонок с ним не начинать."""


def build(folder, guide_source=None, extra=(), no_defaults=False, allow_unknown=False):
    """Пишет folder/context.md. Возвращает (путь, разобранный гайд или None)."""
    sources = [] if no_defaults else [p for p in DEFAULT_CONTEXT if p.exists()]
    parts = [f"# {path.name}\n\n{path.read_text()}" for path in sources + [Path(p).expanduser() for p in extra]]
    parsed = None
    if guide_source:
        if is_link(guide_source):
            print(f"читаю гайд из Notion: {guide_source}", file=sys.stderr)
        try:
            parsed = prepare(guide_source, folder, allow_unknown)
        except notion.ExportError as error:
            raise NoGuide(str(error)) from None
        if parsed.errors:
            raise NoGuide("гайд не разобрался:\n" + "\n".join(f"  {e}" for e in parsed.errors)
                          + f"\nсводка: {folder / 'guide.report.txt'}")
        if parsed.source["kind"] == "notion":
            print(f"гайд: {parsed.title} · блоков {len(parsed.blocks)} · изменён {parsed.source['edited']}", file=sys.stderr)
        # Сессия видит гайд таким, каким его разобрал guide.py: с id блоков в заголовках.
        # Что ни одна строка не потерялась, проверяет сам разбор (guide.check).
        parts.append(f"# Гайд под респондента — по блокам\n\n{guide.render(parsed)}")
    if not parts:
        raise NoGuide("нет контекста интервью: укажи --guide или --context")
    if not guide_source:
        print("внимание: гайд под респондента не задан (--guide) — подсказки пойдут только от цели и гипотез", file=sys.stderr)
    path = folder / "context.md"
    path.write_text("\n\n---\n\n".join(parts))
    return path, parsed


def kickoff(context_path, minutes, parsed=None, part_id=None):
    """Стартовое сообщение сессии: шаблон prompts/kickoff.md, формат ответа из контракта и блоки гайда.

    Без гайда под респондента — блоки по канону (canon-guide.md)."""
    parsed = parsed or guide.canon()
    part, blocks = guide.summary(parsed, part_id)
    titles = {key: f"{key} {block.title}" for key, block in parsed.blocks.items()}
    text = KICKOFF.read_text()
    return (text.replace("{format}", contract.FORMAT)
            .replace("{blocks}", blocks)
            .replace("{part}", part.title or parsed.title or "весь звонок")
            .replace("{cut_order}", ", ".join(titles[k] for k in parsed.cut_order) or "не задан в гайде")
            .replace("{never_cut}", ", ".join(titles[k] for k in parsed.never_cut) or "не задано в гайде")
            .replace("{context}", str(Path(context_path).resolve().relative_to(ROOT)))
            .replace("{minutes}", str(minutes)))
