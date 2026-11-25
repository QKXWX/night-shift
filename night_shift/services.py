# -*- coding: utf-8 -*-
"""三个真实的小服务：DNS、Web、磁盘配额。

它们不是 mock 返回值：DNS 走真实 UDP 协议，Web 走真实 HTTP，
磁盘检查读真实文件大小。所以「修好了」必须真的能通。
"""

import json
import os
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default if default is not None else {}


class DNSHandler(socketserver.BaseRequestHandler):
    """最小 DNS 服务器：只回答 zone.json 里的一条 A 记录。"""

    def handle(self):
        data, sock = self.request
        if len(data) < 16:
            return
        try:
            qname, qtype, qend = _parse_question(data)
        except Exception:
            return
        zone = _read_json(self.server.zone_path, {})
        answer_ip = None
        if qtype == 1 and qname.lower() == str(zone.get("name", "")).lower():
            answer_ip = str(zone.get("ip", ""))

        if answer_ip:
            try:
                ip_bytes = bytes(int(part) for part in answer_ip.split("."))
            except ValueError:
                ip_bytes = b"\x00\x00\x00\x00"
            header = data[:2] + b"\x81\x80" + struct.pack(">HHHH", 1, 1, 0, 0)
            question = data[12:qend]
            answer = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + ip_bytes
            response = header + question + answer
        else:
            header = data[:2] + b"\x81\x83" + struct.pack(">HHHH", 1, 0, 0, 0)
            response = header + data[12:qend]
        sock.sendto(response, self.client_address)


def _parse_question(data):
    offset = 12
    labels = []
    while True:
        length = data[offset]
        offset += 1
        if length == 0:
            break
        labels.append(data[offset:offset + length].decode("ascii", "ignore"))
        offset += length
    qtype, _qclass = struct.unpack(">HH", data[offset:offset + 4])
    return ".".join(labels), qtype, offset + 4


class DnsService:
    def __init__(self, zone_path, host="127.0.0.1", port=0):
        self.zone_path = zone_path
        self.server = socketserver.ThreadingUDPServer((host, port), DNSHandler)
        self.server.zone_path = zone_path
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class WebHandler(BaseHTTPRequestHandler):
    server_version = "night-shift-web/0.1"

    def log_message(self, fmt, *args):
        return

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            config = _read_json(self.server.config_path, {})
            upstream = config.get("upstream_port")
            disk_pct = self.server.disk_pct()
            if upstream != self.server.server_port:
                self._json(502, {
                    "ok": False,
                    "error": "upstream %s 拒绝连接" % upstream,
                    "upstream_port": upstream,
                    "disk_pct": disk_pct,
                })
                return
            if disk_pct >= self.server.disk_threshold:
                self._json(507, {
                    "ok": False,
                    "error": "insufficient storage",
                    "upstream_port": upstream,
                    "disk_pct": disk_pct,
                })
                return
            self._json(200, {"ok": True, "upstream_port": upstream, "disk_pct": disk_pct})
            return
        if self.path.split("?")[0] == "/":
            body = (
                "<!doctype html><meta charset=utf-8><title>night-shift portal</title>"
                "<body style='background:#0b1020;color:#d7e3ff;font-family:sans-serif'>"
                "<h1>portal.nightshift.lab</h1><p>教学门户正在运行。</p></body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"ok": False, "error": "not found"})


class WebService:
    def __init__(self, config_path, disk_dir, budget_mb, host="127.0.0.1", port=0, threshold=80):
        self.server = ThreadingHTTPServer((host, port), WebHandler)
        self.server.config_path = config_path
        self.server.disk_dir = disk_dir
        self.server.budget_mb = float(budget_mb)
        self.server.disk_threshold = float(threshold)
        self.server.disk_pct = lambda: disk_pct(disk_dir, budget_mb)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def disk_pct(directory, budget_mb):
    total = 0
    try:
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                total += os.path.getsize(path)
    except OSError:
        return 0.0
    budget = max(float(budget_mb), 0.001) * 1024 * 1024
    return round(total / budget * 100, 1)
