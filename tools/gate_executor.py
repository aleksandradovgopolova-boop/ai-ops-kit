#!/usr/bin/env python3
"""Gate executor — единый исполнитель quality gates (замыкание контура, v2.15).

Раньше sequential-оркестратор проводил стадии, но НЕ читал quality_gates контракта
и ставил workflow `done` при любом ответе ролей — гейты существовали только на бумаге.
Этот модуль резолвит объявленные контрактом гейты, классифицирует КАЖДЫЙ по способу
проверки и честно считает результат, БЛОКИРУЯ переход по workflow, если блокирующий
гейт не выполнен.

Три типа проверок (принцип «writer ≠ judge», честные декларации):
  - deterministic  — гейт с полем `validator` (детерминированный CLI/чек);
  - ai-review      — read-only reviewer c checklist (заключение судьи-роли);
  - human-approval — гейт с `human_approval` (ручное одобрение, в т.ч. условное).

Результат каждого гейта — machine-readable по schemas/gate-result.schema.json
(status ∈ pass|warn|fail; невыполненный блокирующий гейт → fail с blocker, а не
молчаливый pass). Evidence (заключения reviewer'ов / прогоны валидаторов) подаётся
снаружи как {gate_id: {status, checks, evidence, blockers, override}}: executor не
выдумывает вердикты, которых не было.

Использование:
  gate_executor.py <WORKFLOW> [evidence.json]   — оценить гейты (JSON-отчёт)
  gate_executor.py --selftest                    — офлайн-проверки

Требует pyyaml.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]


def _run_validator(*args) -> bool:
    """Запустить package-валидатор офлайн; True при rc==0."""
    r = subprocess.run([sys.executable, str(PKG / "validation" / args[0]), *args[1:]],
                       capture_output=True, text=True)
    return r.returncode == 0


def deterministic_run(validator):
    """(status, checks, provided) для валидаторов, которые РЕАЛЬНО запускаемы офлайн;
    None — если валидатор символический (напр. validate-intake) и требует внешнего evidence.
    Так gate executor не выдумывает вердикт: он либо честно исполняет проверку, либо ждёт evidence."""
    if validator == "validate-references + validate-claims":
        refs, claims = _run_validator("validate_references.py"), _run_validator("validate_claims.py")
        checks = [{"id": "references_resolve", "status": "pass" if refs else "fail"},
                  {"id": "claims_hold", "status": "pass" if claims else "fail"}]
        status = "pass" if refs and claims else "fail"
        return status, checks, [c["id"] for c in checks if c["status"] == "pass"]
    if validator == "validate-freshness":
        ok = _run_validator("validate_freshness.py", "--selftest")
        checks = [{"id": "no_stale_volatile_docs", "status": "pass" if ok else "warn"}]
        return ("pass" if ok else "warn"), checks, [c["id"] for c in checks if c["status"] == "pass"]
    return None

# ключи, разрешённые схемой gate-result (additionalProperties: false)
_ALLOWED_KEYS = {
    "schema_version", "gate", "status", "blocking", "scope", "checks", "blockers",
    "warnings", "evidence", "affected_files", "affected_artifacts", "tested_revision",
    "artifact_hashes", "owner", "review_mode", "created_at", "expires_at", "override",
    "suggested_next",
}


def load_gates():
    return yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")).get("gates", {})


def load_workflows():
    return yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8")).get("workflows", {})


def classify(gate: dict) -> str:
    """Способ проверки гейта: human-approval | deterministic | ai-review | writer-check."""
    if gate.get("human_approval"):            # True или dict {required_when: [...]}
        return "human-approval"
    if gate.get("validator"):
        return "deterministic"
    if gate.get("review_mode") == "read-only":
        return "ai-review"
    return "writer-check"


def _unmet_reason(kind: str, gate: dict) -> str:
    return {
        "deterministic": f"валидатор '{gate.get('validator')}' не запущен или evidence не предоставлен",
        "ai-review": f"нет заключения reviewer ({gate.get('responsible_role')}) — гейт не пройден",
        "human-approval": "требуется ручное одобрение — не получено",
        "writer-check": "результат ответственной стадии не предоставлен",
    }[kind]


def evaluate_gate(gate_id: str, gate: dict, evidence: dict, tested_revision=None) -> dict:
    """Один гейт -> machine-readable gate-result (schemas/gate-result.schema.json).

    Дисциплина evidence (v2.16): бездоказательного pass не существует — если гейт
    объявляет `required_evidence`, статус pass засчитывается ТОЛЬКО когда эти ключи
    подтверждены (через `provided` или passing-checks). Для детерминированных гейтов с
    реально запускаемым валидатором проверка исполняется здесь; символические валидаторы
    и reviewer/human-гейты требуют внешнего evidence."""
    kind = classify(gate)
    blocking = bool(gate.get("blocking"))
    required = gate.get("required_evidence", []) or []
    ev = dict((evidence or {}).get(gate_id) or {})

    # авто-исполнение детерминированного валидатора, если evidence не подан
    if not ev.get("status") and kind == "deterministic":
        run = deterministic_run(gate.get("validator"))
        if run:
            st, checks, provided = run
            ev = {"status": st, "checks": checks, "provided": provided,
                  "evidence": [f"validator {gate.get('validator')} executed"]}

    status = ev.get("status")
    if status in ("pass", "warn", "fail"):
        checks = ev.get("checks", [])
        blockers = list(ev.get("blockers", [])) if status == "fail" else []
        warnings = list(ev.get("warnings", []))
        evid = ev.get("evidence", [])
        override = ev.get("override")
        # запрет бездоказательного pass: required_evidence обязан быть подтверждён
        if status == "pass" and required:
            covered = set(ev.get("provided", [])) | {c.get("id") for c in checks
                                                     if c.get("status") == "pass"}
            missing = [k for k in required if k not in covered]
            if missing:
                msg = f"бездоказательный pass: не подтверждены required_evidence: {', '.join(missing)}"
                status = "fail" if blocking else "warn"
                if blocking:
                    blockers = [msg]
                else:
                    warnings = warnings + [msg]
    else:
        # evidence не предоставлен: честный отказ. Блокирующий -> fail, иначе advisory warn.
        reason = _unmet_reason(kind, gate)
        status = "fail" if blocking else "warn"
        checks = []
        blockers = [reason] if blocking else []
        warnings = [] if blocking else [reason]
        evid = []
        override = None

    result = {
        "schema_version": 1,
        "gate": gate_id,
        "status": status,
        "blocking": blocking,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "evidence": evid,
        "tested_revision": tested_revision,
        "owner": gate.get("responsible_role", "unknown"),
        "review_mode": gate.get("review_mode", "read-only"),
        "created_at": None,
        "expires_at": None,
        "override": override,
    }
    # инвариант: только ключи, разрешённые схемой
    assert set(result).issubset(_ALLOWED_KEYS), set(result) - _ALLOWED_KEYS
    return result


def evaluate(workflow_id: str, evidence: dict = None, tested_revision=None) -> dict:
    """Оценить все quality_gates контракта. Возвращает сводку + per-gate результаты.

    blocked=True, если хотя бы один БЛОКИРУЮЩИЙ гейт получил status=fail. override с
    полем 'by'+'reason' на fail-гейте снимает блокировку по этому гейту (records override)."""
    workflows = load_workflows()
    gates = load_gates()
    if workflow_id not in workflows:
        raise SystemExit(f"неизвестный workflow '{workflow_id}' (есть: {', '.join(workflows)})")
    gate_ids = workflows[workflow_id].get("quality_gates", []) or []

    results, kinds, unmet = [], {}, []
    for gid in gate_ids:
        gate = gates.get(gid)
        if gate is None:                      # контракт ссылается на несуществующий гейт
            raise SystemExit(f"workflow {workflow_id}: гейт '{gid}' отсутствует в quality/gates.yaml")
        kinds[gid] = classify(gate)
        r = evaluate_gate(gid, gate, evidence, tested_revision)
        results.append(r)
        overridden = bool(r.get("override") and r["override"].get("by") and r["override"].get("reason"))
        if r["blocking"] and r["status"] == "fail" and not overridden:
            unmet.append(gid)

    return {
        "schema_version": 1,
        "workflow": workflow_id,
        "evaluated_gates": gate_ids,
        "gate_kinds": kinds,
        "gate_results": results,
        "unmet_gates": unmet,
        "blocked": bool(unmet),
    }


# ---------------- selftest ----------------

def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    gates = load_gates()
    # 1. классификация типов
    expect("intake_completeness -> deterministic", classify(gates["intake_completeness"]) == "deterministic")
    expect("code_review -> ai-review", classify(gates["code_review"]) == "ai-review")
    expect("security -> human-approval (условный)", classify(gates["security"]) == "human-approval")

    # 2. без evidence блокирующие гейты QUICK -> fail, workflow blocked
    r0 = evaluate("QUICK")
    expect("QUICK без evidence -> blocked", r0["blocked"] is True)
    expect("QUICK unmet = оба блокирующих гейта",
           set(r0["unmet_gates"]) == {"intake_completeness", "implementation_verification"})
    expect("невыполненный блокирующий гейт имеет status=fail",
           all(g["status"] == "fail" for g in r0["gate_results"] if g["blocking"]))

    # 3. с полным evidence (required_evidence подтверждён) -> проходит
    good = {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "pass",
            "provided": ["build_passed", "lint_passed", "tests_passed", "tested_revision"]},
    }
    r1 = evaluate("QUICK", good)
    expect("QUICK с подтверждённым evidence -> не blocked", r1["blocked"] is False)

    # 3b. бездоказательный pass (status:pass без required_evidence) -> отклонён, blocked
    r_bare = evaluate("QUICK", {"intake_completeness": {"status": "pass"},
                                "implementation_verification": {"status": "pass"}})
    expect("бездоказательный pass отклонён -> blocked", r_bare["blocked"] is True)

    # 3c. детерминированный валидатор реально исполняется; символический — нет
    run = deterministic_run("validate-references + validate-claims")
    expect("детерминированный валидатор исполнен (pass на чистом пакете)",
           run is not None and run[0] == "pass")
    expect("символический валидатор не выдумывает вердикт (нужен evidence)",
           deterministic_run("validate-intake") is None)

    # 4. частичный evidence -> всё ещё blocked по недостающему гейту
    r2 = evaluate("QUICK", {"intake_completeness": {"status": "pass",
                                                    "provided": ["classified_type", "size", "risk"]}})
    expect("QUICK частичный evidence -> blocked на implementation_verification",
           r2["blocked"] and r2["unmet_gates"] == ["implementation_verification"])

    # 5. override снимает блокировку по гейту (records override)
    r3 = evaluate("QUICK", {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "fail",
                                        "override": {"by": "human:lead", "reason": "hotfix, verified manually"}}})
    expect("override снимает блокировку", r3["blocked"] is False)

    # 6. каждый gate-result соответствует ключам схемы (additionalProperties:false)
    schema_ok = all(set(g).issubset(_ALLOWED_KEYS) and
                    {"schema_version", "gate", "status", "blocking", "owner", "review_mode"}.issubset(g)
                    for g in r0["gate_results"])
    expect("gate-result по схеме (ключи разрешены, required присутствуют)", schema_ok)

    # 7. все workflow-контракты ссылаются только на существующие гейты
    workflows = load_workflows()
    all_ok = True
    for wid in workflows:
        try:
            evaluate(wid)
        except SystemExit:
            all_ok = False
    expect("все контракты резолвят свои quality_gates", all_ok)

    print("gate_executor selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    if len(argv) > 1:
        wf = argv[1]
        evidence = {}
        if len(argv) > 2:
            evidence = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(evaluate(wf, evidence), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
