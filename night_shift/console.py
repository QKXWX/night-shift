# -*- coding: utf-8 -*-
"""值班台 Web 控制台：只开放安全的操作，不让浏览器执行任意命令。"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "night-shift-console/0.1"

    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, data):
        self._send(code, json.dumps(data, ensure_ascii=False))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            self._json(200, {"ok": True, "state": self.server.lab.state()})
            return
        if path in ("/", "/index.html"):
            path = "/index.html"
        name = os.path.basename(path)
        full = os.path.join(WEB_DIR, name)
        if not os.path.isfile(full):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        with open(full, "rb") as handle:
            body = handle.read()
        self._send(200, body, _MIME.get(os.path.splitext(name)[1], "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?")[0]
        lab = self.server.lab
        if path == "/api/check":
            self._json(200, {"ok": True, "checks": lab.checks(), "evidence": lab.evidence()})
            return
        if path == "/api/hint":
            text = lab.hint()
            self._json(200, {"ok": True, "hint": text, "hints_used": lab.hints_used})
            return
        if path == "/api/action":
            data = self._body()
            ok, message = lab.fix(str(data.get("action", "")), data.get("value"))
            self._json(200, {"ok": ok, "message": message, "checks": lab.checks()})
            return
        if path == "/api/submit":
            report = lab.submit()
            self._json(200, {"ok": True, "report": report})
            return
        self._json(404, {"ok": False, "error": "not found"})


class ConsoleServer:
    def __init__(self, lab, host="127.0.0.1", port=0):
        self.server = ThreadingHTTPServer((host, port), ConsoleHandler)
        self.server.lab = lab
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
