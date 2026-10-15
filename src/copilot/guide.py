"""Шаг 2: гайд интервью (enhanced markdown из Notion или файл .md) → guide.json.

Гайд пишется в Notion по шаблону: части звонка (# Часть 1 — 30 минут), разделы (# 3. …),
блоки (## 3.5 [триггер] ⭐ — 5 мин), в блоке слева — что спрашиваю (> 📖 вопросы, *Иначе:*,
✅ добивки, ⚠️ ловушки, серый текст — пояснения), справа под зелёным заголовком — что записываю.
Правила разбора и схема — docs/architecture.md, раздел 3.

Разбор ничего не выбрасывает молча: каждая непустая строка исходника попадает в какое-то поле,
а то, что не подошло ни под одно правило, перечислено в warnings и в отчёте.
"""
import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = 1
CANON = Path(__file__).with_name("canon-guide.md")

TAG = re.compile(r"<(/?)([a-z][a-z-]*)\b([^>]*?)(/?)>")
ATTR = re.compile(r'([a-z-]+)="([^"]*)"')
SPAN = re.compile(r'<span color="([a-z_]+)">(.*?)</span>', re.S)
KNOWN_INLINE = {"span", "br", "mention-date", "mention-page", "mention-user", "mention-database"}
NUMBER = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?[а-я]?)(?:\.\s+|\s+)(.+)$")
PART = re.compile(r"^(часть\s+(\d+)|между созвонами|после интервью)", re.I)
MINUTES = re.compile(r"(?:(до)\s*)?~?\s*(\d+)(?:\s*[–-]\s*(\d+))?\s*мин", re.I)
MUST = re.compile(r"не резать|не пропускать|обязательно", re.I)
STAR, CUT, WARN = "⭐", "✂", "⚠"


# --- результат разбора ---

@dataclass
class Item:
    kind: str           # question | alt | check | trap | hint | text | quote | heading | field | table
    text: str
    line: int
    label: str = ""     # «4.1» или «[до]» у вопроса
    star: bool = False
    callout: str = ""   # иконка callout'а, внутри которого строка
    collapsed: bool = False  # строка внутри тоггла
    rows: list = field(default_factory=list)


@dataclass
class Record:
    """Правая колонка: что записываю (зелёный заголовок) и что уже записано."""
    title: str
    line: int
    items: list = field(default_factory=list)


@dataclass
class Block:
    id: str
    number: str
    title: str
    line: int
    kind: str = "block"            # section — раздел «# 3. …», block — блок «## 3.5 …»
    part: str = ""
    parent: str = ""
    children: list = field(default_factory=list)
    minutes: dict | None = None    # {"min": 3, "max": 5}; min = null у «до 10 мин»
    deadline_minute: int | None = None
    shared_with: list = field(default_factory=list)
    star: bool = False
    cut: bool = False
    must: bool = False
    warning: str = ""
    note: str = ""                 # остаток заголовка: «по таймеру», «если остаётся время»
    collapsed: bool = False
    items: list = field(default_factory=list)
    records: list = field(default_factory=list)


@dataclass
class Part:
    id: str
    kind: str                      # call | break | after
    title: str
    line: int
    minutes: dict | None = None
    blocks: list = field(default_factory=list)


@dataclass
class Note:
    """Всё, что не блок: callout'ы шапки, карточки «собрать после интервью» и т. п."""
    title: str
    line: int
    icon: str = ""
    after: str = ""                # id блока, после которого стоит заметка
    items: list = field(default_factory=list)


@dataclass
class Guide:
    title: str = ""
    source: dict = field(default_factory=dict)
    minutes: dict | None = None
    parts: list = field(default_factory=list)
    blocks: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)     # таблица «к какой минуте»
    cut_order: list = field(default_factory=list)
    never_cut: list = field(default_factory=list)
    traps: list = field(default_factory=list)
    stop_list: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    lines: int = 0                 # непустых строк в исходнике
    schema: int = SCHEMA

    def call_blocks(self):
        """Блоки частей-созвонов по порядку (без «между созвонами» и «после интервью»)."""
        calls = {p.id for p in self.parts if p.kind == "call"}
        return [b for b in self.blocks.values() if b.part in calls]


# --- лексер: строки → токены с контекстом (колонка, callout, цвет) ---

