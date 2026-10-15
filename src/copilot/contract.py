"""Контракт ответа сессии nmt-chat: формат для модели, разбор строк и состояние панели — в одном месте.

Модель отвечает панелью из шести строк «КЛЮЧ: значение». Описание формата для модели (FORMAT)
подставляется в стартовое сообщение, парсер ниже разбирает те же строки. Строка «КЛЮЧ: =» —
значение не изменилось. Строки, которые не разобрались, не стирают панель: они попадают в errors,
а ответ без единой разобранной строки виден на панели как «ответ не по формату».

Версия 2: блоки называются id из guide.json («3.5», «ч2-вход»), а не словами. Разбор версии 2 —
надмножество версии 1: старые поля (block, ahead, topic, question…) заполняются как раньше, новые
(block_id, ahead_ids, cut_ids, topic_id, fills) — когда в строке есть id. Неизвестный гайду id — ошибка
формата, текст строки при этом остаётся на панели.
"""
import re
from dataclasses import asdict, dataclass, field

VERSION = 2
KEYS = ("БЛОК", "ЗАДАЧИ", "СОБРАНО", "ВОПРОС", "ФЛАЖКИ", "КАНОН")
SLOTS = ["результат", "критерии", "контекст", "триггер", "выше", "эмоции", "частота", "важность"]
MARKS = ("✓", "≈", "✗")

FORMAT = """\
БЛОК: <id блока, в котором сейчас разговор> | впереди: <id блоков «не резать», которые ещё впереди, через запятую> | резать: <id блоков, которые предлагаешь пропустить, через запятую, или —>
ЗАДАЧИ: <до 4 задач, которые респондент назвал сам, его словами, до 6 слов каждая, через « | »> → копать: <номер по порядку> — <почему, до 6 слов>
СОБРАНО: результат <✓ его слова | ✗> | критерии <✓ | ≈ | ✗> | контекст <✓|✗> | триггер <✓|✗> | выше <✓ его слова | ✗> | эмоции <✓|≈|✗> | частота <✓|✗> | важность <✓|✗>
ВОПРОС: <id блока, к которому относится вопрос> · <что добираем, до 4 слов> | <один следующий вопрос, без кавычек>
ФЛАЖКИ: <не больше трёх, через « | », или —>
КАНОН: <принцип, на который опирается вопрос: файл и номер раздела, до 8 слов>"""

# Пример ответа: должен разбираться без ошибок (проверяется тестом).
EXAMPLE = """\
БЛОК: 3.1 | впереди: 4.2, 6, 9, 10 | резать: 8, 7
ЗАДАЧИ: получать клиентов из блога | регулярно выпускать ролики → копать: 1 — ближе к бизнес-цели
СОБРАНО: результат ✓ клиенты из блога | критерии ≈ | контекст ✗ | триггер ✗ | выше ✗ | эмоции ✗ | частота ✗ | важность ✗
ВОПРОС: 3.1 · порог критерия | По каким признакам ты понимаешь, что клиентов из блога достаточно?
ФЛАЖКИ: критерий абстрактный — довести до цифры
КАНОН: гайд интервью §1 п.9"""

LINE = re.compile(r"^\s*(" + "|".join(KEYS) + r"):\s*(.*?)\s*$")
BLOCK_ID = re.compile(r"^(?:ч\d+-[\w-]+|\d{1,2}(?:\.\d{1,2})?[а-я]?)$")
LOOKS_LIKE_KEY = re.compile(r"^\s*([А-ЯЁA-Z]{3,}):")


@dataclass
class Update:
    key: str
    value: str


@dataclass
class FormatError:
    line: str
    why: str

    def __str__(self):
        return f"{self.why}: {self.line[:120]}"


def parse_line(line):
    """Одна строка ответа → Update, None (пустая, «=» или обычный текст) или FormatError."""
    found = LINE.match(line)
    if found:
        return None if found[2] in ("=", "") else Update(found[1], found[2])
    other = LOOKS_LIKE_KEY.match(line)
    if other:
        return FormatError(line, f"незнакомое поле {other[1]}")
    return None


