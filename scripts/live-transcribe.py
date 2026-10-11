#!/usr/bin/env python3
"""Шаг 3: живой захват звука созвона → файл транскрипта, который дописывается по ходу.

Микрофон и системный звук захватываются раздельно (bin/audio-capture), режутся на куски
по паузам и распознаются локальным whisper-server. Звук с компьютера не уходит.
В файл попадают строки вида «[12:34] Респондент: …» и «[12:40] Я: …».

    scripts/live-transcribe.py                 # живой созвон, Ctrl-C — закончить
    scripts/live-transcribe.py --check         # 8 секунд: приходит ли звук с обоих каналов
    scripts/live-transcribe.py --headphones    # в наушниках: не глушить микрофон, пока говорит респондент
    scripts/live-transcribe.py --replay-sys recordings/work/sample-5min.wav   # прогон по записи

Транскрипт: recordings/live/<дата_время>.txt, на него же указывает recordings/live/latest.txt.
"""
import argparse
import io
import json
import math
import os
import queue
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import wave
from array import array
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
                    frames, flags, levels = (list(x) for x in zip(*self.pre))
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


class Session:
    def __init__(self, args):
        self.args = args
        out_dir = ROOT / "recordings/live"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M")
        self.path = Path(args.out).resolve() if args.out else out_dir / f"{stamp}.txt"
        keep = {}
        if args.keep_audio:
            for tag, name in (("S", "respondent"), ("M", "me")):
                keep[tag] = wave.open(str(self.path.with_name(f"{self.path.stem}_{name}.wav")), "wb")
                keep[tag].setnchannels(1)
                keep[tag].setsampwidth(2)
                keep[tag].setframerate(RATE)
        self.channels = {"S": Channel("Респондент", 60, keep.get("S")), "M": Channel("Я", 150, keep.get("M"))}
        self.jobs = queue.Queue()
        self.lags = []
        self.port = None
        self.server = None
        self.capture = None

    # --- распознавание ---

    def start_server(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = subprocess.Popen(
            ["whisper-server", "-m", str(ROOT / self.args.model), "-l", "ru", "-t", "4",
             "--vad", "-vm", str(ROOT / "models/ggml-silero-v5.1.2.bin"),
             "--host", "127.0.0.1", "--port", str(self.port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)  # Ctrl-C не должен убить сервер, пока не распознан хвост
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=1)
                return
            except OSError:
                if self.server.poll() is not None:
                    break
                time.sleep(0.5)
        raise SystemExit("whisper-server не запустился")

    def transcribe(self, pcm):
        body = io.BytesIO()
        with wave.open(body, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        boundary = uuid.uuid4().hex
        form = b""
        for name, value in (("response_format", "json"), ("language", "ru"), ("temperature", "0.0")):
            form += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        form += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="chunk.wav"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n").encode() + body.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/inference", data=form,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return " ".join(json.load(response).get("text", "").split())

    def worker(self):
        with open(self.path, "a", buffering=1) as out:
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                label, start, pcm, heard_at = job
                try:
                    text = self.transcribe(pcm)
                except OSError as error:
                    text = ""
                    print(f"распознавание не удалось: {error}", file=sys.stderr)
                if text and not HALLUCINATION.match(text):
                    line = f"[{int(start) // 60:02d}:{int(start) % 60:02d}] {label}: {text}"
                    out.write(line + "\n")
                    lag = time.time() - heard_at
                    self.lags.append(lag)
                    print(f"{line}  (+{lag:.1f} с)", flush=True)
                self.jobs.task_done()

    # --- звук ---

    def feed(self, tag, at, samples):
        channel = self.channels[tag]
        if channel.origin is None:  # канал начинается там, где сейчас общий отсчёт: часы у каналов могут быть разные
            now = max(ch.received for ch in self.channels.values())
            channel.add_silence(now - channel.received)
            channel.origin = at - now / RATE
        gap = int((at - channel.origin) * RATE) - channel.received
        if gap > 30 * RATE:         # часы канала прыгнули — привязываемся заново
            channel.origin, gap = at - channel.received / RATE, 0
        if gap > RATE // 10:        # дырка в потоке: системный звук в тишине может не приходить
            channel.add_silence(gap)
        channel.add(samples)
        for other in self.channels.values():
            behind = channel.received - other.received
            if behind > MAX_LAG:
                other.add_silence(behind - MAX_LAG // 2)
        self.pump()

    def pump(self, final=False):
        system, mic = self.channels["S"], self.channels["M"]
        now = time.time()
        closed = [(system, seg) for seg in system.process()]
        if self.args.headphones:
            closed += [(mic, seg) for seg in mic.process()]
        else:
            # Без наушников микрофон слышит респондента из динамиков: пока он звучит, микрофон не слушаем.
            heard = system.loud
            echo = lambda i: any(heard[max(0, i - ECHO_BEFORE):i + ECHO_AFTER + 1])
            closed += [(mic, seg) for seg in mic.process(None if final else system.done - ECHO_AFTER, echo)]
        if final:
            closed += [(ch, seg) for ch in (system, mic) for seg in ch.flush()]
        for channel, (start, pcm, end) in sorted(closed, key=lambda item: item[1][0]):
            # когда прозвучал конец куска: сейчас минус то, что пришло после него
            self.jobs.put((channel.label, start, pcm, now - (channel.received / RATE - end)))

    def read_capture(self):
        binary, source = ROOT / "bin/audio-capture", ROOT / "scripts/audio-capture.swift"
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            print("собираю bin/audio-capture…", file=sys.stderr)
            binary.parent.mkdir(exist_ok=True)
            subprocess.run(["swiftc", "-O", "-swift-version", "5", str(source), "-o", str(binary),
                            "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist",
                            "-Xlinker", str(ROOT / "scripts/audio-capture.plist")], check=True)
        self.capture = subprocess.Popen([str(binary)], stdout=subprocess.PIPE)
        stream = self.capture.stdout
        while header := stream.read(13):
            if len(header) < 13:
                break
            tag, at, count = struct.unpack("<cdI", header)
            data = stream.read(count * 2)
            if len(data) < count * 2:
                break
            yield tag.decode(), at, array("h", data)

    def read_replay(self):
        """Те же пакеты, но из записей — с той же скоростью, с какой шёл бы живой звук."""
        files = {tag: wave.open(path) for tag, path in (("S", self.args.replay_sys), ("M", self.args.replay_mic)) if path}
        for tag, w in files.items():
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (RATE, 1, 2):
                raise SystemExit(f"{self.args.replay_sys if tag == 'S' else self.args.replay_mic}: нужен WAV 16 кГц, моно, 16 бит")
        for w in files.values():
            w.setpos(min(w.getnframes(), int(self.args.replay_from * RATE)))
        started, position = time.time(), 0.0
        while position < self.args.replay_seconds:
            got = False
            for tag, w in files.items():
                data = w.readframes(RATE // 10)
                if data:
                    got = True
                    yield tag, position, array("h", data)
            if not got:
                break
            position += 0.1
            time.sleep(max(0, started + position / self.args.speed - time.time()))

    # --- режимы ---

    def check(self):
        print("8 секунд слушаю оба канала: скажите что-нибудь и включите любой звук на компьютере.")
        started = None
        for tag, at, samples in self.read_capture():
            started = started or at
            self.feed(tag, at, samples)
            if at - started > 8:
                break
        self.capture.terminate()
        if started is None:
            raise SystemExit("звук не пришёл — см. сообщение выше")
        for tag, name in (("M", "микрофон (я)"), ("S", "системный звук (респондент)")):
            channel = self.channels[tag]
            level = 20 * math.log10(channel.peak / 32768) if channel.peak else float("-inf")
            verdict = "звук есть" if channel.peak > channel.min_level else "тишина"
            print(f"{name}: {channel.received / RATE:.1f} с, пик {level:.0f} дБ — {verdict}")

    def run(self):
        replay = bool(self.args.replay_sys or self.args.replay_mic)
        print("запускаю распознавание…", file=sys.stderr)
        self.start_server()
        latest = self.path.parent / "latest.txt"
        latest.unlink(missing_ok=True)
        latest.symlink_to(self.path.name)
        self.path.touch()
        thread = threading.Thread(target=self.worker, daemon=True)
        thread.start()
        print(f"транскрипт: {self.path}  ·  Ctrl-C — закончить", file=sys.stderr)

        def stop(*_):
            raise KeyboardInterrupt

        # Ctrl-C и обычный kill заканчивают одинаково: дораспознать хвост и закрыть файлы.
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        try:
            for tag, at, samples in (self.read_replay() if replay else self.read_capture()):
                self.feed(tag, at, samples)
        except KeyboardInterrupt:
            pass
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if self.capture:
            self.capture.terminate()
            if self.capture.wait() not in (0, -signal.SIGTERM):
                print("захват звука остановился с ошибкой — см. сообщение выше", file=sys.stderr)
        self.pump(final=True)
        self.jobs.put(None)
        thread.join()
        for channel in self.channels.values():
            if channel.keep:
                channel.keep.close()
        if self.lags:
            lags = sorted(self.lags)
            print(f"\nстрок: {len(lags)} · от конца фразы до строки в файле: медиана {lags[len(lags) // 2]:.1f} с, "
                  f"максимум {lags[-1]:.1f} с · память сервера {self.server_memory()} МБ", file=sys.stderr)
        self.server.terminate()

    def server_memory(self):
        rss = subprocess.run(["ps", "-o", "rss=", "-p", str(self.server.pid)], capture_output=True, text=True).stdout
        return int(rss) // 1024 if rss.strip() else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="только проверить, что звук приходит с обоих каналов")
    parser.add_argument("--headphones", action="store_true", help="я в наушниках: микрофон не слышит респондента")
    parser.add_argument("--keep-audio", action="store_true", help="сохранить звук обоих каналов рядом с транскриптом")
    parser.add_argument("--model", default="models/ggml-large-v3-turbo-q5_0.bin")
    parser.add_argument("--out", help="файл транскрипта (по умолчанию recordings/live/<дата_время>.txt)")
    parser.add_argument("--replay-sys", help="WAV вместо системного звука")
    parser.add_argument("--replay-mic", help="WAV вместо микрофона")
    parser.add_argument("--replay-from", type=float, default=0, help="с какой секунды записи начать")
    parser.add_argument("--replay-seconds", type=float, default=math.inf, help="сколько секунд записи прогнать")
    parser.add_argument("--speed", type=float, default=1.0, help="скорость прогона записи; 1 — как вживую")
    session = Session(parser.parse_args())
    try:
        session.check() if session.args.check else session.run()
    finally:
        for process in (session.capture, session.server):
            if process and process.poll() is None:
                process.terminate()


if __name__ == "__main__":
    main()
