"""Селфтест validate_learning_loop, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_learning_loop import (  # noqa: F401 — имена, которые использует тело
    Path,
    adrreg,
    check_loop,
    flreg,
    yaml,
)


@pytest.mark.slow
def test_validate_learning_loop_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # реальная петля кита цела (FL-001.follow_up=[ADR-001] резолвится)
    real_errs, real_stats = check_loop(flreg.DEFAULT_DIR, adrreg.DEFAULT_DIR)
    expect(f"реальная петля research->learning->architecture цела (resolved={real_stats.get('adr_refs_resolved')})",
           real_errs == [])

    def _adr(aid):
        return {"schema_version": 1, "kind": "ArchitectureDecision", "id": aid, "title": "t",
                "status": "accepted", "context": "c", "decision": "d",
                "consequences": {"positive": ["p"], "negative": ["n"]}}

    def _fl(fid, follow_up):
        return {"schema_version": 1, "kind": "FeatureLearning", "id": fid, "feature": "feature:x",
                "hypothesis": "h",
                "validation": {"method": "m", "status": "done", "result": "r"},
                "outcome": {"verdict": "confirmed", "expected": "e", "actual": "a"},
                "follow_up": follow_up, "status": "validated"}

    with tempfile.TemporaryDirectory() as ad, tempfile.TemporaryDirectory() as fd:
        adp, flp = Path(ad), Path(fd)
        (adp / "ADR-001.yaml").write_text(yaml.safe_dump(_adr("ADR-001")), encoding="utf-8")
        # follow_up резолвится
        (flp / "FL-001.yaml").write_text(yaml.safe_dump(_fl("FL-001", ["ADR-001"])), encoding="utf-8")
        e, s = check_loop(flp, adp)
        expect("FL.follow_up ADR резолвится -> петля цела", e == [] and s["adr_refs_resolved"] == 1)

        # dangling ADR-ссылка
        (flp / "FL-002.yaml").write_text(yaml.safe_dump(_fl("FL-002", ["ADR-404"])), encoding="utf-8")
        e, _ = check_loop(flp, adp)
        expect("dangling ADR-ссылка -> разрыв петли", any("ADR-404" in x for x in e))
        (flp / "FL-002.yaml").unlink()

        # RR/DP/feature — слабые, не резолвим (не ошибка)
        (flp / "FL-003.yaml").write_text(
            yaml.safe_dump(_fl("FL-003", ["RR-008", "DP-108", "feature:checkout"])), encoding="utf-8")
        e, _ = check_loop(flp, adp)
        expect("RR/DP/feature follow_up — слабые ссылки, не разрывают петлю", e == [])

        # поломанный ADR-реестр -> честно «почините»
        (adp / "ADR-777.yaml").write_text(yaml.safe_dump({**_adr("ADR-001"), "id": "ADR-999"}),
                                          encoding="utf-8")
        e, _ = check_loop(flp, adp)
        expect("битый ADR-реестр -> сообщает 'почините', не ложная уверенность",
               any("ADR-реестр невалиден" in x for x in e))

    assert ok, "перенесённый селфтест validate_learning_loop: см. строки FAIL в выводе"