def find_ids(text):
    """«4.2, 6 и 9» → ["4.2", "6", "9"]. Элемент списка должен быть id целиком (можно с ⭐ или точкой
    в конце), а не текстом с числами: «9 через 5 мин» — не id, такой элемент пропускается."""
    found = []
    for chunk in re.split(r"\s*[,;]\s*|\s+и\s+", text.strip()):
        item = re.fullmatch(r"(\S+?)\.?[\s⭐✂️*]*", chunk)
        if item and BLOCK_ID.match(item[1]):
            found.append(item[1])
    return found


def leading_id(text):
    """id в начале строки: «3.5 · триггер» → «3.5», «3.5 Триггер» → «3.5», «прокопка» → ""."""
    head = re.split(r"\s*·\s*|\s+", text.strip(), maxsplit=1)[0] if text.strip() else ""
    return head.rstrip(".") if BLOCK_ID.match(head.rstrip(".")) else ""


def empty_slots():
    return [{"name": name, "mark": "✗", "text": ""} for name in SLOTS]


@dataclass
class PanelState:
    """То, что панель получает от модели. Поля и их смысл — docs/architecture.md, раздел 6."""
    block: str = ""
    ahead: str = ""
    tasks: list = field(default_factory=list)
    dig: int | None = None
    why: str = ""
    slots: list = field(default_factory=empty_slots)
    question: str = ""
    topic: str = ""
    flags: list = field(default_factory=list)
    canon: str = ""
    block_id: str = ""
    ahead_ids: list = field(default_factory=list)
    cut_ids: list = field(default_factory=list)
    topic_id: str = ""
    fills: str = ""

    def apply(self, update, ids=None):
        """Применяет строку панели. ids — id блоков гайда; возвращает ошибки (неизвестные id)."""
        key, value = update.key, update.value
        errors = []

        def known(found):
            unknown = [i for i in found if ids is not None and i not in ids]
            errors.extend(f"блока {i} нет в гайде: {key}: {value[:80]}" for i in unknown)
            return [i for i in found if i not in unknown]

        if key == "БЛОК":
            self.block, _, self.ahead = (part.strip() for part in value.partition("|"))
            self.block_id = next(iter(known([leading_id(self.block)] if leading_id(self.block) else [])), "")
            self.ahead_ids, self.cut_ids = [], []
            for part in self.ahead.split("|"):
                label, _, rest = part.partition(":")
                if label.strip().lower() == "впереди":
                    self.ahead_ids = known(find_ids(rest))
                elif label.strip().lower() == "резать":
                    self.cut_ids = known(find_ids(rest))
        elif key == "ЗАДАЧИ":
            left, _, right = value.partition("→")
            self.tasks = [re.sub(r"^\d+[.)]?\s*", "", task.strip()) for task in left.split("|") if task.strip(" —")]
            choice = re.search(r"(\d)\s*[—–-]\s*(.*)", right)
            self.dig, self.why = (int(choice[1]) - 1, choice[2].strip()) if choice else (None, right.replace("копать:", "").strip())
        elif key == "СОБРАНО":
            for part in value.split("|"):
                slot = re.match(r"\s*(\S+)\s*(✓|≈|✗)\s*(.*?)\s*$", part)
                if slot and slot[1] in SLOTS:
                    self.slots[SLOTS.index(slot[1])] = {"name": slot[1], "mark": slot[2], "text": slot[3]}
        elif key == "ВОПРОС":
            topic, _, question = value.rpartition(" | ")
            self.topic, self.question = topic.strip(), question.strip("«»\" ")
            found = leading_id(self.topic)
            self.topic_id = next(iter(known([found] if found else [])), "")
            self.fills = self.topic.partition("·")[2].strip() if "·" in self.topic else ""
        elif key == "ФЛАЖКИ":
            self.flags = [] if value.strip() in ("—", "-") else [flag.strip() for flag in value.split("|") if flag.strip()]
        elif key == "КАНОН":
            self.canon = value
        return errors

    def as_dict(self):
        return asdict(self)


