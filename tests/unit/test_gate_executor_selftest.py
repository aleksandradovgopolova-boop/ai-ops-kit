"""Селфтест gate_executor, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from gate_executor import (  # noqa: F401 — имена, которые использует тело
    Path,
    _ALLOWED_KEYS,
    _freshness_run,
    classify,
    collect_evidence,
    deterministic_run,
    evaluate,
    evaluate_gate,
    json,
    load_gates,
    load_workflows,
    override_effective,
    validate_evidence,
    validate_evidence_schemas,
)


@pytest.mark.slow
def test_gate_executor_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    gates = load_gates()
    # 1. классификация типов
    expect("intake_completeness -> deterministic", classify(gates["intake_completeness"]) == "deterministic")
    expect("code_review -> ai-review", classify(gates["code_review"]) == "ai-review")
    expect("security -> human-approval при активном условии (v2.55)",
           classify(gates["security"], {"security_surface_changed": True}) == "human-approval")

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
            "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
    }
    r1 = evaluate("QUICK", good)
    expect("QUICK с подтверждённым evidence -> не blocked", r1["blocked"] is False)

    # v2.54 (finding аудита): gate_ids override — прогон оценивает ГЕЙТЫ RUNPLAN (base+треки),
    # а не только quality_gates контракта. Добавляем трековый гейт -> он реально оценивается.
    rp_gates = list(load_workflows()["QUICK"].get("quality_gates", [])) + ["ux_review"]
    r_rp = evaluate("QUICK", good, gate_ids=rp_gates)
    expect("gate_ids override: ux_review (трек) попал в оценку",
           "ux_review" in r_rp["evaluated_gates"])
    expect("gate_ids override: ux_review без evidence блокирует прогон",
           "ux_review" in r_rp["unmet_gates"] and r_rp["blocked"] is True)

    # v2.61 «умное ослабление»: неприменимый флаг освобождается (записан в warnings), не фабрикуется
    partial = {"implementation_verification": {"status": "pass",
        "provided": ["build_passed", "tests_passed", "tested_revision"]}}  # нет lint/typecheck
    r_strict = evaluate("QUICK", partial)
    expect("без освобождения: недостающие lint/typecheck блокируют",
           "implementation_verification" in r_strict["unmet_gates"])
    r_exempt = evaluate("QUICK", partial,
                        not_applicable={"implementation_verification": {"lint_passed", "typecheck_passed"}})
    expect("с освобождением (нет линтера/тайпчекера в стеке): гейт не блокирует",
           "implementation_verification" not in r_exempt["unmet_gates"])
    iv = next(g for g in r_exempt["gate_results"] if g["gate"] == "implementation_verification")
    expect("освобождение ЗАПИСАНО в warnings (не тихо)",
           any("освобождено" in w for w in iv.get("warnings", [])))

    # v2.55 (finding аудита): условный human_approval (security required_when) НЕ безусловен
    sec_gate = load_gates()["security"]
    expect("security с required_when + нет сигналов -> НЕ human-approval (не ложная блокировка)",
           classify(sec_gate, None) != "human-approval")
    expect("security при secret_boundary_change/security_surface_changed -> human-approval",
           classify(sec_gate, {"security_surface_changed": True}) == "human-approval")
    # v2.107 (finding аудита): единый сигнал secret_boundary (его используют spec_levels/security_pack)
    # тоже поднимает human-approval — дрейф имён устранён
    expect("security при secret_boundary (имя из spec/pack) -> human-approval",
           classify(sec_gate, {"secret_boundary": True}) == "human-approval")
    expect("security при destructive-сигнале -> human-approval",
           classify(sec_gate, {"destructive": True}) == "human-approval")
    expect("безусловный human_approval:true всегда -> human-approval",
           classify({"human_approval": True}, None) == "human-approval")

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

    # 3d2. v3.15.0: гейт с required_when применим только при архитектурном сигнале
    _arch_gate = {"id": "architecture_review", "blocking": True, "review_mode": "read-only",
                  "responsible_role": "architecture-reviewer",
                  "required_when": ["architecture_change", "data_migration"]}
    r_na = evaluate_gate("architecture_review", _arch_gate, {}, signals={})
    expect("architecture_review без сигнала -> not_applicable, не блок",
           r_na["status"] == "pass" and r_na["blocking"] is False and "not_applicable" in r_na.get("scope", []))
    r_active = evaluate_gate("architecture_review", _arch_gate, {}, signals={"data_migration": True})
    expect("architecture_review при сигнале + без evidence -> fail (обязательный судья)",
           r_active["status"] == "fail" and r_active["blocking"] is True)

    # 3d. v3.12.0: freshness-гейт проверяет контекст РЕПОЗИТОРИЯ (не селфтест кита)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td) / ".ai/project/context"
        ctx.mkdir(parents=True)
        (ctx / "ProductStatus.md").write_text(
            "---\nstability: volatile\nreviewed_at: 2020-01-01\n---\n# stale\n", encoding="utf-8")
        st, checks, _ = _freshness_run(td)
        expect("freshness: протухший ProductStatus.md репо -> warn + имя файла",
               st == "warn" and any("stale:ProductStatus.md" in c["id"] for c in checks))
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td) / ".ai/project/context"
        ctx.mkdir(parents=True)
        (ctx / "ProductStatus.md").write_text(
            "---\nstability: volatile\nreviewed_at: 2999-01-01\n---\n# fresh\n", encoding="utf-8")
        st, _, _ = _freshness_run(td)
        expect("freshness: свежий контекст репо -> pass", st == "pass")
    with tempfile.TemporaryDirectory() as td:
        st, checks, _ = _freshness_run(td)
        expect("freshness: нет контекста репо -> warn (пробел виден)",
               st == "warn" and any("repo_context_present" in c["id"] for c in checks))

    # 4. частичный evidence -> всё ещё blocked по недостающему гейту
    r2 = evaluate("QUICK", {"intake_completeness": {"status": "pass",
                                                    "provided": ["classified_type", "size", "risk"]}})
    expect("QUICK частичный evidence -> blocked на implementation_verification",
           r2["blocked"] and r2["unmet_gates"] == ["implementation_verification"])

    # 5. override уважает политику гейта (v2.16): forbidden не обходится, allowed — да
    expect("bypass_policy: forbidden -> override НЕ снимает блок",
           override_effective(gates["implementation_verification"],
                              {"by": "human:lead", "reason": "hotfix"}) is False)
    expect("override_policy.allowed -> override снимает блок (requirements)",
           override_effective(gates["requirements"],
                              {"by": "human:lead", "reason": "accepted"}) is True)
    expect("нет явной override_policy -> обход не разрешён",
           override_effective(gates["specification"], {"by": "x", "reason": "y"}) is False)
    # на уровне workflow: fail forbidden-гейта с override ОСТАЁТСЯ blocked
    r3 = evaluate("QUICK", {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "fail",
                                        "override": {"by": "human:lead", "reason": "hotfix, verified manually"}}})
    expect("forbidden-гейт с override остаётся blocked", r3["blocked"] is True)

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

    # 8. валидация формы evidence по схеме
    expect("валидный evidence -> без ошибок", validate_evidence({"g": {"status": "pass"}}) == [])
    expect("невалидный status -> ошибка", validate_evidence({"g": {"status": "maybe"}}) != [])
    expect("неизвестное поле -> ошибка", validate_evidence({"g": {"status": "pass", "foo": 1}}) != [])
    expect("checks без status -> ошибка",
           validate_evidence({"g": {"status": "pass", "checks": [{"id": "x"}]}}) != [])

    # 9. сбор evidence из вердиктов reviewer-стадий (--collect-evidence)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        (rd / "stage-intake.md").write_text("Intake\nstatus: passed\n", encoding="utf-8")
        (rd / "stage-local-verify.md").write_text("# Final Verification\nИтог: pass\n", encoding="utf-8")
        collected = collect_evidence("QUICK", rd)
        expect("collect: вердикт pass извлечён (статус) для гейтов QUICK",
               collected.get("intake_completeness", {}).get("status") == "pass"
               and collected.get("implementation_verification", {}).get("status") == "pass")
        expect("collect: reviewer НЕ фабрикует детерминированный evidence (provided пуст)",
               not collected.get("implementation_verification", {}).get("provided"))
        expect("collect: слова ревьюера НЕ закрывают детерминированные гейты -> QUICK blocked",
               evaluate("QUICK", collected)["blocked"] is True)
        (rd / "stage-local-verify.md").write_text("Recommendation: FAIL\n", encoding="utf-8")
        expect("collect: вердикт fail -> гейт блокирует",
               evaluate("QUICK", collect_evidence("QUICK", rd))["blocked"] is True)

    # 9b. структурный reviewer-result (v2.33) — источник истины, приоритет над markdown
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        # markdown говорит pass, но структурный json говорит fail с блокером -> fail побеждает
        (rd / "stage-local-verify.md").write_text("Итог: pass\n", encoding="utf-8")
        (rd / "stage-local-verify.reviewer.json").write_text(json.dumps({
            "schema_version": 1, "kind": "reviewer-result", "gate": "implementation_verification",
            "status": "fail", "checks": [{"id": "tests", "status": "fail"}],
            "blockers": ["2 теста упали на ревизии abc123"]}), encoding="utf-8")
        col = collect_evidence("QUICK", rd)
        expect("structured reviewer-result побеждает markdown (fail, не pass)",
               col.get("implementation_verification", {}).get("status") == "fail")
        expect("structured fail -> QUICK blocked", evaluate("QUICK", col)["blocked"] is True)

    # 10. well-formedness evidence_schema (v2.33): типы полей из словаря
    expect("evidence_schema гейтов well-formed", validate_evidence_schemas() == [])
    expect("битый тип в evidence_schema -> ошибка",
           validate_evidence_schemas({"g": {"evidence_schema": {"build": {"exit_code": "bogus"}}}}) != [])

    assert ok, "перенесённый селфтест gate_executor: см. строки FAIL в выводе"
