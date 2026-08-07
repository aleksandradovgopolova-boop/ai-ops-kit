"""Селфтест security_review_cascade, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from security_review_cascade import (  # noqa: F401 — имена, которые использует тело
    check,
    run_cascade,
)


@pytest.mark.slow
def test_security_review_cascade_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    SHA = "deadbeef"

    def det_none(_):  # detector нашёл 0 findings
        return {"findings": []}

    def det_one(defect="x", fid="f1"):
        return lambda _: {"findings": [{"id": fid, "defect": defect}]}

    def ver(verdict, proof=None, cites=None):
        def _v(_code, _f):
            ce = {}
            if proof is not None:
                ce = {"proof_type": proof, "detail": "d", "cited_lines": cites or [1]}
            return {"verdict": verdict, "exploit_path": "e" if verdict == "confirmed" else None,
                    "counter_evidence": ce}
        return _v

    # 1) нет findings → pass
    r = run_cascade("safe code", SHA, det_none, ver("disproved"))
    expect("нет findings → pass", r["final"]["status"] == "pass" and check(r) == [])

    # 2) confirmed → fail
    r = run_cascade("bad", SHA, det_one(), ver("confirmed"))
    expect("verifier confirmed → fail", r["final"]["status"] == "fail" and r["final"]["blockers"] == ["f1"])

    # 3) disproved + распознанное доказательство + корроборация True → pass (даунгрейд)
    code_param = "conn.execute('SELECT * FROM u WHERE n=?', (name,))"
    r = run_cascade(code_param, SHA, det_one(), ver("disproved", "parameterized_query", [1]))
    expect("disproved + parameterized_query (corr True) → pass",
           r["final"]["status"] == "pass" and r["final"]["downgraded_findings"] == ["f1"])

    # 4) disproved БЕЗ распознанного доказательства → pending_human (fail-closed)
    r = run_cascade("bad", SHA, det_one(), ver("disproved", proof=None))
    expect("disproved без структурного доказательства → pending_human",
           r["final"]["status"] == "pending_human" and "f1" in r["final"]["pending"])

    # 5) КЛЮЧЕВОЙ: verifier ВРЁТ disproved parameterized_query, но код — f-string SQL → корроборация
    #    опровергает → pending_human, НЕ pass. Реальный дефект не превращается в false green.
    code_fstring = "conn.execute(f\"SELECT * FROM u WHERE n='{name}'\")"
    r = run_cascade(code_fstring, SHA, det_one(defect="sqli"), ver("disproved", "parameterized_query", [1]))
    expect("disproved с ОПРОВЕРГНУТЫМ доказательством → pending_human (не false green)",
           r["final"]["status"] == "pending_human" and "f1" in r["final"]["pending"])

    # 6) uncertain → pending_human
    r = run_cascade("bad", SHA, det_one(), ver("uncertain"))
    expect("uncertain → pending_human", r["final"]["status"] == "pending_human")

    # 7) detector schema-fail → pending_human (не pass)
    r = run_cascade("bad", SHA, lambda _: None, ver("disproved"))
    expect("detector schema-fail → pending_human (fail-closed)",
           r["final"]["status"] == "pending_human" and r["schema_valid"] is False)

    # 8) verifier schema-fail на finding → pending_human
    r = run_cascade("bad", SHA, det_one(), lambda _c, _f: {"verdict": "garbage"})
    expect("verifier schema-fail → pending_human", r["final"]["status"] == "pending_human")

    # 9) корроборация checksum_not_security: md5 на пароле → опровергнуто → pending
    code_pw = "return hashlib.md5(password.encode()).hexdigest()"
    r = run_cascade(code_pw, SHA, det_one(defect="weak-crypto"),
                    ver("disproved", "checksum_not_security", [1]))
    expect("md5-на-пароле, заявлен checksum → опровергнуто → pending_human",
           r["final"]["status"] == "pending_human")

    # 10) корроборация safe_argv: shell=True → опровергнуто → pending
    code_shell = "subprocess.run('ping ' + host, shell=True)"
    r = run_cascade(code_shell, SHA, det_one(defect="cmdi"), ver("disproved", "safe_argv", [1]))
    expect("shell=True, заявлен safe_argv → опровергнуто → pending_human",
           r["final"]["status"] == "pending_human")

    # 11) множественные findings: один confirmed → весь fail (blocker доминирует над downgrade)
    def det_two(_):
        return {"findings": [{"id": "a", "defect": "x"}, {"id": "b", "defect": "y"}]}

    def ver_mixed(_code, f):
        if f["id"] == "a":
            return {"verdict": "disproved", "counter_evidence": {"proof_type": "not_a_secret", "cited_lines": [1]}}
        return {"verdict": "confirmed", "exploit_path": "e", "counter_evidence": {}}
    r = run_cascade("x", SHA, det_two, ver_mixed)
    expect("blocker доминирует: один confirmed при одном downgrade → fail",
           r["final"]["status"] == "fail" and r["final"]["blockers"] == ["b"])

    # check() отвергает несогласованный результат
    expect("check: pass с blockers → ошибка",
           any("fail-closed" in x for x in check({"kind": "SecurityCascadeResult", "tested_sha": "s",
               "primary": {}, "verification": {},
               "final": {"status": "pass", "blockers": ["z"], "pending": [], "downgraded_findings": []}})))

    assert ok, "перенесённый селфтест security_review_cascade: см. строки FAIL в выводе"
