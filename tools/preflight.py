#!/usr/bin/env python3
"""Preflight Truth — проверки ДО запуска модели (v2.115).

Аудит: Spec-First блокировал ДОСТАВКУ, а не РЕАЛИЗАЦИЮ — pipeline сначала гонял tool loop, писал код и
коммит, и лишь ПОТОМ проверял полноту спеки. Это delivery-gate, не Spec-First. Здесь — единый preflight,
который выполняется ДО tool loop; при провале модель НЕ запускается, правки/коммит НЕ создаются.

Порядок (fail-closed):
  classification -> ContextPayload собран -> spec достаточна -> задача атомарна ИЛИ декомпозиция
  подтверждена -> context budget не превышен -> необходимые human approvals присутствуют -> только
  потом tool loop.

Инварианты честности:
  * неполная (существующая) спека -> блок ДО реализации (ноль вызовов tool loop, ноль коммитов);
  * context overflow -> блок ДО исполнения;
  * неатомарная задача -> блок, пока человек не подтвердит декомпозицию ИЛИ не выберет один пакет;
  * ошибки Context Compiler/Spec/Planner -> fail-closed для ENGINEERING/PRODUCT/CRITICAL;
  * доменные human_approval_conditions исполняются через ApprovalRecord (не boolean).

Использование:
  preflight.py --selftest
"""

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "tools"))

import spec_levels   # noqa: E402
import approvals     # noqa: E402

# Уровни, для которых слой контекста обязан быть здоров (ошибки -> fail-closed, не «продолжаем молча»).
_HEAVY = {"ENGINEERING", "PRODUCT", "CRITICAL", "AI_FEATURE", "RESEARCH"}


