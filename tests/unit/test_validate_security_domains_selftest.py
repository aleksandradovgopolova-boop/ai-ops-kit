"""Селфтест validate_security_domains, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_security_domains import (  # noqa: F401 — имена, которые использует тело
    PKG,
    REQUIRED_DOMAINS,
    check,
    yaml,
)


@pytest.mark.slow
def test_validate_security_domains_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    real = PKG / "security" / "security-domains.yaml"
    if real.exists():
        expect("поставляемый security-domains.yaml валиден",
               check(yaml.safe_load(real.read_text(encoding="utf-8"))) == [])
    good = {"kind": "security-domains", "allowed_evidence_sources": ["secret_scan", "security_reviewer"],
            "domains": [{"id": d, "applicability": {"signals": [], "file_patterns": [".*"]},
                         "required_evidence": ["secret_scan"], "severity_policy": {"default": "high"},
                         "remediation_template": {"summary": "fix"}} for d in REQUIRED_DOMAINS]}
    expect("синтетический полный набор валиден", check(good) == [])
    expect("не тот kind -> ошибка", any("security-domains" in e for e in check({"kind": "x"})))
    bad_ev = {"kind": "security-domains", "allowed_evidence_sources": ["secret_scan"],
              "domains": [{"id": "secrets", "applicability": {"file_patterns": [".*"]},
                           "required_evidence": ["magic"], "severity_policy": {"default": "high"},
                           "remediation_template": {"summary": "x"}}]}
    expect("required_evidence вне allowed -> ошибка", any("magic" in e for e in check(bad_ev)))
    bad_sev = {"kind": "security-domains", "allowed_evidence_sources": ["secret_scan"],
               "domains": [{"id": "secrets", "applicability": {"file_patterns": [".*"]},
                            "required_evidence": ["secret_scan"], "severity_policy": {"default": "meh"},
                            "remediation_template": {"summary": "x"}}]}
    expect("неизвестная severity -> ошибка", any("severity_policy" in e for e in check(bad_sev)))
    expect("неполный набор доменов -> ошибка", any("не хватает" in e for e in check(bad_sev)))

    assert ok, "перенесённый селфтест validate_security_domains: см. строки FAIL в выводе"
