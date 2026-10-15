"""Шаг 3: живой захват звука созвона → файл транскрипта, который дописывается по ходу.

Микрофон и системный звук захватываются раздельно (bin/audio-capture), режутся на куски
по паузам и распознаются локальным whisper-server. Звук с компьютера не уходит.
В файл попадают строки вида «[12:34] Респондент: …» и «[12:40] Я: …».

    scripts/live-transcribe.py                 # живой созвон, Ctrl-C — закончить
    scripts/live-transcribe.py --check         # 8 секунд: приходит ли звук с обоих каналов
    scripts/live-transcribe.py --headphones    # в наушниках: не глушить микрофон, пока говорит респондент
    scripts/live-transcribe.py --replay-sys recordings/work/sample-5min.wav   # прогон по записи

Транскрипт: recordings/live/<дата_время>/transcript.txt, на папку указывает recordings/live/latest.
"""
import argparse
import math
import queue
import signal
import struct
import subprocess
import sys
import threading
import time
import wave
from array import array
from pathlib import Path

from copilot import native
from copilot.paths import new_call_folder
from copilot.transcribe.segmenter import ECHO_AFTER, ECHO_BEFORE, HALLUCINATION, MAX_LAG, RATE, Channel
from copilot.transcribe.whisper import Whisper


class Transcriber:
    def __init__(self, args):
        self.args = args
        # Папка звонка: своя при запуске отдельно, а copilot.py передаёт файл в своей папке (--out).
        if args.out:
            self.path = Path(args.out).resolve()
        else:
            self.path = None if args.check else new_call_folder() / "transcript.txt"
        keep = {}
        if args.keep_audio and self.path:
            for tag, name in (("S", "respondent"), ("M", "me")):
                keep[tag] = wave.open(str(self.path.with_name(f"{self.path.stem}_{name}.wav")), "wb")
                keep[tag].setnchannels(1)
                keep[tag].setsampwidth(2)
                keep[tag].setframerate(RATE)
        self.channels = {"S": Channel("Респондент", 60, keep.get("S")), "M": Channel("Я", 150, keep.get("M"))}
        self.jobs = queue.Queue()
        self.lags = []
        self.whisper = Whisper(args.model)
        self.capture = None

    # --- распознавание ---

    def worker(self):
        with open(self.path, "a", buffering=1) as out:
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                label, start, pcm, heard_at = job
                try:
                    text = self.whisper.transcribe(pcm)
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

            def echo(i):
                return any(heard[max(0, i - ECHO_BEFORE):i + ECHO_AFTER + 1])

            closed += [(mic, seg) for seg in mic.process(None if final else system.done - ECHO_AFTER, echo)]
        if final:
            closed += [(ch, seg) for ch in (system, mic) for seg in ch.flush()]
        for channel, (start, pcm, end) in sorted(closed, key=lambda item: item[1][0]):
            # когда прозвучал конец куска: сейчас минус то, что пришло после него
            self.jobs.put((channel.label, start, pcm, now - (channel.received / RATE - end)))

    def read_capture(self):
        binary = native.build("audio-capture")
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
        self.whisper.start()
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
                  f"максимум {lags[-1]:.1f} с · память сервера {self.whisper.memory()} МБ", file=sys.stderr)
        self.whisper.server.terminate()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="только проверить, что звук приходит с обоих каналов")
    parser.add_argument("--headphones", action="store_true", help="я в наушниках: микрофон не слышит респондента")
    parser.add_argument("--keep-audio", action="store_true", help="сохранить звук обоих каналов рядом с транскриптом")
    parser.add_argument("--model", default="models/ggml-large-v3-turbo-q5_0.bin")
    parser.add_argument("--out", help="файл транскрипта (по умолчанию recordings/live/<дата_время>/transcript.txt)")
    parser.add_argument("--replay-sys", help="WAV вместо системного звука")
    parser.add_argument("--replay-mic", help="WAV вместо микрофона")
    parser.add_argument("--replay-from", type=float, default=0, help="с какой секунды записи начать")
    parser.add_argument("--replay-seconds", type=float, default=math.inf, help="сколько секунд записи прогнать")
    parser.add_argument("--speed", type=float, default=1.0, help="скорость прогона записи; 1 — как вживую")
    transcriber = Transcriber(parser.parse_args())
    try:
        transcriber.check() if transcriber.args.check else transcriber.run()
    finally:
        for process in (transcriber.capture, transcriber.whisper.server):
            if process and process.poll() is None:
                process.terminate()
