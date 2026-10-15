"""Локальный whisper-server: large-v3-turbo q5_0 + VAD (без VAD модель зацикливается на паузах, см. шаг 1).
Звук уходит только на 127.0.0.1."""
import io
import json
import socket
import subprocess
import time
import urllib.request
import uuid
import wave

from copilot.paths import ROOT
from copilot.transcribe.segmenter import RATE


class Whisper:
    def __init__(self, model):
        self.model = model
        self.port = None
        self.server = None

    def start(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = subprocess.Popen(
            ["whisper-server", "-m", str(ROOT / self.model), "-l", "ru", "-t", "4",
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

    def memory(self):
        rss = subprocess.run(["ps", "-o", "rss=", "-p", str(self.server.pid)], capture_output=True, text=True).stdout
        return int(rss) // 1024 if rss.strip() else 0
