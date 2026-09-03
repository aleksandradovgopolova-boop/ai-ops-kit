"""Гранулярные тесты context_compiler (мигрировано из test_context_compiler_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.context.context_compiler import (
    CONTEXT_BUDGET_DEFAULT,
    MODEL_CONTEXT,
    Path,
    build_payload,
    compile_bundle,
)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
    return tmp_path


@pytest.fixture
def eng_task():
    return {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"],
            "task_text": "отрефакторить модуль расчёта"}


@pytest.mark.unit
class TestCompileBundle:
    def test_kind_context_bundle(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert b["kind"] == "ContextBundle"

    def test_agents_included(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert len(b["included"]["agents"]) > 0

    def test_included_reasons_for_agents(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert all(a in b["included_reasons"]["agents"] for a in b["included"]["agents"])

    def test_engineering_includes_rules(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert {"core", "engineering"} <= set(b["included"]["rules"])

    def test_repository_context_node(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert any("node" in r for r in b["included"]["repository_context"])

    def test_excluded_with_reasons(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert b["excluded"] and all("reason" in e and "source" in e for e in b["excluded"])

    def test_estimated_tokens_positive(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert b["estimated_tokens"] > 0

    def test_context_budget_present(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        assert b["context_budget"] == CONTEXT_BUDGET_DEFAULT

    def test_reproducibility(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        b2 = compile_bundle(eng_task, repo)
        assert b["included"] == b2["included"] and b["excluded"] == b2["excluded"]

    def test_overflow_small_budget(self, repo, eng_task):
        compile_bundle(eng_task, repo)
        b_of = compile_bundle(eng_task, repo, context_budget=10)
        assert b_of["overflow"] is True

    def test_overflow_open_question(self, repo, eng_task):
        b = compile_bundle(eng_task, repo)
        b_of = compile_bundle(eng_task, repo, context_budget=10)
        assert any("бюджет" in q for q in b_of["open_questions"])
        assert b_of["included"]["agents"] == b["included"]["agents"]

    def test_quick_lighter_than_engineering(self, repo):
        eng = compile_bundle(
            {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"],
             "task_text": "отрефакторить модуль расчёта"}, repo)
        q = compile_bundle(
            {"task_type": "QUICK", "risk": "low", "affected_areas": ["core"],
             "task_text": "мелкая правка"}, repo)
        assert len(q["included"]["rules"]) <= len(eng["included"]["rules"])

    def test_product_includes_product_rules(self, repo):
        p = compile_bundle(
            {"task_type": "PRODUCT", "risk": "medium", "affected_areas": ["catalog"],
             "measurable_behavior": True, "task_text": "новая фича"}, repo)
        assert "product" in p["included"]["rules"]


@pytest.mark.unit
class TestBuildPayload:
    def test_payload_kind_and_text(self, repo, eng_task):
        pay = build_payload(eng_task, repo)
        assert pay["kind"] == "ContextPayload" and len(pay["text"]) > 0

    def test_payload_contains_real_rules(self, repo, eng_task):
        pay = build_payload(eng_task, repo)
        assert "=== [rule]" in pay["text"] and pay["payload_tokens"] > 0

    def test_payload_items_have_required_fields(self, repo, eng_task):
        pay = build_payload(eng_task, repo)
        assert all({"hash", "revision", "reason", "tokens", "source"} <= set(i)
                   for i in pay["included_items"])

    def test_payload_budget_with_reserves(self, repo, eng_task):
        pay = build_payload(eng_task, repo)
        assert pay["payload_budget"] < pay["context_budget"]
        assert pay["output_reserve"] > 0 and pay["tool_loop_reserve"] > 0

    def test_payload_overflow_excludes_for_budget(self, repo, eng_task):
        pay_of = build_payload(eng_task, repo, context_budget=60)
        assert pay_of["excluded_for_budget"]
        assert any(i["kind"] == "project_context" for i in pay_of["included_items"])

    def test_payload_model_window(self, repo, eng_task):
        pay_m = build_payload(eng_task, repo, context_budget=500_000, model="deepseek-chat")
        assert pay_m["context_budget"] == MODEL_CONTEXT["deepseek-chat"]
