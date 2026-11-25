# -*- coding: utf-8 -*-
"""值班引擎：起服务、注入故障、验收、计分。"""

import datetime
import json
import shutil
import socket
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import scenarios
from .services import DnsService, WebService, disk_pct

DNS_NAME = "portal.nightshift.lab"


def _free_tcp_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def dns_lookup(name, port, timeout=2.0):
    """发一条真实 DNS A 查询，返回 (ip, error)。"""
    query_id = 0x4E53
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split(".")) + b"\x00"
    packet = struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + labels + struct.pack(">HH", 1, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, ("127.0.0.1", port))
        data, _ = sock.recvfrom(512)
    except OSError as exc:
        return None, str(exc)
    finally:
        sock.close()
    if len(data) < 12:
        return None, "响应过短"
    flags = struct.unpack(">H", data[2:4])[0]
    ancount = struct.unpack(">H", data[6:8])[0]
    if not (flags & 0x8000):
        return None, "不是 DNS 响应"
    if ancount == 0:
        return None, "NXDOMAIN / 无 A 记录"
    # 跳过问题区
    offset = 12
    while data[offset] != 0:
        offset += 1 + data[offset]
    offset += 5
    # 回答名可能是压缩指针
    if data[offset] & 0xC0 == 0xC0:
        offset += 2
    else:
        while data[offset] != 0:
            offset += 1 + data[offset]
        offset += 1
    rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
    offset += 10
    if rtype != 1 or rdlen != 4:
        return None, "不是 A 记录"
    return ".".join(str(part) for part in data[offset:offset + 4]), None


