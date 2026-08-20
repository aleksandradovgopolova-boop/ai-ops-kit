"""Тесты Tech Health (PR-14) на фикстурах: все цвета из выгрузки + «не проверено» ≠ «в порядке»."""
from __future__ import annotations

import yaml

import health_tech as ht
from ai_ops_kit.intelligence import health_common as hc


def _export(root, data):
    (root / ".ai-ops").mkdir(exist_ok=True)
    (root / ht.EXPORT_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_no_export_is_unknown_not_green(tmp_path):
    r = ht.tech_health_report(tmp_path)
    assert r["band"] == hc.UNKNOWN
    assert r["complete"] is False
    assert set(r["unverified"]) == {"ci", "tests", "lint", "security", "dependencies"}
    assert all(reason.strip() for reason in r["reasons"])


def test_all_healthy_is_green(tmp_path):
    _export(tmp_path, {
        "ci": {"status": "passing"},
        "tests": {"passed": 271, "total": 271},
        "lint": {"errors": 0},
        "security": {"critical": 0, "high": 0},
        "dependencies": {"outdated": 0},
    })
    r = ht.tech_health_report(tmp_path)
    assert r["band"] == hc.GREEN
    assert r["complete"] is True


def test_failing_ci_is_red(tmp_path):
    _export(tmp_path, {"ci": {"status": "failing"}, "tests": {"passed": 271, "total": 271}})
    r = ht.tech_health_report(tmp_path)
    assert r["band"] == hc.RED
    assert any("CI" in reason for reason in r["reasons"])


def test_lint_errors_are_red(tmp_path):
    _export(tmp_path, {"lint": {"errors": 3}})
    assert ht._lint_signal({"lint": {"errors": 3}}).band == hc.RED


def test_high_vulns_are_yellow_critical_are_red(tmp_path):
    assert ht._security_signal({"security": {"high": 2}}).band == hc.YELLOW
    assert ht._security_signal({"security": {"critical": 1}}).band == hc.RED
    assert ht._security_signal({"security": {"critical": 0, "high": 0}}).band == hc.GREEN


def test_tests_ratio_bands():
    assert ht._tests_signal({"tests": {"passed": 271, "total": 271}}).band == hc.GREEN
    assert ht._tests_signal({"tests": {"passed": 90, "total": 100}}).band == hc.YELLOW
    assert ht._tests_signal({"tests": {"passed": 50, "total": 100}}).band == hc.RED


def test_zero_total_tests_is_unknown_not_green():
    # ноль тестов — не «всё прошло», а «доля не определена»
    assert ht._tests_signal({"tests": {"passed": 0, "total": 0}}).band == hc.UNKNOWN


def test_outdated_deps_are_yellow():
    assert ht._deps_signal({"dependencies": {"outdated": 4}}).band == hc.YELLOW
    assert ht._deps_signal({"dependencies": {"outdated": 0}}).band == hc.GREEN


def test_broken_export_is_unknown_not_green(tmp_path):
    (tmp_path / ".ai-ops").mkdir()
    (tmp_path / ht.EXPORT_REL).write_text("[not, a, mapping]\n", encoding="utf-8")
    r = ht.tech_health_report(tmp_path)
    assert r["band"] == hc.UNKNOWN


def test_partial_export_flags_incomplete(tmp_path):
    # только ci прочитан (green); остальное отсутствует -> green по проверенному, но не complete
    _export(tmp_path, {"ci": {"status": "passing"}})
    r = ht.tech_health_report(tmp_path)
    assert r["band"] == hc.GREEN
    assert r["complete"] is False
    assert set(r["unverified"]) == {"tests", "lint", "security", "dependencies"}