@dataclass
class Token:
    kind: str           # heading | line | table | callout | end-callout | unknown
    text: str
    line: int
    level: int = 0
    column: int | None = None
    callout: str = ""
    gray: bool = False
    green: bool = False
    collapsed: bool = False
    rows: list = field(default_factory=list)
    lines: list = field(default_factory=list)


def clean(text):
    """Строка Notion → читаемый текст: без тегов, экранирования и HTML-сущностей."""
    text = re.sub(r"<br\s*/?>", " / ", text)
    text = re.sub(r'<mention-date start="([^"]*)"(?: startTime="([^"]*)")?[^>]*/>',
                  lambda m: m[1] + (f" {m[2]}" if m[2] else ""), text)
    text = re.sub(r'<mention-[a-z]+ [^>]*?(?:title|name)="([^"]*)"[^>]*/>', r"\1", text)
    text = SPAN.sub(r"\2", text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~|>])", r"\1", text)
    return html.unescape(text).strip()


def is_gray(text):
    """Строка целиком серая: вне серых span'ов нет ничего, кроме пробелов и разметки."""
    if '<span color="gray">' not in text:
        return False
    rest = SPAN.sub(lambda m: "" if m[1] == "gray" else m[2], text)
    return not re.sub(r"[\s*_]", "", rest)


def unwrap(text):
    """Ответ MCP-инструмента обёрнут в <page><content>…</content></page>; API отдаёт голый markdown.

    Возвращает (содержимое, номер строки, с которой оно начинается, заголовок страницы или "")."""
    title = ""
    found = re.search(r'<properties>\s*(\{.*?\})\s*</properties>', text, re.S)
    if found:
        try:
            title = json.loads(found[1]).get("title", "")
        except ValueError:
            pass
    start = text.find("<content>")
    if start < 0:
        return text, 1, title
    end = text.rfind("</content>")
    body = text[start + len("<content>"):end if end > start else len(text)]
    if body.startswith("\n"):
        body = body[1:]
        start += 1
    return body, text[:start + len("<content>")].count("\n") + 1, title