def http_health(port, timeout=2.0):
    """请求 /health，返回 (status, body)。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body
    except Exception as exc:
        return None, {"error": str(exc)}


class Lab:
    def __init__(self, root="lab", scenario="dns", time_limit=1800,
                 dns_port=None, web_port=None, cache_mb=None, budget_mb=10):
        self.root = Path(root).resolve()
        self.scenario_name = scenario
        self.scenario = scenarios.get(scenario)
        self.time_limit = int(time_limit)
        self.dns_port = int(dns_port or _free_udp_port())
        self.web_port = int(web_port or _free_tcp_port())
        self.cache_mb = float(cache_mb if cache_mb is not None else (9.0 if scenario == "disk" else 0.5))
        self.budget_mb = float(budget_mb)
        self.started_at = None
        self.hints_used = 0
        self.actions = []
        self.dns = None
        self.web = None
        self._submitted = None

    # ---------------- 生命周期 ----------------
    def setup(self):
        if self.root.exists():
            shutil.rmtree(self.root)
        (self.root / "dns").mkdir(parents=True)
        (self.root / "web").mkdir(parents=True)
        (self.root / "disk").mkdir(parents=True)
        (self.root / "logs").mkdir(parents=True)

        zone_ip = "10.0.0.99" if self.scenario_name == "dns" else "127.0.0.1"
        self._write_json(self.root / "dns" / "zone.json", {"name": DNS_NAME, "ip": zone_ip})

        self.dns = DnsService(str(self.root / "dns" / "zone.json"), port=self.dns_port).start()
        self.web = WebService(
            str(self.root / "web" / "config.json"),
            str(self.root / "disk"),
            self.budget_mb,
            port=self.web_port,
        ).start()
        self.web_port = self.web.port
        upstream = self.web_port + 2 if self.scenario_name == "web" else self.web_port
        self._write_json(self.root / "web" / "config.json", {"upstream_port": upstream})

        cache_path = self.root / "disk" / "cache.bin"
        if self.cache_mb > 0:
            with open(cache_path, "wb") as handle:
                handle.truncate(int(self.cache_mb * 1024 * 1024))
        self.started_at = time.time()
        self._log("值班开始：%s（%s）" % (self.scenario["title"], self.scenario_name))
        return self

    def close(self):
        for service in (self.dns, self.web):
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    pass
        self.dns = None
        self.web = None

    # ---------------- 检查 ----------------
    def checks(self):
        checks = []

        ip, error = dns_lookup(DNS_NAME, self.dns_port)
        dns_ok = ip == "127.0.0.1"
        checks.append({
            "key": "dns",
            "label": "域名解析",
            "ok": dns_ok,
            "detail": ("%s → %s" % (DNS_NAME, ip)) if ip else ("%s：%s" % (DNS_NAME, error)),
        })

        status, body = http_health(self.web_port)
        web_ok = status == 200 and bool(body.get("ok"))
        checks.append({
            "key": "web",
            "label": "门户健康",
            "ok": web_ok,
            "detail": ("HTTP %s · upstream=%s" % (status, body.get("upstream_port"))) if status else str(body.get("error")),
        })

        pct = disk_pct(str(self.root / "disk"), self.budget_mb)
        disk_ok = pct < 80
        checks.append({
            "key": "disk",
            "label": "磁盘占用",
            "ok": disk_ok,
            "detail": "缓存占用 %.1f%%（阈值 80%%）" % pct,
        })
        return checks

    def evidence(self):
        lines = []
        for item in self.checks():
            lines.append("[%s] %s：%s" % ("OK" if item["ok"] else "FAIL", item["label"], item["detail"]))
        return lines

    # ---------------- 玩家动作 ----------------
    def fix(self, action, value=None):
        if action == "dns_ip":
            try:
                parts = [int(part) for part in str(value).split(".")]
                if len(parts) != 4 or any(part < 0 or part > 255 for part in parts):
                    raise ValueError("不是合法 IPv4")
            except ValueError as exc:
                return False, str(exc)
            self._write_json(self.root / "dns" / "zone.json", {"name": DNS_NAME, "ip": value})
            self._log("修改 DNS A 记录为 %s" % value)
            return True, "已写入区域文件，下一次查询立即生效。"
        if action == "web_port":
            try:
                port = int(value)
            except (TypeError, ValueError):
                return False, "端口必须是数字"
            self._write_json(self.root / "web" / "config.json", {"upstream_port": port})
            self._log("修改 Web upstream_port 为 %s" % port)
            return True, "已写入配置，下一次请求立即生效。"
        if action == "clean_disk":
            removed = []
            for name in ("cache.bin",):
                path = self.root / "disk" / name
                if path.exists():
                    path.unlink()
                    removed.append(name)
            self._log("清理磁盘：%s" % (", ".join(removed) or "没有可清理文件"))
            return True, "已清理 %s。" % (", ".join(removed) or "（无文件）")
        return False, "未知动作"

    def hint(self):
        if self.hints_used >= len(self.scenario["hints"]):
            return None
        text = self.scenario["hints"][self.hints_used]
        self.hints_used += 1
        self._log("使用线索 #%d" % self.hints_used)
        return text

    def submit(self):
        checks = self.checks()
        passed = all(item["ok"] for item in checks)
        elapsed = int(time.time() - self.started_at) if self.started_at else 0
        score = 0
        if passed and elapsed <= self.time_limit:
            score = max(0, 100 - self.hints_used * 10 - max(0, elapsed - 300) // 60 * 2)
        report = {
            "scenario": self.scenario_name,
            "title": self.scenario["title"],
            "passed": passed,
            "score": score,
            "elapsed_seconds": elapsed,
            "time_limit": self.time_limit,
            "hints_used": self.hints_used,
            "checks": checks,
            "actions": self.actions,
            "root_cause": self.scenario["root_cause"],
            "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self._submitted = report
        self._write_json(self.root / "report.json", report)
        self._log("提交结案：%s，得分 %d" % ("通过" if passed else "未通过", score))
        return report

    # ---------------- 状态 ----------------
    @property
    def remaining(self):
        if not self.started_at:
            return self.time_limit
        return max(0, self.time_limit - int(time.time() - self.started_at))

    @property
    def submitted(self):
        return self._submitted

    def state(self):
        return {
            "scenario": self.scenario_name,
            "title": self.scenario["title"],
            "subtitle": self.scenario["subtitle"],
            "ticket": self.scenario["ticket"],
            "brief": [line.replace("15353", str(self.dns_port)).replace("18080", str(self.web_port))
                      for line in self.scenario["brief"]],
            "fix_action": self.scenario["fix_action"],
            "fix_label": self.scenario["fix_label"],
            "remaining": self.remaining,
            "time_limit": self.time_limit,
            "hints_used": self.hints_used,
            "checks": self.checks(),
            "submitted": self._submitted,
        }

    # ---------------- 文件 ----------------
    def _write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def _log(self, message):
        self.actions.append({
            "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "message": message,
        })
        path = self.root / "logs" / "actions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.actions[-1], ensure_ascii=False) + "\n")
