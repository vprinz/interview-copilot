"""Нарезка по паузам на синтетическом сигнале: тишина, «речь» (громкий тон), тишина."""
import math
from array import array

from copilot.transcribe import segmenter
from copilot.transcribe.segmenter import FRAME, RATE, Channel


def tone(seconds, level=3000):
    return array("h", (int(level * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(int(seconds * RATE))))


def silence(seconds):
    return array("h", bytes(int(seconds * RATE) * 2))


def cut(*pieces):
    channel = Channel("Я", 150)
    for piece in pieces:
        channel.add(piece)
    return channel.process() + channel.flush()


def test_phrase_between_pauses_is_one_piece():
    pieces = cut(silence(1), tone(4), silence(2))
    assert len(pieces) == 1
    start, pcm, end = pieces[0]
    assert 0.6 <= start <= 1.0 and 4.9 <= end <= 5.3
    assert len(pcm) == round((end - start) * RATE) * 2


def test_short_click_is_not_speech():
    assert cut(silence(1), tone(0.2), silence(2)) == []


def test_two_phrases_with_long_pause_are_two_pieces():
    assert len(cut(silence(0.5), tone(4), silence(1.5), tone(4), silence(2))) == 2


def test_short_phrase_waits_for_continuation():
    # Кусок короче 3 с не закрывается на паузе в 1 с: фраза не рвётся на запинке.
    assert len(cut(silence(0.5), tone(1.5), silence(1.1), tone(2), silence(2))) == 1


def test_long_monologue_is_cut_hard():
    pieces = cut(silence(0.5), tone(30), silence(2))
    assert len(pieces) >= 2
    assert all(end - start <= segmenter.HARD_LEN * FRAME / RATE + 0.01 for start, _, end in pieces)


def test_hallucinations_are_filtered():
    for text in ("Спасибо.", "Продолжение следует...", "Субтитры сделал DimaTorzok", "Мм", "Ок"):
        assert segmenter.HALLUCINATION.match(text), text
    assert not segmenter.HALLUCINATION.match("Спасибо, что нашёл время")
