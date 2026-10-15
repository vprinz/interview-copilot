"""HTTP для панели: страница, её состояние и кнопки. Слушает только 127.0.0.1."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from copilot.paths import PACKAGE

WEB = PACKAGE / "web"
FILES = {"/": ("panel.html", "text/html; charset=utf-8"), "/panel.css": ("panel.css", "text/css; charset=utf-8"),
         "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
         "/panel-state.schema.json": ("panel-state.schema.json", "application/json")}


def serve(copilot, port):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, body, kind, code=200):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/state":
                self.reply(json.dumps(copilot.snapshot(), ensure_ascii=False).encode(), "application/json")
            elif self.path == "/guide":
                self.reply(json.dumps(copilot.guide_info, ensure_ascii=False).encode(), "application/json")
            elif self.path in FILES:
                name, kind = FILES[self.path]
                self.reply((WEB / name).read_bytes(), kind)
            else:
                self.reply(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path == "/refresh":
                copilot.refresh.set()
            elif self.path == "/skip":
                copilot.skip()
            elif self.path == "/restart-clock":
                copilot.restart_clock()
            self.reply(b"{}", "application/json")

        def log_message(self, *_):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return http
