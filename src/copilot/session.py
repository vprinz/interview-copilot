"""Одна долгая сессия /nmt-chat на интервью: процесс claude -p в режиме stream-json.

Скилл один раз читает канон и контекст интервью; дальше каждое сообщение — новые реплики,
ответ читается потоком, по строкам (вопрос можно показать раньше конца панели).
"""
import json
import os
import subprocess
import time

from copilot.paths import ROOT


def command(model):
    # Без --strict-mcp-config в сессию грузятся все MCP-серверы пользователя.
    return ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--tools", "Read", "--allowedTools", "Read", "--effort", "low", "--model", model]


class Session:
    def __init__(self, model, process=None):
        self.process = process or subprocess.Popen(
            command(model), cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={**os.environ, "NMT_NO_UPDATE_CHECK": "1"}, start_new_session=True)

    def ask(self, text, on_line=None):
        """Отправляет сообщение. on_line вызывается для каждой готовой строки ответа.

        Возвращает (весь ответ, {took, out, context, ok})."""
        started = time.time()
        message = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        tail = ""
        for raw in self.process.stdout:
            event = json.loads(raw)
            kind = event.get("type")
            if kind == "stream_event" and on_line:
                delta = event["event"].get("delta", {})
                if delta.get("type") == "text_delta":
                    *done, tail = (tail + delta["text"]).split("\n")
                    for line in done:
                        on_line(line)
            elif kind == "result":
                if on_line and tail:
                    on_line(tail)
                usage = event.get("usage", {})
                info = {"took": round(time.time() - started, 1), "out": usage.get("output_tokens", 0),
                        "context": sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
                        "ok": event.get("subtype") == "success" and not event.get("is_error")}
                return event.get("result") or "", info
        raise RuntimeError("сессия nmt-chat закрылась")