def lex(text, first=1):
    tokens, structure = [], set()
    columns, callouts, details = [], [], 0
    table = None
    for no, raw in enumerate(text.split("\n"), start=first):
        line = raw.strip()
        if not line:
            continue
        column = columns[-1] if columns else None
        icon = callouts[-1] if callouts else ""
        if table is not None:
            table.lines.append(no)
            if line.startswith("</table>"):
                tokens.append(table)
                table = None
            elif line == "<tr>":
                table.rows.append([])
            elif line.startswith("<td"):
                if not table.rows:
                    table.rows.append([])
                table.rows[-1].append(clean(re.sub(r"</?td[^>]*>", "", line)))
            elif line == "</tr>":
                pass
            elif table.rows and table.rows[-1]:      # продолжение многострочной ячейки
                table.rows[-1][-1] += " " + clean(re.sub(r"</td>", "", line))
            continue
        opening = TAG.match(line)
        name = opening[2] if opening else ""
        whole = bool(opening) and opening.end() == len(line)
        if name == "table":
            table = Token("table", "", no, column=column, callout=icon, collapsed=details > 0, lines=[no])
            continue
        if name in {"columns", "column", "callout", "details", "page", "content", "ancestor-path", "parent-page", "properties",
                                "empty-block"} and whole:
            structure.add(no)
            closing = opening[1] == "/"
            if name == "columns":
                if closing and columns:
                    columns.pop()
                    tokens.append(Token("end-columns", "", no))
                elif not closing:
                    columns.append(-1)
                    tokens.append(Token("columns", "", no))
            elif name == "column" and not closing and columns:
                columns[-1] += 1
            elif name == "callout":
                if closing and callouts:
                    callouts.pop()
                    tokens.append(Token("end-callout", "", no))
                elif not closing:
                    attrs = dict(ATTR.findall(opening[3]))
                    callouts.append(attrs.get("icon", "•"))
                    tokens.append(Token("callout", attrs.get("color", ""), no, column=column, callout=callouts[-1]))
            elif name == "details":
                details += -1 if closing else 1
            continue
        if line == "---":
            structure.add(no)
            continue
        summary = re.fullmatch(r"<summary>(.*)</summary>", line)
        if summary:
            tokens.append(Token("heading", clean(summary[1]), no, level=3, column=column, callout=icon, collapsed=True))
            continue
        foreign = [m[2] for m in TAG.finditer(line) if m[2] not in KNOWN_INLINE]
        if foreign:
            tokens.append(Token("unknown", line, no, column=column))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)(?:\s*\{toggle=\"true\"\})?$", line)
        if heading:
            body = heading[2]
            green = bool(re.fullmatch(r'<span color="green">.*</span>', body.strip()))
            tokens.append(Token("heading", clean(body), no, level=len(heading[1]), column=column, callout=icon,
                                green=green, gray=is_gray(body), collapsed=details > 0 or "{toggle" in line))
            continue
        tokens.append(Token("line", line, no, column=column, callout=icon, gray=is_gray(line), collapsed=details > 0))
    if table is not None:
        tokens.append(table)
    return tokens, structure


# --- заголовки блоков ---

def parse_minutes(text):
    found = MINUTES.search(text)
    if not found:
        return None, text
    low, high = int(found[2]), int(found[3] or found[2])
    value = {"min": None, "max": low} if found[1] else {"min": low, "max": high}
    return value, (text[:found.start()] + text[found.end():])


def parse_heading(text):
    """«3.1 [критерии успеха] ⭐ — 5 мин вместе с 3.6» → номер, название, время, пометки."""
    numbered = NUMBER.match(text)
    number, rest = (numbered[1], numbered[2]) if numbered else ("", text)
    title, _, tail = rest.partition(" — ")
    star, cut = STAR in text, CUT in text
    warning = ""
    found = re.search(r"⚠️?\s*([^⭐✂—]*)", tail)
    if found:
        warning = found[1].strip(" ,.")
    minutes, tail = parse_minutes(tail)
    shared = re.search(r"вместе с\s+([\d.,\sи]+)", tail)
    shared_with = re.findall(r"\d{1,2}(?:\.\d{1,2})?", shared[1]) if shared else []
    if shared:
        tail = tail.replace(shared[0], "")
    note = re.sub(r"[⭐⚠️✂️]|не резать|не пропускать|обязательно", "", tail)
    if warning:
        note = note.replace(warning, "")
    title = re.sub(r"[⭐⚠️✂️]", "", title).strip()
    title = re.sub(r"^\[(.*)\]$", r"\1", title).strip()
    return {"number": number, "title": title, "minutes": minutes, "star": star, "cut": cut,
            "must": bool(MUST.search(text)), "warning": warning, "shared_with": shared_with,
            "note": re.sub(r"\s+", " ", note).strip(" ,.—")}


def classify(token, in_record=False):
    """Строка блока → Item нужного вида."""
    item = classify_text(token, in_record)
    item.collapsed = token.collapsed
    return item


def classify_text(token, in_record):
    text = token.text
    if token.kind == "heading":
        return Item("heading", text, token.line, callout=token.callout)
    if token.gray:
        return Item("hint", clean(text), token.line, callout=token.callout)
    body = clean(text)
    if in_record:
        return Item("field", body, token.line, callout=token.callout)
    if body.startswith(">"):
        body = body.lstrip("> ").strip()
        if "📖" not in body:
            return Item("quote", body, token.line, callout=token.callout)
        body = body.replace("📖", "").strip()
        label = re.match(r"^\*\*([^*]+)\*\*\s*", body)
        if label:
            body = body[label.end():]
        star = body.startswith(STAR)
        body = body.replace(STAR, "", 1).strip() if star else body
        return Item("question", body.strip("«»").strip(), token.line, label=label[1].strip() if label else "",
                    star=star, callout=token.callout)
    if re.match(r"^\*Иначе:?\*:?", body):
        return Item("alt", re.sub(r"^\*Иначе:?\*:?\s*", "", body).strip("«»"), token.line, callout=token.callout)
    if body.startswith("✅"):
        return Item("check", body.removeprefix("✅").strip(), token.line, callout=token.callout)
    if body.startswith(("⚠️", "⚠", "❌")):
        return Item("trap", body.lstrip("⚠️❌ ").strip(), token.line, callout=token.callout)
    return Item("text", body, token.line, callout=token.callout)


def shared_words(a, b):
    """Сколько общих слов от пяти букв (сравниваются первые пять) у двух названий."""
    def stems(text):
        return {w[:5] for w in re.findall(r"[а-яёa-z]{5,}", text.lower())}
    return len(stems(a) & stems(b))


def slug(text):
    words = re.findall(r"[а-яёa-z0-9]+", text.lower())
    return "-".join(words[:2]) or "блок"


# --- сборка ---

class Builder:
    def __init__(self):
        self.guide = Guide()
        self.order = []            # блоки по порядку, пока id не окончательные
        self.part = None
        self.section = None
        self.block = None
        self.note = None
        self.record = None
        self.group = []            # блоки, начатые в левой колонке текущих <columns>
        self.group_records = []    # зелёные заголовки правой колонки — хозяин назначается при </columns>
        self.group_owner = None    # блок, в котором открылись колонки
        self.in_columns = False
        self.cut_lines = []
        self.timeline_rows = []
        self.stop_mode = False
        self.placed = set()

    def place(self, *lines):
        self.placed.update(lines)

    def target_note(self, title, line, icon=""):
        self.note = Note(title, line, icon=icon, after=self.order[-1] if self.order else "")
        self.guide.notes.append(self.note)
        self.block = self.record = None
        return self.note

    def start_part(self, token):
        found = PART.match(token.text)
        kind = "call" if found[2] else "break" if "между" in found[1].lower() else "after"
        part = Part(id=f"ч{found[2]}" if found[2] else slug(token.text), kind=kind, title=token.text, line=token.line,
                    minutes=parse_minutes(token.text)[0])
        self.guide.parts.append(part)
        self.part, self.section, self.block, self.note, self.record = part, None, None, None, None

    def start_block(self, token, kind):
        head = parse_heading(token.text)
        block = Block(id="", number=head["number"], title=head["title"], line=token.line, kind=kind,
                      minutes=head["minutes"], shared_with=head["shared_with"], star=head["star"], cut=head["cut"],
                      must=head["must"], warning=head["warning"], note=head["note"], collapsed=token.collapsed)
        if self.part is None or self.part.kind != "call" and not any(p.kind == "call" for p in self.guide.parts):
            # Блоки до первой «# Часть …» (или гайд без частей) — один звонок.
            implicit = Part(id="ч1", kind="call", title="Звонок", line=token.line, minutes=self.guide.minutes)
            self.guide.parts.insert(0, implicit)
            self.part = implicit
        block.part = self.part.id
        if kind == "block" and self.section and block.number.startswith(self.section.number + "."):
            block.parent = self.section
        self.order.append(block)
        self.block, self.note, self.record = block, None, None
        if kind == "section":
            self.section = block
        elif token.column is not None:
            self.group.append(block)

    def start_record(self, token):
        self.record = Record(token.text, token.line)
        if self.in_columns:
            self.group_records.append(self.record)
        elif self.block is not None:
            self.block.records.append(self.record)
        else:
            self.record = None
            self.target_note(token.text, token.line)

    def open_columns(self):
        self.group, self.group_records, self.group_owner, self.record = [], [], self.block, None
        self.in_columns = True

    def close_columns(self):
        """Зелёные заголовки справа → блоки слева: по совпадению слов в названии, при равном числе — по порядку,
        иначе — первому блоку группы (или блоку, в котором открылись колонки)."""
        blocks = self.group or ([self.group_owner] if self.group_owner else [])
        records, self.group_records = self.group_records, []
        for index, record in enumerate(records):
            if not blocks:
                self.guide.notes.append(Note(record.title, record.line, items=record.items))
                continue
            score, owner = max(((shared_words(b.title, record.title), b) for b in blocks), key=lambda pair: pair[0])
            if score == 0:
                owner = blocks[index] if len(records) == len(blocks) else blocks[0]
            owner.records.append(record)
        self.record = None
        if self.group:
            self.block = self.group[-1]
        self.group, self.group_owner, self.in_columns = [], None, False

    def add(self, token):
        right = token.column == 1 and self.in_columns and (self.record is not None or self.group or self.group_owner)
        if right:
            if self.record is None:
                self.start_record(Token("heading", "", token.line, column=1))
                self.record.title = ""
            self.record.items.append(classify(token, in_record=True))
        elif self.note is not None:
            self.note.items.append(classify(token))
        elif self.block is not None:
            self.block.items.append(classify(token))
        else:
            self.preamble(token)
        self.place(token.line)

    def preamble(self, token):
        """Строка до первого блока и вне callout'а — в заметку шапки; ⏱ задаёт общую длительность."""
        if token.text.startswith("⏱"):
            if self.part is None and self.guide.minutes is None:
                self.guide.minutes = parse_minutes(token.text)[0]
            elif self.part is not None and self.part.minutes is None:
                self.part.minutes = parse_minutes(token.text)[0]
        if not self.guide.notes or self.guide.notes[-1].icon or self.guide.notes[-1].title:
            self.guide.notes.append(Note("", token.line))
        self.guide.notes[-1].items.append(classify(token))

    def feed(self, token):
        kind = token.kind
        if kind == "columns":
            self.open_columns()
            return
        if kind == "end-columns":
            self.close_columns()
            return
        if kind == "unknown":
            alt = re.search(r'<unknown\b[^>]*alt="([^"]*)"', token.text)
            what = f"блок Notion без markdown ({alt[1]})" if alt else f"незнакомый тег: {token.text[:80]}"
            self.guide.warnings.append(f"строка {token.line}: {what} — строка не разобрана")
            self.place(token.line)
            return
        if kind == "callout":
            self.place(token.line)
            if self.block is None and self.note is None or (self.note is not None and self.note.icon):
                self.target_note("", token.line, icon=token.callout)
            return
        if kind == "end-callout":
            self.place(token.line)
            if self.note is not None and self.note.icon and self.block is None:
                self.note = None
            return
        if kind == "table":
            self.place(*token.lines)
            self.table(token)
            return
        if token.callout == "✂️" and self.block is None:
            self.cut_lines.append(clean(token.text))
        if kind == "heading":
            self.heading(token)
            return
        if token.callout.startswith(WARN) and self.block is None and self.note is not None and self.note.icon.startswith(WARN):
            self.guide.traps.append(classify(token))
            self.place(token.line)
            return
        self.add(token)

    def heading(self, token):
        self.place(token.line)
        text = token.text
        if token.level == 1:
            if PART.match(text):
                self.start_part(token)
            elif NUMBER.match(text):
                self.start_block(token, "section")
            else:
                self.target_note(text, token.line)
            return
        if token.level == 2 and token.green:
            self.start_record(token)
            return
        if token.level == 2 and token.callout == "":
            self.stop_mode = "стоп-лист" in text.lower()
            if self.stop_mode:
                self.target_note(text, token.line)
                return
            numbered = NUMBER.match(text)
            if numbered or (" — " in text and parse_minutes(text.partition(" — ")[2])[0] and self.part is not None):
                self.start_block(token, "block")
            else:
                self.target_note(text, token.line)
            return
        item = classify(token)
        if self.record is not None and token.column == 1:
            self.record.items.append(item)
        elif self.note is not None:
            self.note.items.append(item)
        elif self.block is not None:
            self.block.items.append(item)
        else:
            self.preamble(token)

    def table(self, token):
        header = [cell.lower() for cell in (token.rows[0] if token.rows else [])]
        if any("к какой минуте" in cell for cell in header):
            self.timeline_rows.append((token.line, header, token.rows[1:]))
        elif self.stop_mode or any("антипаттерн" in cell for cell in header):
            self.guide.stop_list += [{"pattern": row[0], "why": row[1] if len(row) > 1 else ""} for row in token.rows[1:] if row]
        else:
            item = Item("table", " | ".join(token.rows[0]) if token.rows else "", token.line, rows=token.rows, callout=token.callout)
            if token.column == 1 and self.record is not None:
                self.record.items.append(item)
            elif self.note is not None:
                self.note.items.append(item)
            elif self.block is not None:
                self.block.items.append(item)
            else:
                self.guide.notes.append(Note("", token.line, items=[item]))


def assign_ids(guide, order):
    """Номер из гайда — id блока. Номер повторяется в разных частях — id с частью: «ч2-5»."""
    seen = {}
    for block in order:
        seen.setdefault(block.number or slug(block.title), []).append(block)
    for base, blocks in seen.items():
        parts = [b.part for b in blocks]
        for block in blocks:
            unnumbered = not block.number
            qualify = (len(blocks) > 1 or unnumbered) and block.part
            block.id = f"{block.part}-{base}" if qualify else base
        if len(set(parts)) < len(parts):
            guide.errors.append(f"номер {base} повторяется внутри одной части: строки " + ", ".join(str(b.line) for b in blocks))
        if any(not b.number for b in blocks):
            for b in blocks:
                guide.warnings.append(f"строка {b.line}: блок «{b.title}» без номера → id {b.id}")
    for block in order:
        while block.id in guide.blocks:
            block.id += "'"
        guide.blocks[block.id] = block
    for block in order:
        if isinstance(block.parent, Block):
            block.parent.children.append(block.id)
            block.parent = block.parent.id
    for part in guide.parts:
        part.blocks = [b.id for b in order if b.part == part.id]
    for note in guide.notes:
        note.after = note.after.id if isinstance(note.after, Block) else note.after


def find_blocks(guide, phrase):
    """«путь к найму», «числа из блока 6», «эмоции» → id блоков частей-созвонов."""
    term = re.sub(r"\(.*?\)|[⭐*«»\"]", "", phrase).strip(" .").lower()
    if not term:
        return []
    candidates = guide.call_blocks() or list(guide.blocks.values())
    number = re.search(r"блок\w*\s+(\d{1,2}(?:\.\d{1,2})?[а-я]?)", term)
    if number:
        return [b.id for b in candidates if b.number == number[1]][:1]
    exact = [b.id for b in candidates if b.title.lower() == term]
    if exact:
        return exact
    return [b.id for b in candidates if b.kind == "block" and (term in b.title.lower() or b.title.lower() in term)] or \
           [b.id for b in candidates if term in b.title.lower()]


def resolve_cut(guide, lines):
    for line in lines:
        text = re.sub(r"\*\*", "", line)
        if "не резать" in text.lower():
            target = guide.never_cut
        elif "режь" in text.lower() or "если не успеваешь" in text.lower():
            target = guide.cut_order
        else:
            continue
        for phrase in re.split(r"→|,|·|;", text.split(":", 1)[-1]):
            found = find_blocks(guide, phrase)
            if not found and phrase.strip(" ."):
                guide.warnings.append(f"«что резать»: не нашёл блок для «{phrase.strip(' .')}»")
            target += [b for b in found if b not in target]
    for block in guide.blocks.values():
        if (block.star or block.must) and block.id not in guide.never_cut and block.kind == "block":
            guide.never_cut.append(block.id)


def resolve_timeline(guide, tables):
    for line, header, rows in tables:
        closes = next((i for i, cell in enumerate(header) if "закрыт" in cell), len(header) - 1)
        for row in rows:
            if not row or not re.fullmatch(r"\d+", row[0]):
                continue
            minute, text = int(row[0]), row[closes] if closes < len(row) else row[-1]
            ids = []
            for number in re.findall(r"(?:^|\bи\s+|,\s*)(\d{1,2}(?:\.\d{1,2})?[а-я]?)(?=[.\s]|$)", text):
                found = [b for b in guide.call_blocks() if b.number == number]
                if found:
                    ids.append(found[0].id)
                    if found[0].deadline_minute is None:
                        found[0].deadline_minute = minute
            if not ids:
                guide.warnings.append(f"строка {line}: в таблице времени не нашёл блок для «{text}»")
            guide.timeline.append({"minute": minute, "text": text, "blocks": ids})


def check(guide, nonempty, structure, placed):
    if not guide.blocks:
        guide.errors.append("в гайде не найдено ни одного блока — проверь, что это гайд интервью")
    for part in guide.parts:
        if part.kind == "call" and not part.blocks:
            guide.warnings.append(f"в части «{part.title}» нет блоков")
    shared = {b for block in guide.blocks.values() for b in block.shared_with}
    for block in guide.call_blocks() or guide.blocks.values():
        if block.kind == "block" and block.minutes is None and block.number not in shared and not block.shared_with \
                and not (block.parent and guide.blocks[block.parent].minutes):
            guide.warnings.append(f"блок {block.id} «{block.title}» без времени")
    lost = sorted(set(nonempty) - structure - placed)
    for no in lost:
        guide.warnings.append(f"строка {no} потерялась при разборе: {nonempty[no][:80]}")


def parse(text, source=None):
    """Текст гайда → Guide. Ошибки — в guide.errors (звонок с таким гайдом не начинать)."""
    body, first, title = unwrap(text)
    tokens, structure = lex(body, first)
    builder = Builder()
    for token in tokens:
        builder.feed(token)
    guide = builder.guide
    guide.source = source or {}
    guide.title = guide.source.get("title") or title or next(
        (t.text for t in tokens if t.kind == "heading" and t.level == 1 and not NUMBER.match(t.text) and not PART.match(t.text)), "")
    assign_ids(guide, builder.order)
    resolve_cut(guide, builder.cut_lines)
    resolve_timeline(guide, builder.timeline_rows)
    if guide.minutes is None:
        calls = [p.minutes for p in guide.parts if p.kind == "call" and p.minutes]
        guide.minutes = calls[0] if len(calls) == 1 else None
    nonempty = {no: line.strip() for no, line in enumerate(body.split("\n"), start=first) if line.strip()}
    guide.lines = len(nonempty)
    check(guide, nonempty, structure, builder.placed)
    return guide


# --- запись и чтение ---

def to_dict(guide):
    data = asdict(guide)
    data["blocks"] = {key: asdict(block) for key, block in guide.blocks.items()}
    return data


def save(guide, folder):
    folder = Path(folder)
    (folder / "guide.json").write_text(json.dumps(to_dict(guide), ensure_ascii=False, indent=1) + "\n")
    (folder / "guide.report.txt").write_text(report(guide) + "\n")
    return folder / "guide.json"


def load(path):
    data = json.loads(Path(path).read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: схема гайда {data.get('schema')}, ожидается {SCHEMA}")

    def items(raw):
        return [Item(**item) for item in raw]

    guide = Guide(**{k: v for k, v in data.items() if k not in ("parts", "blocks", "notes", "traps")})
    guide.parts = [Part(**p) for p in data["parts"]]
    guide.blocks = {k: Block(**{**b, "items": items(b["items"]), "records": [Record(r["title"], r["line"], items(r["items"])) for r in b["records"]]})
                    for k, b in data["blocks"].items()}
    guide.notes = [Note(**{**n, "items": items(n["items"])}) for n in data["notes"]]
    guide.traps = items(data["traps"])
    return guide


def canon():
    """Блоки интервью по канону на 60 минут — когда гайда под респондента нет."""
    return parse(CANON.read_text(), {"kind": "canon", "title": "Блоки интервью по канону"})


# --- отчёт для глаз ---

def span(minutes):
    if not minutes:
        return "—"
    if minutes["min"] is None:
        return f"до {minutes['max']}"
    return str(minutes["min"]) if minutes["min"] == minutes["max"] else f"{minutes['min']}–{minutes['max']}"


def report(guide):
    out = [f"Гайд: {guide.title}"]
    if guide.source.get("kind") == "notion":
        out.append(f"Notion: изменён {guide.source.get('edited', '?')}, скачан {guide.source.get('fetched', '?')}")
    total = sum(len(b.items) + sum(len(r.items) for r in b.records) for b in guide.blocks.values())
    out.append(f"Строк в исходнике: {guide.lines} · блоков: {len(guide.blocks)} · строк в блоках: {total} · "
               f"заметок: {len(guide.notes)} · ловушек: {len(guide.traps)} · стоп-лист: {len(guide.stop_list)}")
    if guide.minutes:
        out.append(f"Длительность: {span(guide.minutes)} мин")
    parts = guide.parts or [Part("", "call", "Весь звонок", 0, blocks=list(guide.blocks))]
    for part in parts:
        out.append("")
        out.append(f"== {part.title}" + (f" · {span(part.minutes)} мин" if part.minutes else ""))
        for key in part.blocks:
            b = guide.blocks[key]
            marks = "".join(["⭐" if b.star else "", "✂️" if b.cut else "", " не резать" if b.must else ""])
            when = f"к {b.deadline_minute}-й мин" if b.deadline_minute is not None else f"{span(b.minutes)} мин"
            questions = sum(i.kind == "question" for i in b.items)
            indent = "    " if b.parent else "  "
            extra = f" · {b.warning}" if b.warning and not b.must else ""
            out.append(f"{indent}[{b.id}] {b.title} · {when} {marks}".rstrip() + f" · вопросов {questions}" + extra)
    if guide.cut_order:
        out += ["", "Резать по порядку: " + ", ".join(guide.cut_order)]
    if guide.never_cut:
        out.append("Не резать: " + ", ".join(guide.never_cut))
    if guide.errors:
        out += ["", "ОШИБКИ — звонок с этим гайдом не начинать:"] + [f"  {e}" for e in guide.errors]
    if guide.warnings:
        out += ["", "Предупреждения:"] + [f"  {w}" for w in guide.warnings]
    return "\n".join(out)