class Reply:
    """Разбор одного ответа по мере прихода строк: применяет обновления, копит ошибки."""

    def __init__(self, state, on_update=None, ids=None):
        self.state = state
        self.on_update = on_update
        self.ids = ids
        self.keys = []
        self.errors = []

    def feed(self, line):
        result = parse_line(line)
        if isinstance(result, FormatError):
            self.errors.append(str(result))
        elif result is not None:
            self.errors += self.state.apply(result, self.ids)
            self.keys.append(result.key)
            if self.on_update:
                self.on_update(result)
        elif LINE.match(line):
            self.keys.append(LINE.match(line)[1])  # «=» — поле на месте, тоже ответ по формату

    def finish(self, text):
        """Весь ответ пришёл. Если в нём нет ни одной строки панели — это ошибка формата."""
        if not self.keys and text.strip():
            self.errors.append(f"в ответе нет ни одной строки панели: {text.strip()[:120]}")
        return self.errors


# --- состояние панели целиком (/state) ---
# Поля модели — из PanelState, поля копайлота — ниже. Из этого описания собирается
# web/panel-state.schema.json; страница читает только поля оттуда, тест сверяет снимок со схемой.

RUNTIME_FIELDS = {
    "status": ("string", "готовлюсь | слушаю | думаю | ответ не по формату | ошибка"),
    "note": ("string", "пояснение к статусу: текст ошибки или неожиданного ответа"),
    "minutes": ("integer", "на сколько минут рассчитан звонок (часть звонка)"),
    "elapsed": ("integer", "секунд от начала интервью; клик по таймеру обнуляет"),
    "now": ("number", "время копайлота, unix-секунды"),
    "next": ("integer", "секунд до следующего обновления по таймеру"),
    "waiting": ("integer", "реплик ждут отправки в сессию"),
    "speed": ("number", "скорость прогона записи; 1 — вживую"),
    "skipped": ("string", "последний пропущенный вопрос"),
    "focus": ("string", "фокус исследования: основная задача | бизнес-цель — от сессии на старте"),
    "heard": ("string", "последняя услышанная реплика"),
    "updated": (["number", "null"], "когда пришёл последний ответ, unix-секунды"),
    "took": (["number", "null"], "сколько шёл последний ответ, секунд"),
    "context": ("integer", "токенов в контексте сессии"),
    "changed": ("object", "ключ строки панели → когда она последний раз менялась"),
    "errors": ("array", "ошибки формата последнего ответа"),
    "timeline": ("object", "блоки части с состоянием done | current | ahead | cut, план по часам, отставание — timeline.build"),
    "guide_block": (["object", "null"], "вопросы, добивки и ловушки текущего блока из гайда — timeline.block_card"),
}

MODEL_FIELDS = {
    "block": "строка БЛОК до первой «|»: id блока (v2) или его название (v1)",
    "ahead": "строка БЛОК после первой «|»",
    "block_id": "id текущего блока, если он есть в гайде",
    "ahead_ids": "id обязательных блоков, которые ещё впереди",
    "cut_ids": "id блоков, которые модель предлагает резать",
    "tasks": "задачи респондента его словами, до 4",
    "dig": "номер задачи для прокопки с нуля или null",
    "why": "почему копать эту задачу",
    "slots": "восемь элементов задачи: name, mark (✓ ≈ ✗), text",
    "question": "следующий вопрос",
    "topic": "часть ВОПРОС до «|»: id блока · что добираем",
    "topic_id": "id блока, к которому относится вопрос",
    "fills": "что добирает вопрос",
    "flags": "флажки, до 3",
    "canon": "ссылка на раздел канона",
}


def json_type(annotation):
    if str(annotation) == "int | None":
        return ["integer", "null"]
    return {str: "string", list: "array", int: "integer"}[annotation]


def state_schema():
    from dataclasses import fields
    properties = {f.name: {"type": json_type(f.type), "description": MODEL_FIELDS[f.name]} for f in fields(PanelState)}
    properties.update({name: {"type": kind, "description": text} for name, (kind, text) in RUNTIME_FIELDS.items()})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Состояние панели копайлота",
            "description": f"GET /state, раз в полсекунды. Формат ответа модели — версия {VERSION}. "
                           "Статичное за звонок — GET /guide: title, kind (notion | file | canon), part, stop_list, "
                           "names (id блока → название).",
            "type": "object", "required": sorted(properties), "properties": properties}


if __name__ == "__main__":
    import json

    from copilot.paths import PACKAGE
    path = PACKAGE / "web/panel-state.schema.json"
    path.write_text(json.dumps(state_schema(), ensure_ascii=False, indent=1) + "\n")
    print(path)
