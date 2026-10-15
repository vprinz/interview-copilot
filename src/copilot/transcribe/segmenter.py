"""Нарезка звука на куски речи по паузам — без зависимостей, на энергии сигнала.

Параметры подбирались на живом звуке (шаг 3, см. память step3): пауза 1 с, мягкий рез после 8 с,
жёсткий на 14 с; короче 0,4 с речи не распознаём.
"""
import math
import re
from array import array
from collections import deque

RATE = 16000
FRAME = 480                 # 30 мс
START_FRAMES = 3            # столько громких кадров из последних четырёх — началась речь
PRE_ROLL = 10               # 300 мс до начала речи идут в кусок
END_PAUSE = 33              # 1 с тишины — конец куска
SHORT_LEN, SHORT_PAUSE = 100, 50    # кусок короче 3 с ждёт продолжения 1,5 с: иначе фраза рвётся на запинке
SOFT_LEN, SOFT_PAUSE = 267, 8   # после 8 с режем на паузе от 240 мс
HARD_LEN, HARD_LOOKBACK = 467, 67   # на 14 с режем принудительно, в самом тихом месте последних 2 с
MIN_VOICED = 13             # куски с речью короче 0,4 с не распознаём
ECHO_BEFORE, ECHO_AFTER = 10, 3     # микрофон глушим, если респондент звучал за 300 мс до и 90 мс после
MAX_LAG = RATE              # канал, отставший на секунду, догоняем тишиной

# Что Whisper «слышит» в тишине, шуме и стуке клавиш.
HALLUCINATION = re.compile(
    r"^(\W*\w{0,2}|спасибо|продолжение следует|спасибо за просмотр|субтитры\b.*|редактор субтитров.*"
    r"|.*dimatorzok.*|.*amara\.org.*)[\s.!…]*$", re.I)


class Channel:
    """Один поток звука: копит сэмплы, делит на кадры, находит куски речи."""

    def __init__(self, label, min_level, keep=None):
        self.label = label
        self.min_level = min_level   # ниже этого уровня — тишина при любом шуме
        self.keep = keep             # wave-файл, если звук сохраняем
        self.buf = array("h")
        self.received = 0            # сэмплов принято от начала, вместе со вставленной тишиной
        self.origin = None           # время источника, которому соответствует начало отсчёта
        self.done = 0                # кадров разобрано
        self.floor = 0.0             # уровень фонового шума
        self.loud = bytearray()      # по байту на кадр: был ли звук
        self.recent = deque(maxlen=4)
        self.pre = deque(maxlen=PRE_ROLL)
        self.seg = None              # открытый кусок: [номер первого кадра, кадры, флаги речи, уровни]
        self.quiet = 0
        self.peak = 0.0

    def add(self, samples):
        self.buf.extend(samples)
        self.received += len(samples)
        if self.keep:
            self.keep.writeframesraw(samples.tobytes())

    def add_silence(self, count):
        self.add(array("h", bytes(count * 2)))

    def process(self, upto=None, echo=None):
        """Разбирает накопленные кадры, возвращает закрытые куски: (начало в секундах, сэмплы, конец в секундах)."""
        closed = []
        while len(self.buf) >= FRAME and (upto is None or self.done < upto):
            frame = self.buf[:FRAME]
            del self.buf[:FRAME]
            level = math.sqrt(sum(x * x for x in frame) / FRAME)
            self.peak = max(self.peak, level)
            loud = level > max(self.min_level, self.floor * 3)
            if loud:
                self.floor *= 1.0005     # если шум вырос насовсем, порог догонит его за минуту
            else:
                self.floor += (level - self.floor) * 0.05
            self.loud.append(loud)
            speech = loud and not (echo and echo(self.done))
            self.recent.append(speech)

            if self.seg is None:
                self.pre.append((frame, speech, level))
                if sum(self.recent) >= START_FRAMES:
                    frames, flags, levels = (list(x) for x in zip(*self.pre, strict=True))
                    self.seg = [self.done - len(frames) + 1, frames, flags, levels]
                    self.pre.clear()
                    self.quiet = 0
            else:
                _, frames, flags, levels = self.seg
                frames.append(frame)
                flags.append(speech)
                levels.append(level)
                self.quiet = 0 if speech else self.quiet + 1
                spoken = len(frames) - self.quiet
                if self.quiet >= (END_PAUSE if spoken >= SHORT_LEN else SHORT_PAUSE):
                    closed += self._close(spoken + 7)
                elif len(frames) >= SOFT_LEN and self.quiet >= SOFT_PAUSE:
                    closed += self._close(len(frames))
                elif len(frames) >= HARD_LEN:
                    tail = levels[-HARD_LOOKBACK:]
                    closed += self._close(len(frames) - HARD_LOOKBACK + tail.index(min(tail)), carry=True)
            self.done += 1
        return closed

    def flush(self):
        return self._close(len(self.seg[1])) if self.seg else []

    def _close(self, keep, carry=False):
        start, frames, flags, levels = self.seg
        self.seg = [start + keep, frames[keep:], flags[keep:], levels[keep:]] if carry else None
        if sum(flags[:keep]) < MIN_VOICED:
            return []
        return [(start * FRAME / RATE, b"".join(f.tobytes() for f in frames[:keep]), (start + keep) * FRAME / RATE)]
