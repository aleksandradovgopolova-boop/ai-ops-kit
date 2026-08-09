"""Селфтест context_compiler, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_compiler import (  # noqa: F401 — имена, которые использует тело
    CONTEXT_BUDGET_DEFAULT,
    MODEL_CONTEXT,
    Path,
    build_payload,
    compile_bundle,
)


@pytest.mark.slow
def test_context_compiler_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        eng = {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"],
               "task_text": "отрефакторить модуль расчёта"}
        b = compile_bundle(eng, root)
        expect("kind=ContextBundle", b["kind"] == "ContextBundle")
        expect("включены агенты из RunPlan (непусто)", len(b["included"]["agents"]) > 0)
        expect("для каждого включённого агента есть причина",
               all(a in b["included_reasons"]["agents"] for a in b["included"]["agents"]))
        expect("ENGINEERING включает правила engineering+core",
               {"core", "engineering"} <= set(b["included"]["rules"]))
        expect("repository_context определил node", any("node" in r for r in b["included"]["repository_context"]))
        expect("excluded непуст и с причинами",
               b["excluded"] and all("reason" in e and "source" in e for e in b["excluded"]))
        expect("estimated_tokens измерен ДО модели (>0)", b["estimated_tokens"] > 0)
        expect("context_budget присутствует", b["context_budget"] == CONTEXT_BUDGET_DEFAULT)
        # воспроизводимость: тот же вход -> тот же пакет (без времени/рандома; revision может отличаться в не-git)
        b2 = compile_bundle(eng, root)
        expect("воспроизводимость: included идентичен при тех же входах",
               b["included"] == b2["included"] and b["excluded"] == b2["excluded"])

        # overflow: маленький бюджет -> overflow=True + open_question, контекст НЕ обрезан
        b_of = compile_bundle(eng, root, context_budget=10)
        expect("overflow: бюджет превышен -> overflow=True", b_of["overflow"] is True)
        expect("overflow: поднят open_question (не обрезано молча)",
               any("бюджет" in q for q in b_of["open_questions"])
               and b_of["included"]["agents"] == b["included"]["agents"])

        # QUICK легче ENGINEERING по правилам (меньше категорий)
        q = compile_bundle({"task_type": "QUICK", "risk": "low", "affected_areas": ["core"], "task_text": "мелкая правка"}, root)
        expect("QUICK: правил не больше, чем у ENGINEERING (минимальность)",
               len(q["included"]["rules"]) <= len(b["included"]["rules"]))

        # PRODUCT включает product-правила
        p = compile_bundle({"task_type": "PRODUCT", "risk": "medium", "affected_areas": ["catalog"],
                            "measurable_behavior": True, "task_text": "новая фича"}, root)
        expect("PRODUCT включает правила product", "product" in p["included"]["rules"])

        # v2.108 Operational Context: build_payload даёт РЕАЛЬНЫЙ текст для prompt + манифест
        pay = build_payload(eng, root)
        expect("payload: kind=ContextPayload + непустой text", pay["kind"] == "ContextPayload"
               and len(pay["text"]) > 0)
        expect("payload: содержит РЕАЛЬНОЕ содержимое правил (не только пути)",
               "=== [rule]" in pay["text"] and pay["payload_tokens"] > 0)
        expect("payload: у каждого элемента hash+revision+reason+tokens",
               all({"hash", "revision", "reason", "tokens", "source"} <= set(i) for i in pay["included_items"]))
        expect("payload: бюджет с резервами (output+tool-loop < полный бюджет)",
               pay["payload_budget"] < pay["context_budget"]
               and pay["output_reserve"] > 0 and pay["tool_loop_reserve"] > 0)
        # маленький бюджет -> вытеснение фиксируется (не молча), задача остаётся
        pay_of = build_payload(eng, root, context_budget=60)
        expect("payload: превышение бюджета -> excluded_for_budget непуст (не молча), task остался",
               pay_of["excluded_for_budget"]
               and any(i["kind"] == "project_context" for i in pay_of["included_items"]))
        # модель сужает бюджет по окну
        pay_m = build_payload(eng, root, context_budget=500_000, model="deepseek-chat")
        expect("payload: окно модели сужает бюджет (deepseek-chat=64k)",
               pay_m["context_budget"] == MODEL_CONTEXT["deepseek-chat"])

    assert ok, "перенесённый селфтест context_compiler: см. строки FAIL в выводе"
