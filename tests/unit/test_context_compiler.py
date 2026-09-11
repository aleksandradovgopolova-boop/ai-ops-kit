"""Гранулярные тесты context_compiler (мигрировано из test_context_compiler_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import functools

import pytest

from ai_ops_kit.context.context_compiler import (
    CONTEXT_BUDGET_DEFAULT,
    MODEL_CONTEXT,
    Path,
)
from ai_ops_kit.context.context_compiler import build_payload as _build_payload
from ai_ops_kit.context.context_compiler import compile_bundle as _compile_bundle
from ai_ops_kit.engine.run_plan import build_plan as _build_plan

# K2: context не строит RunPlan сам — план инъецируется. В тестах строитель настоящий
# (engine.run_plan.build_plan), поэтому подставляем его по умолчанию, а вызовы остаются как есть.
compile_bundle = functools.partial(_compile_bundle, build_plan=_build_plan)
build_payload = functools.partial(_build_payload, build_plan=_build_plan)


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


@pytest.mark.unit
class TestStorybookNavigationWiring:
    """#613: живой потребитель storybook_query — при ui_changed навигация по дизайн-системе
    дочки попадает в контекст пишущего агента."""

    def _repo_with_storybook(self, tmp_path):
        import json as _json
        (tmp_path / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        (tmp_path / "storybook-static").mkdir()
        (tmp_path / "storybook-static" / "index.json").write_text(_json.dumps({"v": 5, "entries": {
            "ui-button--default": {"type": "story", "id": "ui-button--default", "title": "UI/Button",
                "name": "Default", "importPath": "./src/ui/Button.stories.tsx"}}}), encoding="utf-8")
        return tmp_path

    def test_ui_changed_injects_storybook_navigation(self, tmp_path):
        root = self._repo_with_storybook(tmp_path)
        p = build_payload({"task_text": "поправить кнопку", "ui_changed": True,
                           "changed_files": ["src/ui/Button.tsx"]}, root)
        assert "storybook-navigation" in p["text"]
        assert "UI/Button" in p["text"]
        assert any(i["kind"] == "storybook" for i in p["included_items"])

    def test_no_storybook_section_without_ui_signal(self, tmp_path):
        root = self._repo_with_storybook(tmp_path)
        p = build_payload({"task_text": "починить бэкенд"}, root)   # ui_changed отсутствует
        assert "storybook-navigation" not in p["text"]

    def test_no_storybook_section_when_child_has_no_storybook(self, repo):
        p = build_payload({"task_text": "поправить кнопку", "ui_changed": True}, repo)
        assert "storybook-navigation" not in p["text"]   # не шумим на не-Storybook дочке


# ─── #678: генератор сам проверяет форму собранного ContextBundle (validate-and-warn) ──────────

class TestCompileBundleValidatesItsOwnShape:
    def test_valid_bundle_emits_no_warning_and_check_is_green(self, repo, eng_task):
        """Реальный compile_bundle -> валидный ContextBundle: ни предупреждения, ни ошибок check()."""
        import warnings as _w

        from ai_ops_kit.checks.context_bundle import check
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            b = compile_bundle(eng_task, repo)
        assert not [x for x in caught if issubclass(x.category, RuntimeWarning)], \
            [str(x.message) for x in caught]
        assert check(b) == []

    def test_overflow_bundle_also_green(self, repo, eng_task):
        """Ветка overflow (крохотный бюджет) тоже даёт валидный bundle — без ложного warn."""
        import warnings as _w

        from ai_ops_kit.checks.context_bundle import check
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            b = compile_bundle(eng_task, repo, context_budget=10)
        assert not [x for x in caught if issubclass(x.category, RuntimeWarning)], \
            [str(x.message) for x in caught]
        assert check(b) == []

    def test_warn_helper_fires_on_malformed_bundle(self):
        """Битый ContextBundle -> генератор ГРОМКО предупреждает (bundle становится payload модели)."""
        from ai_ops_kit.context.context_compiler import _warn_if_bundle_malformed
        bad = {"kind": "ContextBundle", "workitem_id": "x", "included": "не объект",
               "excluded": [], "estimated_tokens": 1, "context_budget": 1}
        with pytest.warns(RuntimeWarning, match="нарушением формы"):
            _warn_if_bundle_malformed(bad)


@pytest.mark.unit
class TestContextDoesNotImportEngine:
    """K2-развязка слоёв: context не строит RunPlan сам и не импортирует engine."""

    def test_compile_bundle_requires_plan_or_builder(self, repo, eng_task):
        """Без plan и без build_plan — явная ошибка, а не тихий импорт engine."""
        with pytest.raises(ValueError, match="context не импортирует engine"):
            _compile_bundle(eng_task, repo)

    def test_source_has_no_engine_import(self):
        """В исходнике context_compiler нет ссылки на engine — ни статической, ни динамической."""
        src = (Path(__file__).resolve().parents[2] / "ai_ops_kit" / "context"
               / "context_compiler.py").read_text(encoding="utf-8")
        assert "ai_ops_kit.engine" not in src, "context_compiler не должен упоминать engine"
