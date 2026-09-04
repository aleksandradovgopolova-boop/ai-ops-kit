"""Юнит-тесты execution_pipeline: авторинг и spec-глубина."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _QUICK_SIG, _init_git, _init_python_repo


@pytest.mark.unit
class TestAuthoredContext:
    """Tests for _authored_context — spec-first context for implementation."""

    def test_empty_authored_returns_empty(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._authored_context([], child_root, "wid")
        assert result == ""

    def test_none_authored_returns_empty(self, child_root):
        _init_git(child_root)
        result = execution_pipeline._authored_context(None, child_root, "wid")
        assert result == ""


@pytest.mark.unit
class TestAuthorWithRetry:
    """Tests for _author_with_retry — retry logic for flaky author output."""

    def test_first_attempt_valid(self):
        from ai_ops_kit.shared import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        author = lambda prompt: "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud)
        assert errs == []
        assert data is not None
        assert data["kind"] == "requirements-artifact"

    def test_flaky_first_then_valid(self):
        from ai_ops_kit.shared import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        calls = {"n": 0}
        def flaky_author(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return "garbage not yaml"
            return "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(flaky_author, "prompt", check, bud)
        assert errs == []
        assert calls["n"] == 2

    def test_always_invalid(self):
        from ai_ops_kit.shared import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 5})
        author = lambda prompt: "always garbage"
        check = lambda data: ["invalid"] if not isinstance(data, dict) else ["still invalid"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud, attempts=2)
        assert len(errs) > 0

    def test_budget_exceeded(self):
        from ai_ops_kit.shared import budget as budget_mod
        bud = budget_mod.Budget.from_dict({"max_model_calls": 0})
        author = lambda prompt: "schema_version: 1\nkind: requirements-artifact\nrequirements:\n  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n"
        import validate_requirements_artifact as vra
        check = lambda data: vra.check(data) if isinstance(data, dict) else ["not a dict"]
        data, errs = execution_pipeline._author_with_retry(author, "prompt", check, bud)
        assert any("budget" in str(e) for e in errs)


@pytest.mark.unit
class TestRunAuthoring:
    """Tests for _run_authoring — artifact production pipeline."""

    def test_authoring_closes_requirements(self, child_root):
        _init_git(child_root)
        def author(prompt):
            if "requirements-artifact" in prompt:
                return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                        "  - id: R1\n    statement: test requirement\n"
                        "    acceptance:\n      - when x then y\n")
            return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                    "  - id: WP1\n    summary: test\n    depends_on: []\n"
                    "write_scope:\n  - src/\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements", "plan_readiness"], {}, "test-wid",
            "test task", {"max_model_calls": 10})
        assert "requirements" in gate_ev
        assert gate_ev["requirements"]["status"] == "pass"
        assert "plan_readiness" in gate_ev
        assert gate_ev["plan_readiness"]["status"] == "pass"
        assert wrote is True
        # artifact on disk
        assert (child_root / ".ai" / "runplan" / "test-wid" / "requirements.yaml").is_file()

    def test_authoring_invalid_artifact(self, child_root):
        _init_git(child_root)
        author = lambda prompt: "not valid yaml artifact"
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements"], {}, "bad-wid",
            "test task", {"max_model_calls": 5})
        assert "requirements" not in gate_ev
        assert any(not a["valid"] for a in authored)

    def test_authoring_skips_existing_evidence(self, child_root):
        _init_git(child_root)
        author = lambda prompt: "should not be called"
        existing_ev = {"requirements": {"status": "pass", "provided": ["existing"]}}
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            author, child_root, ["requirements"], existing_ev, "skip-wid",
            "test task", {"max_model_calls": 5})
        assert gate_ev["requirements"]["status"] == "pass"
        assert gate_ev["requirements"]["provided"] == ["existing"]

    def test_authoring_spec_with_valid_openspec(self, child_root):
        _init_git(child_root)
        def spec_author(prompt):
            return ("schema_version: 1\nkind: spec-change\ncapability: test\nwhy: testing\n"
                    "what_changes:\n  - add feature\ntasks:\n  - implement\n"
                    "requirements:\n  - name: Fmt\n    text: The system SHALL format.\n"
                    "    scenarios:\n      - {name: T, when: x, then: y}\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            spec_author, child_root, ["specification"], {}, "spec-wid",
            "spec task", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" in gate_ev
        assert gate_ev["specification"]["status"] == "pass"

    def test_authoring_spec_cli_absent(self, child_root):
        _init_git(child_root)
        def spec_author(prompt):
            return ("schema_version: 1\nkind: spec-change\ncapability: test\nwhy: testing\n"
                    "what_changes:\n  - add feature\ntasks:\n  - implement\n"
                    "requirements:\n  - name: Fmt\n    text: The system SHALL format.\n"
                    "    scenarios:\n      - {name: T, when: x, then: y}\n")
        gate_ev, authored, wrote = execution_pipeline._run_authoring(
            spec_author, child_root, ["specification"], {}, "spec-absent",
            "spec task", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (False, False, "no CLI"))
        assert "specification" not in gate_ev
        assert any(a["gate"] == "specification" and a.get("closed") is False for a in authored)


@pytest.mark.unit
class TestAuthoredContextWithArtifacts:
    """Tests for _authored_context with actual artifacts on disk."""

    def test_context_from_valid_artifacts(self, child_root):
        _init_git(child_root)
        # Create artifact files
        out_dir = child_root / ".ai" / "runplan" / "ctx-wid"
        out_dir.mkdir(parents=True)
        (out_dir / "requirements.yaml").write_text("requirements:\n  - id: R1\n", encoding="utf-8")
        authored = [{"gate": "requirements", "artifact": "requirements.yaml", "valid": True}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert "SPECIFICATION" in result or "requirements" in result
        assert "R1" in result

    def test_context_skips_invalid_artifacts(self, child_root):
        _init_git(child_root)
        authored = [{"gate": "requirements", "artifact": "requirements.yaml", "valid": False}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert result == ""

    def test_context_skips_openspec(self, child_root):
        _init_git(child_root)
        authored = [{"gate": "specification", "artifact": "openspec/changes/wid", "valid": True}]
        result = execution_pipeline._authored_context(authored, child_root, "ctx-wid")
        assert result == ""


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineAuthoring:
    """Tests for run_pipeline with author=True — product authoring integration."""

    def test_authoring_without_author_proposer(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="no author",
            signals={"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
            feature="na-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report["authored"] is None

    def test_authoring_with_valid_author(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}
        def author(prompt):
            if "requirements-artifact" in prompt:
                return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                        "  - id: R1\n    statement: test\n    acceptance:\n      - when x then y\n")
            return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                    "  - id: WP1\n    summary: test\n    depends_on: []\nwrite_scope:\n  - src/\n")
        ops = iter([{"op": "write", "path": "src/au.py", "content": "a = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="authoring test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="auth-test",
            commit=True,
            isolate=True,
            install_deps=False,
            author=True,
            author_proposer=author,
        )
        assert report["authored"] is not None
        assert all(a["valid"] for a in report["authored"] if a.get("gate") in ("requirements", "plan_readiness"))
        assert "requirements" not in report["gates"]["unmet"]
        assert "plan_readiness" not in report["gates"]["unmet"]

    def test_authoring_with_invalid_author(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}
        bad_author = lambda prompt: "not valid yaml"
        ops = iter([{"op": "write", "path": "src/bad.py", "content": "b = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="bad author",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="bad-auth",
            commit=True,
            isolate=True,
            install_deps=False,
            author=True,
            author_proposer=bad_author,
        )
        # Invalid spec -> implementation skipped (spec-prestage-failed)
        assert report["loop"]["stopped"] == "spec-prestage-failed"
        assert report["spec_first"]["prestage"]["implementation_skipped"] is True
        assert report["ready_for_pr"] is False


@pytest.mark.unit
class TestSpecFirstGate:
    """spec-first: неполный spec.yaml не пускает в implementation; полный — не блокирует."""

    def test_incomplete_spec_blocks(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.gates import spec_levels as sl
        sl.create_spec(child_root, "spec-fn", _QUICK_SIG)  # все разделы missing
        it_sf = iter([{"op": "write", "path": "src/sf.py", "content": "s=1\n"}, {"done": True}])
        rep_sf = execution_pipeline.run_pipeline(
            "spec-first блок", _QUICK_SIG, child_root, lambda c: next(it_sf),
            budget={"max_model_calls": 5}, feature="spec-fn",
            commit=True, isolate=True, install_deps=False, baseline_diff=True)
        assert rep_sf.get("ready_for_pr") is False
        assert rep_sf["spec_first"]["ok"] is False
        assert rep_sf["spec_first"]["incomplete_sections"]

    def test_full_spec_does_not_block(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.gates import spec_levels as sl
        import yaml as yaml_mod
        sp = child_root / "features" / "spec-fn2" / "spec.yaml"
        sp.parent.mkdir(parents=True, exist_ok=True)
        full_secs = {s: {"status": "complete", "content": "x"} for s in sl.required_sections(0)}
        sp.write_text(yaml_mod.safe_dump({"schema_version": 1, "kind": "spec",
                      "workitem_id": "spec-fn2", "level": 0, "sections": full_secs}),
                      encoding="utf-8")
        it_sf2 = iter([{"op": "write", "path": "src/sf2.py", "content": "s=2\n"}, {"done": True}])
        rep_sf2 = execution_pipeline.run_pipeline(
            "spec-first полон", _QUICK_SIG, child_root, lambda c: next(it_sf2),
            budget={"max_model_calls": 5}, feature="spec-fn2",
            commit=True, isolate=True, install_deps=False, baseline_diff=True)
        assert rep_sf2["spec_first"]["ok"] is True
        assert not rep_sf2["spec_first"]["incomplete_sections"]


@pytest.mark.unit
class TestSpecDepthEngineering:
    """spec-depth: ENGINEERING без --author -> незакрытые разделы уровня -> блок."""

    def test_eng_without_author_blocked(self, child_root):
        _init_python_repo(child_root)
        from ai_ops_kit.engine import tool_broker
        sig_eng = {"task_type": "ENGINEERING", "size": "small", "risk": "medium",
                   "affected_areas": ["core"]}
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        it_sd = iter([{"op": "write", "path": "src/sd.py", "content": "x=1\n"}, {"done": True}])
        rep_sd = execution_pipeline.run_pipeline(
            "eng без артефактов", sig_eng, child_root, lambda c: next(it_sd),
            policy=pol, budget={"max_model_calls": 5}, feature="sd-fn",
            commit=True, isolate=True, install_deps=False)
        assert rep_sd["spec_depth"]["ok"] is False
        assert rep_sd["spec_depth"]["missing"]
        assert rep_sd["ready_for_pr"] is False


@pytest.mark.unit
class TestAuthoringEngineering:
    """Product Authoring: ENGINEERING-план и артефакт-гейты requirements/plan_readiness."""

    def _sig_eng(self):
        return {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}

    def _author_provider(self, prompt):
        if "requirements-artifact" in prompt:
            return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                    "  - id: R1\n    statement: фильтр по статусу сужает список\n"
                    "    acceptance:\n      - when статус=paid then только оплаченные\n")
        if "spec-change" in prompt:
            return ("schema_version: 1\nkind: spec-change\ncapability: catalog\nwhy: нужен фильтр\n"
                    "what_changes:\n  - добавить фильтр по статусу\ntasks:\n  - реализовать\n"
                    "requirements:\n  - name: Filter\n    text: The system SHALL filter by status.\n"
                    "    scenarios:\n      - {name: T, when: статус=paid, then: показаны оплаченные}\n")
        return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
                "  - id: WP1\n    summary: добавить фильтр\n    depends_on: []\n"
                "write_scope:\n  - src/\n")

    def test_engineering_plan_has_artifact_gates_evaluated(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/na.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор без артефактов", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-na",
            commit=True, isolate=True, install_deps=False)
        assert "requirements" in rep["gates"]["evaluated"]
        assert "plan_readiness" in rep["gates"]["evaluated"]

    def test_without_author_artifact_gates_unmet(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/na.py", "content": "n=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор без артефактов", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-na2",
            commit=True, isolate=True, install_deps=False)
        assert "requirements" in rep["gates"]["unmet"]
        assert "plan_readiness" in rep["gates"]["unmet"]
        assert rep["authored"] is None

    def test_valid_artifact_closes_gates_and_runs_impl(self, child_root):
        _init_python_repo(child_root)
        it = iter([{"op": "write", "path": "src/au.py", "content": "a=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с артефактами", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-au",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=self._author_provider)
        assert "requirements" not in rep["gates"]["unmet"]
        assert "plan_readiness" not in rep["gates"]["unmet"]
        assert rep["authored"] and all(a["valid"] for a in rep["authored"])
        assert (child_root / ".ai" / "worktrees" / "eng-au" / ".ai" / "runplan" / "eng-au" / "requirements.yaml").exists()
        # валидная спека -> реализация запущена
        assert (child_root / ".ai" / "worktrees" / "eng-au" / "src" / "au.py").exists()
        assert rep["spec_first"]["prestage"]["implementation_skipped"] is False

    def test_invalid_artifact_keeps_requirements_blocking_no_code(self, child_root):
        _init_python_repo(child_root)
        bad_author = lambda prompt: "это не yaml артефакта, просто текст"  # noqa: E731
        it = iter([{"op": "write", "path": "src/ba.py", "content": "b=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с битым артефактом", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 5}, feature="eng-ba",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=bad_author)
        assert "requirements" in rep["gates"]["unmet"]
        assert any(not a["valid"] for a in (rep["authored"] or []))
        # невалидная спека -> tool loop НЕ запущен, код НЕ записан
        assert rep["loop"]["stopped"] == "spec-prestage-failed"
        assert rep["spec_first"]["prestage"]["implementation_skipped"] is True
        assert rep["ready_for_pr"] is False
        assert not (child_root / ".ai" / "worktrees" / "eng-ba" / "src" / "ba.py").exists()

    def test_flaky_author_retry_restores_valid_form(self, child_root):
        _init_python_repo(child_root)

        def flaky_author(prompt):
            if "[повтор" not in prompt:
                return "(пустой ответ модели)"
            return self._author_provider(prompt)
        it = iter([{"op": "write", "path": "src/fk.py", "content": "f=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с флаки-автором", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="eng-fk",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=flaky_author)
        assert "requirements" not in rep["gates"]["unmet"]
        assert rep["authored"] and all(a["valid"] for a in rep["authored"])

    def test_always_flaky_author_keeps_gate_blocking(self, child_root):
        _init_python_repo(child_root)
        always_bad = lambda prompt: "(пустой ответ модели)"  # noqa: E731
        it = iter([{"op": "write", "path": "src/ab.py", "content": "b=1\n"}, {"done": True}])
        rep = execution_pipeline.run_pipeline(
            "рефактор с вечно-битым автором", self._sig_eng(), child_root, lambda c: next(it),
            budget={"max_model_calls": 20}, feature="eng-ab",
            commit=True, isolate=True, install_deps=False,
            author=True, author_proposer=always_bad)
        assert "requirements" in rep["gates"]["unmet"]
        assert any(not a["valid"] for a in (rep["authored"] or []))


@pytest.mark.unit
class TestRunAuthoringSpecEdges:
    """_run_authoring: битый spec не закрывается; task с двоеточием нормализуется."""

    def _spec_author(self, prompt):
        return (
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита цены\n"
            "what_changes:\n  - добавить formatPrice\ntasks:\n  - реализовать\n  - тест\n"
            "requirements:\n  - name: Formatting\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: formatPrice(1000), then: returns 1 000}\n")

    def test_cli_ok_closes_specification(self, child_root):
        _init_git(child_root)
        gev, _auth, _ = execution_pipeline._run_authoring(
            self._spec_author, child_root, ["specification"], {}, "spec-ok",
            "форматирование цены", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" in gev
        assert gev["specification"]["provided"] == ["openspec_valid", "requirements_covered"]
        assert (child_root / "openspec" / "changes" / "spec-ok" / "proposal.md").exists()

    def test_broken_spec_not_closed(self, child_root):
        _init_git(child_root)
        gev, auth, _ = execution_pipeline._run_authoring(
            lambda p: "не yaml", child_root, ["specification"], {}, "spec-bad",
            "x", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert "specification" not in gev
        assert any(a["gate"] == "specification" and not a["valid"] for a in auth)

    def test_task_with_colon_normalized_valid(self, child_root):
        _init_git(child_root)
        colon_author = lambda prompt: (  # noqa: E731
            "schema_version: 1\nkind: spec-change\ncapability: pricing\nwhy: нужна утилита\n"
            "what_changes:\n  - добавить formatPrice\n"
            "tasks:\n  - Написать unit-тесты: все ветвления, граничные значения, ошибочный ввод\n  - реализовать\n"
            "requirements:\n  - name: Fmt\n    text: The system SHALL format price.\n"
            "    scenarios:\n      - {name: T, when: x, then: y}\n")
        _gev, auth, _ = execution_pipeline._run_authoring(
            colon_author, child_root, ["specification"], {}, "spec-colon",
            "цена", {"max_model_calls": 5},
            openspec_validate=lambda wr, cid: (True, True, "valid"))
        assert any(a["gate"] == "specification" and a["valid"] for a in auth)
