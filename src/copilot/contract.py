"""Контракт ответа сессии nmt-chat: формат для модели, разбор строк и состояние панели — в одном месте.

Модель отвечает панелью из шести строк «КЛЮЧ: значение» (версия 1). Описание формата для модели
(FORMAT) подставляется в стартовое сообщение, парсер ниже разбирает те же строки. Строка «КЛЮЧ: =» —
значение не изменилось. Строки, которые не разобрались, не стирают панель: они попадают в errors,
а ответ без единой разобранной строки виден на панели как «ответ не по формату».
"""
import re
from dataclasses import asdict, dataclass, field

VERSION = 1
KEYS = ("БЛОК", "ЗАДАЧИ", "СОБРАНО", "ВОПРОС", "ФЛАЖКИ", "КАНОН")
SLOTS = ["результат", "критерии", "контекст", "триггер", "выше", "эмоции", "частота", "важность"]
MARKS = ("✓", "≈", "✗")

FORMAT = """\
БЛОК: <контакт | квалификация | карта задач | прокопка | продажа | рекомендации> | <что из обязательного ещё не сделано, до 8 слов>
ЗАДАЧИ: <до 4 задач, которые респондент назвал сам, его словами, до 6 слов каждая, через « | »> → копать: <номер по порядку> — <почему, до 6 слов>
СОБРАНО: результат <✓ его слова | ✗> | критерии <✓ | ≈ | ✗> | контекст <✓|✗> | триггер <✓|✗> | выше <✓ его слова | ✗> | эмоции <✓|≈|✗> | частота <✓|✗> | важность <✓|✗>
ВОПРОС: <блок гайда под респондента, к которому относится вопрос, его номером и названием из гайда, и что добираем — до 6 слов> | <один следующий вопрос, без кавычек>
ФЛАЖКИ: <не больше трёх, через « | », или —>
КАНОН: <принцип, на который опирается вопрос: файл и номер раздела, до 8 слов>"""

# Пример ответа: должен разбираться без ошибок (проверяется тестом).
EXAMPLE = """\
БЛОК: прокопка | продажа, рекомендации
ЗАДАЧИ: получать клиентов из блога | регулярно выпускать ролики → копать: 1 — ближе к бизнес-цели
СОБРАНО: результат ✓ клиенты из блога | критерии ≈ | контекст ✗ | триггер ✗ | выше ✗ | эмоции ✗ | частота ✗ | важность ✗
ВОПРОС: 3.1 Критерии успеха · порог | По каким признакам ты понимаешь, что клиентов из блога достаточно?
ФЛАЖКИ: критерий абстрактный — довести до цифры
КАНОН: гайд интервью §1 п.9"""

LINE = re.compile(r"^\s*(" + "|".join(KEYS) + r"):\s*(.*?)\s*$")
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

    def apply(self, update):
        key, value = update.key, update.value
        if key == "БЛОК":
            self.block, _, self.ahead = (part.strip() for part in value.partition("|"))
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
        elif key == "ФЛАЖКИ":
            self.flags = [] if value.strip() in ("—", "-") else [flag.strip() for flag in value.split("|") if flag.strip()]
        elif key == "КАНОН":
            self.canon = value

    def as_dict(self):
        return asdict(self)


class Reply:
    """Разбор одного ответа по мере прихода строк: применяет обновления, копит ошибки."""

    def __init__(self, state, on_update=None):
        self.state = state
        self.on_update = on_update
        self.keys = []
        self.errors = []

    def feed(self, line):
        result = parse_line(line)
        if isinstance(result, FormatError):
            self.errors.append(str(result))
        elif result is not None:
            self.state.apply(result)
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
