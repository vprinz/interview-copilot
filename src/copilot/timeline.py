"""Таймлайн панели: блоки части звонка, где мы по факту (id от модели) и где должны быть по часам.

План по часам строится из гайда: у верхних блоков части время идёт подряд (берётся верхняя граница:
«3–5 мин» → 5), «к N-й мин» из таблицы времени задаёт конец блока напрямую, блок «вместе с 3.6» делит
окно с 3.6, подблоки (3.1…3.10) живут в окне своего раздела.
"""
from copilot import guide as guide_module


def windows(parsed, part):
    """id блока → (начало, конец) в минутах от начала части."""
    result, cursor = {}, 0
    top = [k for k in part.blocks if not parsed.blocks[k].parent]
    shared = {}
    for key in top:
        block = parsed.blocks[key]
        for other in block.shared_with:
            shared[other] = key
    for key in top:
        block = parsed.blocks[key]
        number = block.number
        if number in shared and shared[number] in result:
            result[key] = result[shared[number]]
            continue
        if block.deadline_minute is not None:
            end = max(cursor, block.deadline_minute)
        else:
            end = cursor + (block.minutes["max"] if block.minutes else 0)
        result[key] = (cursor, end)
        cursor = end
    for key in part.blocks:
        parent = parsed.blocks[key].parent
        if parent and parent in result:
            result[key] = result[parent]
    return result


def top_of(parsed, key):
    while key and parsed.blocks[key].parent:
        key = parsed.blocks[key].parent
    return key


def build(parsed, part, elapsed_seconds, current, cut_ids=(), ahead_ids=()):
    """Состояние таймлайна для панели. current — id блока от модели (или "")."""
    minute = elapsed_seconds / 60
    spans = windows(parsed, part)
    order = part.blocks
    current = current if current in order else ""
    current_top = top_of(parsed, current) if current else ""
    tops = [k for k in order if not parsed.blocks[k].parent]
    plan = next((k for k in tops if spans[k][0] <= minute < spans[k][1]), None)
    if plan is None and tops and minute >= spans[tops[-1]][1]:
        plan = tops[-1]
    behind = 0
    # У блока без времени («если остаётся время») окно нулевое — отставать от него нечего.
    if current_top and current_top in spans and spans[current_top][0] < spans[current_top][1]:
        start, end = spans[current_top]
        behind = round(minute - end) if minute > end else -round(start - minute) if minute < start else 0
    position = order.index(current) if current else -1
    items = []
    for index, key in enumerate(order):
        block = parsed.blocks[key]
        if key == current or key == current_top:
            state = "current"
        elif key in cut_ids:
            state = "cut"
        elif index < position and (top_of(parsed, key) != current_top or parsed.blocks[key].parent):
            state = "done"
        else:
            state = "ahead"
        items.append({
            "id": key, "number": block.number, "title": block.title, "sub": bool(block.parent),
            "time": f"к {block.deadline_minute}-й" if block.deadline_minute is not None
                    else guide_module.span(block.minutes) if block.minutes else "",
            "star": block.star, "must": key in parsed.never_cut, "cut_mark": block.cut,
            "state": state, "plan": key == plan and plan != current_top,
            "minutes": (block.minutes or {}).get("max") or 0,
        })
    return {
        "part": part.title, "items": items, "current": current, "plan": plan or "",
        "behind": behind,
        "ahead": [k for k in ahead_ids if k in order],
        "cut": [k for k in cut_ids if k in order],
    }


def block_card(parsed, key):
    """Подсказка из гайда для широкого окна: вопросы, добивки и ловушки текущего блока."""
    block = parsed.blocks.get(key)
    if block is None:
        return None
    questions = []
    for item in block.items:
        if item.kind == "question":
            questions.append({"text": item.text, "label": item.label, "alts": []})
        elif item.kind == "alt" and questions:
            questions[-1]["alts"].append(item.text)
    return {"id": key, "title": block.title, "questions": questions,
            "checks": [i.text for i in block.items if i.kind == "check"],
            "traps": [i.text for i in block.items if i.kind == "trap"]}