def assess(signals, child_root, wid, plan=None, bundle=None, payload=None,
           spec_cov=None, work_pkg=None, lifecycle_errors=None, domains=None):
    """-> {kind, ok, blocked, checks{...}, reasons[]}. Детерминированно, без модели и без правок."""
    signals = dict(signals or {})
    child_root = Path(child_root)
    tt = (signals.get("task_type") or (plan or {}).get("base_workflow") or "QUICK").upper()
    heavy = tt in _HEAVY
    lifecycle_errors = list(lifecycle_errors or [])
    checks, reasons = {}, []

    def block(reason):
        reasons.append(reason)

    # 1. classification
    ok_class = bool(tt)
    checks["classification"] = {"ok": ok_class, "task_type": tt}
    if not ok_class:
        block("classification: не удалось определить тип задачи")

    # 2. ContextPayload собран (для heavy — обязателен; ошибка сборки -> fail-closed)
    payload_ok = payload is not None and bool((payload or {}).get("text"))
    checks["context_payload"] = {"ok": payload_ok or (not heavy), "built": payload is not None}
    if heavy and not payload_ok:
        block("context_payload: compiled payload не собран для heavy-задачи (fail-closed)")

    # 3. spec достаточна — существующая, но неполная спека НЕ пускает в реализацию (главный фикс #1)
    spec_artifact = bool((spec_cov or {}).get("spec_artifact"))
    spec_missing = list((spec_cov or {}).get("blocking_missing") or [])
    spec_ok = not (spec_artifact and spec_missing)
    checks["spec"] = {"ok": spec_ok, "artifact_present": spec_artifact, "missing": spec_missing}
    if not spec_ok:
        block(f"spec-first: спека features/{wid}/spec.yaml существует, но неполна "
              f"(не заполнено: {', '.join(spec_missing)}) — реализация не начинается")

    # 4. атомарность / подтверждённая декомпозиция
    should_decompose = bool((work_pkg or {}).get("should_decompose"))
    confirmed = bool(signals.get("decomposition_confirmed") or signals.get("work_package_id"))
    atomic_ok = (not should_decompose) or confirmed
    checks["atomic"] = {"ok": atomic_ok, "should_decompose": should_decompose,
                        "confirmed": confirmed,
                        "selected_package": signals.get("work_package_id")}
    if not atomic_ok:
        n = len((work_pkg or {}).get("work_packages") or [])
        block(f"atomic-planning: задача не атомарна ({n} пакетов) — подтверди декомпозицию "
              f"(decomposition_confirmed) ИЛИ выбери один пакет (work_package_id) до исполнения")

    # 5. context budget не превышен -> блок ДО исполнения
    overflow = bool((bundle or {}).get("overflow"))
    checks["context_budget"] = {"ok": not overflow, "overflow": overflow}
    if overflow:
        block("context-budget: контекст задачи превышает бюджет — декомпозируй до исполнения")

    # 6. human approvals: доменные условия через ApprovalRecord (+ destructive)
    appr = approvals.check(signals, child_root, wid, domains=domains)
    missing = list(appr["missing"])
    # destructive не является security-доменом -> требуем отдельный ApprovalRecord "destructive"
    if signals.get("destructive"):
        recs = approvals.load_approvals(child_root, wid)
        has_destructive = any(r.get("approval") == "destructive" and approvals._record_valid(r) for r in recs)
        if not has_destructive:
            missing = missing + [{"domain": "destructive", "condition": "деструктивное действие",
                                  "trigger": "destructive", "reason": "нет валидного ApprovalRecord"}]
    approvals_ok = not missing
    checks["approvals"] = {"ok": approvals_ok, "required": appr["required"], "missing": missing}
    if not approvals_ok:
        block("human-approval: не хватает одобрений (ApprovalRecord): "
              + ", ".join(m["domain"] for m in missing))

    # 7. ошибки слоя контекста -> fail-closed для heavy
    lifecycle_ok = (not lifecycle_errors) or (not heavy)
    checks["lifecycle"] = {"ok": lifecycle_ok, "errors": lifecycle_errors}
    if heavy and lifecycle_errors:
        block("lifecycle: сбой слоя контекста (Compiler/Spec/Planner) для heavy-задачи -> "
              "fail-closed: " + "; ".join(lifecycle_errors))

    ok = not reasons
    return {"schema_version": 1, "kind": "PreflightTruth", "ok": ok, "blocked": not ok,
            "task_type": tt, "checks": checks, "reasons": reasons}


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        good_payload = {"text": "=== [rule] ..."}
        # чистый QUICK-атомарный -> ok
        pf = assess({"task_type": "QUICK"}, root, "w", payload=good_payload,
                    spec_cov={"spec_artifact": False, "blocking_missing": []},
                    work_pkg={"should_decompose": False})
        expect("preflight: чистый QUICK -> ok, не блокирует", pf["ok"] is True)

        # неполная существующая спека -> блок (ДО реализации)
        pf_spec = assess({"task_type": "QUICK"}, root, "w", payload=good_payload,
                         spec_cov={"spec_artifact": True, "blocking_missing": ["goal", "scope"]},
                         work_pkg={"should_decompose": False})
        expect("preflight: неполная спека -> blocked (spec-first ДО реализации)",
               pf_spec["blocked"] and any("spec-first" in r for r in pf_spec["reasons"]))

        # неатомарная без подтверждения -> блок; с подтверждением -> ok
        wp = {"should_decompose": True, "work_packages": [{"id": "a"}, {"id": "b"}]}
        pf_a = assess({"task_type": "ENGINEERING"}, root, "w", payload=good_payload,
                      spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("preflight: неатомарная без подтверждения -> blocked", pf_a["blocked"])
        pf_a2 = assess({"task_type": "ENGINEERING", "decomposition_confirmed": True}, root, "w",
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("preflight: декомпозиция подтверждена -> atomic-гейт пройден", pf_a2["checks"]["atomic"]["ok"])
        pf_a3 = assess({"task_type": "ENGINEERING", "work_package_id": "a"}, root, "w",
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("preflight: выбран один пакет -> atomic-гейт пройден", pf_a3["checks"]["atomic"]["ok"])

        # overflow -> блок
        pf_of = assess({"task_type": "ENGINEERING"}, root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False}, bundle={"overflow": True})
        expect("preflight: context overflow -> blocked", pf_of["blocked"]
               and any("context-budget" in r for r in pf_of["reasons"]))

        # payload не собран: heavy -> блок, QUICK -> ок
        pf_pe = assess({"task_type": "ENGINEERING"}, root, "w", payload=None,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False})
        expect("preflight: payload не собран + heavy -> blocked (fail-closed)", pf_pe["blocked"])
        pf_pq = assess({"task_type": "QUICK"}, root, "w", payload=None,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False})
        expect("preflight: payload не собран + QUICK -> не блокирует (light)", pf_pq["ok"])

        # lifecycle-ошибка: heavy -> блок, QUICK -> ок
        pf_le = assess({"task_type": "PRODUCT"}, root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False}, lifecycle_errors=["context_compiler: X"])
        expect("preflight: lifecycle-ошибка + heavy -> blocked (fail-closed)", pf_le["blocked"])
        pf_lq = assess({"task_type": "QUICK"}, root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False}, lifecycle_errors=["context_compiler: X"])
        expect("preflight: lifecycle-ошибка + QUICK -> не блокирует", pf_lq["ok"])

        # human approval: secret_boundary без ApprovalRecord -> блок; с записью -> ок
        pf_ap = assess({"task_type": "ENGINEERING", "secret_boundary": True}, root, "w",
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False})
        expect("preflight: secret_boundary без ApprovalRecord -> blocked (человек не пройден)",
               pf_ap["blocked"] and any("human-approval" in r for r in pf_ap["reasons"]))
        approvals.write_record(root, "w", "secrets", "u@x", "config", "согласовано", created_at="2026-07-18")
        pf_ap2 = assess({"task_type": "ENGINEERING", "secret_boundary": True}, root, "w",
                        payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []},
                        work_pkg={"should_decompose": False})
        expect("preflight: secret_boundary + валидный ApprovalRecord -> approvals пройдены",
               pf_ap2["checks"]["approvals"]["ok"])

        # destructive без записи -> блок
        pf_d = assess({"task_type": "ENGINEERING", "destructive": True}, root, "wd",
                      payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []},
                      work_pkg={"should_decompose": False})
        expect("preflight: destructive без ApprovalRecord -> blocked",
               pf_d["blocked"] and any(m["domain"] == "destructive" for m in pf_d["checks"]["approvals"]["missing"]))

    print("preflight selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
