"""Селфтест validate_release_claims, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_release_claims import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    PKG,
    _runtime_status,
    check,
    derived_counts,
    derived_gate_counts,
    derived_verification_counts,
    mvp_gates_are_blocking,
    yaml,
)


@pytest.mark.slow
def test_validate_release_claims_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    checks, agents = derived_counts(PKG)
    vf = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    # берём реальный runtime-claim, который точно есть (parallel_execution generic-orchestrator)
    st = _runtime_status(PKG, "generic-orchestrator", "parallel_execution")
    _g, _m = derived_gate_counts()
    _vt, _vc = derived_verification_counts()
    # v3.34: охват доказательства — часть контракта claims, поэтому есть и в минимальном наборе.
    scopes = {n: {"obtained_by": "CI", "covers": "x", "does_not_cover": "y"}
              for n in ("full-current-python", "compatibility-matrix")}
    base = {"registry_type": "release-claims", "version": vf, "checks_count": checks,
            "agents_count": agents, "gates_count": _g, "mvp_blocking_count": _m,
            "validators_count": _vt, "validators_externally_tested": _vc,
            "evidence_scopes": scopes,
            "docs_must_reference_version": ["README.md"],
            # КАНАЛ — ЧАСТЬ КОНТРАКТА с F-030: это публичный статус релиза, и он обязан быть
            # проверяемым. `qualification` не требует полевых доказательств, поэтому минимальный
            # набор остаётся минимальным; `stable` без обкатки на двух дочках не пройдёт — это
            # проверяется ниже.
            "channel": "qualification",
            "channels": {"qualification": {"requires": ["own_ci_green"]},
                         "stable": {"requires": ["own_ci_green", "field_evidence"],
                                    "field_evidence_min_repos": 2}},
            "runtime_capabilities": [{"runtime": "generic-orchestrator",
                                      "capability": "parallel_execution", "status": st}]}
    expect("согласованные claims -> без ошибок", check(base) == [])
    # F-030: канал зарабатывается. Три проверки — объявление обязательно, `stable` без обкатки не
    # проходит, обкатка на двух РАЗНЫХ дочках проходит.
    _no_chan = {k: v for k, v in base.items() if k != "channel"}
    expect("claims без channel -> ошибка (публичный статус неизвестен)", check(_no_chan) != [])
    expect("stable без полевых доказательств -> ошибка",
           check({**base, "channel": "stable"}) != [])
    expect("stable с обкаткой на двух разных дочках -> без ошибок",
           check({**base, "channel": "stable",
                  "field_evidence": [{"repo": "a", "version": vf, "outcome": "ok"},
                                     {"repo": "b", "version": vf, "outcome": "ok"}]}) == [])
    expect("version != VERSION -> ошибка",
           any("claims отстали" in x for x in check({**base, "version": "0.0.0"})))
    expect("checks_count устарел -> ошибка",
           any("checks_count" in x for x in check({**base, "checks_count": 91})))
    expect("agents_count устарел -> ошибка",
           any("agents_count" in x for x in check({**base, "agents_count": 1})))
    # v3.28.x: числа гейтов — тоже публичная поверхность, тоже DERIVED.
    expect("gates_count устарел -> ошибка",
           any("gates_count" in x for x in check({**base, "gates_count": 999})))
    expect("mvp_blocking_count устарел -> ошибка",
           any("mvp_blocking_count" in x for x in check({**base, "mvp_blocking_count": 999})))
    expect("MVP-блокеры реально blocking: true в реестре", mvp_gates_are_blocking() == [])
    expect("просадка внешнего покрытия валидаторов -> ошибка",
           any("validators_externally_tested" in x
               for x in check({**base, "validators_externally_tested": 0})))
    expect("runtime capability дрейф -> ошибка",
           any("дрейф" in x for x in check({**base, "runtime_capabilities": [
               {"runtime": "generic-orchestrator", "capability": "parallel_execution", "status": "unsupported"}]})))
    # v3.9.1: forbidden_stale_markers — стейл-маркер, реально присутствующий в README -> ошибка
    expect("forbidden_stale_markers: присутствующий в README -> ошибка",
           any("устаревший маркер" in x for x in check({**base, "forbidden_stale_markers": ["Открытая"]})))
    expect("forbidden_stale_markers: отсутствующий -> без ошибки",
           not any("устаревший маркер" in x for x in check({**base, "forbidden_stale_markers": ["NONEXISTENT-STALE-XYZ-9999"]})))
    _bad_doc = {**base, "version": "vNONEXISTENT-9.9.9", "checks_count": checks, "agents_count": agents}
    # version mismatch И doc-reference оба сработают; проверяем doc-reference-ветку отдельно на фейковой версии,
    # подложив её и в VERSION-независимую проверку: используем несуществующую строку -> README её не содержит
    expect("README не ссылается на версию -> ошибка (среди прочих)",
           any("не ссылается на текущую версию" in x for x in check(_bad_doc)))

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect("реальный release-claims.yaml согласован с кодом", errs == [])
        for x in errs:
            print("   -", x)

    assert ok, "перенесённый селфтест validate_release_claims: см. строки FAIL в выводе"
