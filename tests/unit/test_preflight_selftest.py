"""Селфтест preflight, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from preflight import (  # noqa: F401 — имена, которые использует тело
    Path,
    approvals,
    assess,
)


@pytest.mark.slow
def test_preflight_selftest():
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
        # v2.120: голый decomposition_confirmed БОЛЬШЕ не пускает блоб -> всё ещё blocked
        pf_a2 = assess({"task_type": "ENGINEERING", "decomposition_confirmed": True}, root, "w",
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("v2.120 preflight: голый decomposition_confirmed -> НЕ пускает блоб (blocked)", pf_a2["blocked"])
        # выбран СУЩЕСТВУЮЩИЙ пакет из плана -> atomic-гейт пройден (author=True снимает spec-блок heavy)
        pf_a3 = assess({"task_type": "ENGINEERING", "work_package_id": "a"}, root, "w", author=True,
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("preflight: выбран существующий пакет (id в плане) -> atomic-гейт пройден",
               pf_a3["checks"]["atomic"]["ok"])
        # v2.120: ВЫМЫШЛЕННЫЙ id (нет в плане) -> blocked
        pf_a4 = assess({"task_type": "ENGINEERING", "work_package_id": "ghost"}, root, "w",
                       payload=good_payload, spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("v2.120 preflight: вымышленный work_package_id (нет в плане) -> blocked",
               pf_a4["blocked"] and pf_a4["checks"]["atomic"]["selected_valid"] is False)
        # id из авторитетного плана sequence-исполнителя -> пройден
        pf_a5 = assess({"task_type": "ENGINEERING", "work_package_id": "seq-2",
                        "_sequence_plan_ids": ["seq-1", "seq-2"]}, root, "w", payload=good_payload, author=True,
                       spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=wp)
        expect("v2.120 preflight: id из плана sequence-исполнителя -> atomic-гейт пройден",
               pf_a5["checks"]["atomic"]["ok"])

        # ── v2.121 (P1.1): спека обязательна ДО tool loop для heavy (author-or-spec) ──────────────
        atomic_wp = {"should_decompose": False}
        # ENGINEERING без спеки и без --author -> блок (spec-first до реализации)
        pf_h1 = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                       root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=atomic_wp)
        expect("v2.121 preflight: heavy без спеки и без --author -> blocked (spec-first)",
               pf_h1["blocked"] and any("spec-first" in r and "ДО реализации" in r for r in pf_h1["reasons"]))
        # тот же кейс c --author -> spec-блок снят (движок авторизует спеку пре-стадией)
        pf_h2 = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                       root, "w", payload=good_payload, author=True,
                       spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=atomic_wp)
        expect("v2.121 preflight: heavy без спеки, но с --author -> spec-гейт пройден",
               pf_h2["checks"]["spec"]["ok"] and not any("spec-first" in r for r in pf_h2["reasons"]))
        # v3.8.3: reevaluate_only обходит build-preconditions (spec-first/atomic), НО НЕ approvals
        pf_re = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                       root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=atomic_wp,
                       reevaluate_only=True)
        expect("v3.8.3 preflight: reevaluate_only -> spec-first НЕ блокирует (build-precondition неприменим)",
               not any("spec-first" in r for r in pf_re["reasons"])
               and pf_re["checks"]["spec"].get("skipped_reevaluate") is True)
        pf_re2 = assess({"task_type": "ENGINEERING", "destructive": True}, root, "w", payload=good_payload,
                        spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=atomic_wp,
                        reevaluate_only=True)
        expect("v3.8.3 preflight: reevaluate_only НЕ обходит approvals (destructive без записи -> blocked)",
               pf_re2["blocked"] and any("human-approval" in r for r in pf_re2["reasons"]))
        # QUICK без спеки -> НЕ требует спеку (light)
        pf_q = assess({"task_type": "QUICK", "size": "small", "affected_areas": ["core"]},
                      root, "w", payload=good_payload,
                      spec_cov={"spec_artifact": False, "blocking_missing": []}, work_pkg=atomic_wp)
        expect("v2.121 preflight: QUICK без спеки -> НЕ блокирует (light)",
               pf_q["ok"] and pf_q["checks"]["spec"]["ok"])
        # heavy с ПОЛНОЙ спекой на диске -> ok даже без --author
        pf_h3 = assess({"task_type": "ENGINEERING", "size": "small", "affected_areas": ["core"]},
                       root, "w", payload=good_payload,
                       spec_cov={"spec_artifact": True, "blocking_missing": []}, work_pkg=atomic_wp)
        expect("v2.121 preflight: heavy с полной спекой -> spec-гейт пройден без --author",
               pf_h3["checks"]["spec"]["ok"])

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
        # v3.37: привязка обязана быть СВЕРЯЕМОЙ. Прежде здесь стояло binds_to="p" при отсутствии плана
        # на диске — сверять было не с чем, и проверка молча пропускала запись. Кладём план и связываем
        # с его реальным хэшем: сценарий тот же, но теперь он проверяет то, что обещает.
        _fdir = root / "features" / "w"
        _fdir.mkdir(parents=True, exist_ok=True)
        (_fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a]\n", encoding="utf-8")
        approvals.write_record(root, "w", "secrets", "u@x", "config", "согласовано", created_at="2026-07-18",
                               expires_at="2027-01-01T00:00:00Z", risk="secret", source="user")
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

    # --- v3.21.0 EngOps срез 3: экономическая граница ДО tool loop ---------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # author=True снимает spec-first, чтобы единственной переменной осталась ЭКОНОМИКА:
        # иначе блок приходил бы от отсутствия спеки, и тест был бы зелёным вхолостую.
        base_kw = dict(payload=good_payload, author=True,
                       spec_cov={"spec_artifact": False, "blocking_missing": []},
                       work_pkg={"should_decompose": False})

        # positive: истории нет -> прогон НЕ блокируется, но статус честно unavailable (не «бесплатно»)
        pf_e0 = assess({"task_type": "ENGINEERING"}, root, "we", **base_kw)
        eco = pf_e0["checks"].get("economic_budget") or {}
        expect("preflight: экономическая проверка присутствует в checks", bool(eco))
        expect("preflight: без экономических данных прогон в целом не блокируется "
               "(переменная изолирована — spec-first снят author=True)", not pf_e0["blocked"])
        expect("preflight: нет истории -> не блок, статус unavailable (не выдаём за ноль)",
               eco.get("ok") and eco.get("verdict") == "proceed_unknown"
               and eco.get("estimate_status") == "unavailable"
               and eco.get("cost_median") is None)

        # side-effect proof: ledger действительно записан и читается -> только потом проверяем реакцию
        import usage_ledger as _ul
        for wid, cost in (("WI-a", 3.0), ("WI-b", 9.0)):
            _ul.append(root, wid, [{"role": "writer", "cost": cost, "cost_status": "measured",
                                    "usage_status": "measured", "input_tokens": 10,
                                    "output_tokens": 10}])
        import economic_preflight as _ep
        _est = _ep.estimate(root)
        expect("preflight: ledger реально записан (side-effect proof до проверки гейта)",
               _est["status"] == "measured_history" and _est["sample_tasks"] == 2
               and _est["cost_max"] == 9.0)

        # fail-closed: худший прогон (9.0) дороже лимита RunPlan (5) -> БЛОК до tool loop
        pf_e1 = assess({"task_type": "ENGINEERING"}, root, "we",
                       plan={"execution_budget": {"max_cost": 5}}, **base_kw)
        expect("preflight: худший сравнимый прогон дороже лимита -> blocked ДО запуска модели",
               pf_e1["blocked"] and not pf_e1["checks"]["economic_budget"]["ok"]
               and any("economic-preflight" in r for r in pf_e1["reasons"]))
        expect("preflight: блокирует ИМЕННО экономика (других причин в reasons нет)",
               len(pf_e1["reasons"]) == 1)

        # в пределах лимита -> проходит
        pf_e2 = assess({"task_type": "ENGINEERING"}, root, "we",
                       plan={"execution_budget": {"max_cost": 20}}, **base_kw)
        expect("preflight: в пределах лимита -> экономика не блокирует",
               pf_e2["checks"]["economic_budget"]["ok"] and not pf_e2["blocked"])

        # лимита нет вовсе -> не выдумываем и не блокируем
        expect("preflight: без execution_budget экономика не блокирует",
               assess({"task_type": "ENGINEERING"}, root, "we", **base_kw)
               ["checks"]["economic_budget"]["ok"])

        # reevaluate_only: переоценка уже построенной фичи — build-precondition не применяется
        pf_e3 = assess({"task_type": "ENGINEERING"}, root, "we",
                       plan={"execution_budget": {"max_cost": 5}}, reevaluate_only=True, **base_kw)
        expect("preflight: reevaluate_only -> экономическая проверка НЕ применяется",
               "economic_budget" not in pf_e3["checks"] and not pf_e3["blocked"])

    assert ok, "перенесённый селфтест preflight: см. строки FAIL в выводе"
