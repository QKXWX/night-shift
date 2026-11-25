# -*- coding: utf-8 -*-
import json

import pytest

from night_shift.engine import Lab, dns_lookup


def make_lab(tmp_path, scenario, **kwargs):
    lab = Lab(root=str(tmp_path / "lab"), scenario=scenario, time_limit=120,
              cache_mb=8 if scenario == "disk" else 0.5, budget_mb=10, **kwargs).setup()
    return lab


@pytest.fixture
def cleanup():
    labs = []
    yield labs
    for lab in labs:
        lab.close()


def test_dns_scenario_is_really_broken_then_fixed(tmp_path, cleanup):
    lab = make_lab(tmp_path, "dns")
    cleanup.append(lab)
    ip, error = dns_lookup("portal.nightshift.lab", lab.dns_port)
    assert error is None
    assert ip == "10.0.0.99"
    checks = {item["key"]: item for item in lab.checks()}
    assert checks["dns"]["ok"] is False
    assert checks["web"]["ok"] is True
    assert checks["disk"]["ok"] is True

    assert lab.fix("dns_ip", "999.1.1.1")[0] is False
    assert lab.fix("dns_ip", "127.0.0.1")[0] is True
    checks = {item["key"]: item for item in lab.checks()}
    assert all(item["ok"] for item in checks.values())


def test_web_scenario_returns_502_then_200(tmp_path, cleanup):
    lab = make_lab(tmp_path, "web")
    cleanup.append(lab)
    checks = {item["key"]: item for item in lab.checks()}
    assert checks["web"]["ok"] is False
    assert "502" in checks["web"]["detail"] or "upstream" in checks["web"]["detail"]

    assert lab.fix("web_port", lab.web_port)[0] is True
    assert all(item["ok"] for item in lab.checks())


def test_disk_scenario_returns_507_then_recovers(tmp_path, cleanup):
    lab = make_lab(tmp_path, "disk")
    cleanup.append(lab)
    checks = {item["key"]: item for item in lab.checks()}
    assert checks["disk"]["ok"] is False
    assert checks["web"]["ok"] is False

    assert lab.fix("clean_disk")[0] is True
    assert all(item["ok"] for item in lab.checks())


def test_submit_pass_score_and_report(tmp_path, cleanup):
    lab = make_lab(tmp_path, "dns")
    cleanup.append(lab)
    lab.fix("dns_ip", "127.0.0.1")
    lab.hint()
    report = lab.submit()
    assert report["passed"] is True
    assert report["score"] == 90
    assert report["root_cause"]
    saved = json.loads((lab.root / "report.json").read_text(encoding="utf-8"))
    assert saved["passed"] is True


def test_submit_fail_has_no_score(tmp_path, cleanup):
    lab = make_lab(tmp_path, "dns")
    cleanup.append(lab)
    report = lab.submit()
    assert report["passed"] is False
    assert report["score"] == 0


def test_hints_are_finite(tmp_path, cleanup):
    lab = make_lab(tmp_path, "web")
    cleanup.append(lab)
    assert lab.hint()
    assert lab.hint()
    assert lab.hint()
    assert lab.hint() is None
    assert lab.hints_used == 3
