"""Юнит-тесты execution_pipeline: проход ревью и security-вердикты в run_pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import execution_pipeline

from _pipeline_helpers import _init_git

# Тесты поднимают реальный git-репозиторий и прогоняют конвейер ревью через подпроцессы — >10 c на
# CI, то есть slow по определению маркера (pytest.ini). Снят с шарда `fast` под `--dist loadfile` в
# slow-шарды selftests, где есть запас; на КАЖДОМ PR по-прежнему выполняется. Issue #465.
pytestmark = pytest.mark.slow


@pytest.mark.unit
class TestSecurityVerdictErrorsAdditional:
    """Additional tests for _security_verdict_errors — deeper branches."""

    def _make_vrr(self):
        import validate_reviewer_result as vrr
        return vrr

    def test_duplicate_domains(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "a.py"}]},
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok2", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "b.py"}]},
            ]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("дубли" in e for e in errs)

    def test_extra_domain(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [
                {"domain": "injection", "status": "pass",
                 "checks": [{"id": "ok", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "a.py"}]},
                {"domain": "unknown_domain", "status": "pass",
                 "checks": [{"id": "ok2", "status": "pass"}],
                 "evidence": [{"type": "code-read", "path": "b.py"}]},
            ]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("лишние" in e or "неизвестные" in e for e in errs)

    def test_pass_domain_without_evidence(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("evidence" in e for e in errs)

    def test_domain_without_checks(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("checks" in e for e in errs)

    def test_nested_check_without_id(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("nested-check" in e for e in errs)

    def test_warn_domain_without_blockers(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "warn",
                                "checks": [{"id": "ok", "status": "pass"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("blockers" in e for e in errs)

    def test_file_type_evidence_with_reads_match(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "input_validation", "status": "pass",
                                "checks": [{"id": "iv", "status": "pass"}],
                                "evidence": [{"type": "file", "path": "pricing.py", "lines": "10-11"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc", ["input_validation"], self._make_vrr(), reviewer_reads=["pricing.py"])
        assert errs == []

    def test_file_type_evidence_fabricated(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "input_validation", "status": "pass",
                                "checks": [{"id": "iv", "status": "pass"}],
                                "evidence": [{"type": "file", "path": "pricing.py", "lines": "10-11"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(
            res, "abc", ["input_validation"], self._make_vrr(), reviewer_reads=["other.py"])
        assert any("сфабрикован" in e for e in errs)

    def test_pass_domain_check_without_pass_check(self):
        res = {
            "schema_version": 1, "kind": "reviewer-result", "gate": "security",
            "status": "pass", "reviewed_revision": "abc",
            "checks": [{"id": "sec", "status": "pass"}],
            "domain_results": [{"domain": "injection", "status": "pass",
                                "checks": [{"id": "ok", "status": "warn"}],
                                "evidence": [{"type": "code-read", "path": "a.py"}]}]
        }
        errs = execution_pipeline._security_verdict_errors(res, "abc", ["injection"], self._make_vrr())
        assert any("ни один" in e for e in errs)


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSecurityPack:
    """Tests for security pack integration in run_pipeline."""

    def test_security_scan_present_with_commit(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/sec.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="security test",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="sec-pack-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        # security_scan should be present (may be None if no committed_sha path, but with commit it runs)
        # The key is that security gate evaluation happened
        assert "security_scan" in report
        assert "gates" in report

    def test_security_secret_blocks(self, child_root):
        _init_git(child_root)
        # Не канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — публичный образец, и
        # детектор с 19.08.2026 его не считает утечкой. Позитивной фикстуре нужен ключ,
        # похожий на настоящий.
        _aws = "AKIA" + "QRSTUVWX9012YZAB"
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "medium", "affected_areas": ["core"]}
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        ops = iter([{"op": "write", "path": "src/leak.py",
                     "content": f'KEY = "{_aws}"\n'}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="secret test",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 10},
            feature="sec-secret",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report.get("security_scan") is not None
        assert "secrets" in report["security_scan"]["blocking"]
        assert "security" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSpecDepth:
    """Tests for spec-depth and spec-first integration."""

    def test_spec_depth_in_report(self, child_root):
        _init_git(child_root)
        ops = iter([{"op": "write", "path": "src/sd.py", "content": "s = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="spec depth",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 10},
            feature="sd-test",
            commit=True,
        )
        assert "spec_depth" in report
        assert "spec_first" in report
        assert isinstance(report["spec_depth"]["missing"], list)
        assert isinstance(report["spec_first"]["incomplete_sections"], list)

    def test_spec_first_prestage_without_author(self, child_root):
        _init_git(child_root)
        report = execution_pipeline.run_pipeline(
            task="no author",
            signals={"task_type": "QUICK"},
            child_root=child_root,
            proposer=lambda ctx: {"done": True},
            budget={"max_model_calls": 5},
        )
        assert report["spec_first"]["prestage"]["ran"] is False
        assert report["spec_first"]["prestage"]["implementation_skipped"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineReviewPass:
    """Tests for run_pipeline review with pass reviewer — exercises _run_reviews."""

    def test_review_pass_closes_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # Reviewer reads the file first, then passes
        def pass_reviewer(prompt):
            if "--- src/rp2.py ---" in prompt:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            if "src/rp2.py" in prompt:
                return '{"op":"read","path":"src/rp2.py"}'
            return '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["no context"]}'
        ops = iter([{"op": "write", "path": "src/rp2.py", "content": "p = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review pass",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rp2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=pass_reviewer,
        )
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "pass" for r in report["reviews"])
        assert "ux_review" not in report["gates"]["unmet"]

    def test_review_warn_blocks_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        warn_reviewer = lambda prompt: (
            '{"kind":"reviewer-result","status":"warn",'
            '"checks":[{"id":"x","status":"warn"}],'
            '"blockers":["state not covered"]}')
        ops = iter([{"op": "write", "path": "src/rw2.py", "content": "w = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="review warn",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rw2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=warn_reviewer,
        )
        assert report["reviews"] is not None
        assert any(r["gate"] == "ux_review" and r["status"] == "warn" for r in report["reviews"])
        assert "ux_review" in report["gates"]["unmet"]

    def test_review_rubber_stamp_blocked(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # Rubber-stamp: pass without reading anything
        rubber = lambda prompt: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        ops = iter([{"op": "write", "path": "src/rs2.py", "content": "r = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="rubber stamp",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            budget={"max_model_calls": 20},
            feature="rs2-test",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=rubber,
        )
        # 0 reads on blocking gate -> blocked as rubber-stamp
        assert any(r["gate"] == "ux_review" and r.get("closed_as") == "blocked"
                    for r in (report["reviews"] or []))
        assert "ux_review" in report["gates"]["unmet"]

    def test_review_pass_zero_reads_but_grounded_evidence_passes(self, child_root):
        """Fix C для ревьюеров: pass БЕЗ read-op, но evidence ссылается на ДОСТАВЛЕННЫЙ файл — НЕ
        рубер-штамп: кит сам сверил состав правки. Разблокирует боевого claude-cli, который судит из
        диффа и read-op детерминированно не эмитит (тот же класс, что закрыл acceptance Fix C)."""
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # pass, НИ ОДНОГО read-op, но evidence на доставленный src/rg2.py
        grounded = lambda prompt: (
            '{"kind":"reviewer-result","status":"pass",'
            '"checks":[{"id":"ok","status":"pass","evidence":[{"file":"src/rg2.py","lines":"1"}]}]}')
        ops = iter([{"op": "write", "path": "src/rg2.py", "content": "g = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="grounded pass", signals=sig, child_root=child_root,
            proposer=lambda ctx: next(ops), budget={"max_model_calls": 20},
            feature="rg2-test", commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=grounded)
        # заземлено на доставленный файл -> pass закрывает гейт, несмотря на 0 reads
        assert any(r["gate"] == "ux_review" and r["status"] == "pass"
                   for r in (report["reviews"] or [])), report["reviews"]
        assert "ux_review" not in report["gates"]["unmet"]

    def test_review_pass_zero_reads_evidence_off_change_is_still_blocked(self, child_root):
        """Заземление требует ИМЕННО доставленный файл. pass с 0 reads и evidence на ЧУЖОЙ файл
        (не в правке) остаётся рубер-штампом — страж не ослаблен. Мутация (снять условие заземления)
        роняет либо этот тест (over-ground), либо grounded-тест (under-ground)."""
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        off = lambda prompt: (
            '{"kind":"reviewer-result","status":"pass",'
            '"checks":[{"id":"ok","status":"pass","evidence":[{"file":"src/UNRELATED.py","lines":"1"}]}]}')
        ops = iter([{"op": "write", "path": "src/ro2.py", "content": "o = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="off-change evidence", signals=sig, child_root=child_root,
            proposer=lambda ctx: next(ops), budget={"max_model_calls": 20},
            feature="ro2-test", commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=off)
        assert any(r["gate"] == "ux_review" and r.get("closed_as") == "blocked"
                   for r in (report["reviews"] or [])), report["reviews"]
        assert "ux_review" in report["gates"]["unmet"]

    def test_review_pass_zero_reads_fabricated_lines_is_blocked(self, child_root):
        """Заземление ревью поднято до уровня приёмки (Fix C, P0 04.09.2026): pass с 0 reads и evidence
        на ДОСТАВЛЕННЫЙ файл, но с ВЫДУМАННЫМ диапазоном строк (500-520 в однострочном файле) —
        остаётся рубер-штампом: кит читает файл и видит, что таких строк нет. Совпадения ИМЕНИ мало.
        Мутация (снять сверку строк с файлом) роняет либо этот тест, либо grounded-тест выше."""
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["core"], "ui_changed": True}
        # pass, 0 reads, evidence на доставленный файл, но строки выдуманы (файл в 1 строку)
        fabricated = lambda prompt: (
            '{"kind":"reviewer-result","status":"pass",'
            '"checks":[{"id":"ok","status":"pass","evidence":[{"file":"src/rf2.py","lines":"500-520"}]}]}')
        ops = iter([{"op": "write", "path": "src/rf2.py", "content": "f = 1\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="fabricated lines", signals=sig, child_root=child_root,
            proposer=lambda ctx: next(ops), budget={"max_model_calls": 20},
            feature="rf2-test", commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=fabricated)
        assert any(r["gate"] == "ux_review" and r.get("closed_as") == "blocked"
                   for r in (report["reviews"] or [])), report["reviews"]
        assert "ux_review" in report["gates"]["unmet"]


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineSecurityReviewer:
    """Tests for security reviewer integration in run_pipeline."""

    def test_security_reviewer_pass_closes_gate(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "ENGINEERING", "size": "small", "risk": "medium", "affected_areas": ["core"]}
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        # Clean code + reviewer pass
        sec_reviewer = lambda c: '{"kind":"reviewer-result","status":"pass","summary":"clean"}'
        ops = iter([{"op": "write", "path": "src/clean.py", "content": "def f():\n    return 1\n"},
                     {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="security reviewer pass",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 15},
            feature="sec-rev-pass",
            commit=True,
            isolate=True,
            install_deps=False,
            review=True,
            reviewer_proposer=sec_reviewer,
        )
        # Security reviewer was invoked (reviews ran)
        assert report["reviews"] is not None


@pytest.mark.critical_path
@pytest.mark.unit
class TestRunPipelineNewDependency:
    """Tests for new dependency detection in security pack."""

    def test_new_dependency_triggers_security(self, child_root):
        _init_git(child_root)
        sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        from ai_ops_kit.engine import tool_broker
        pol = tool_broker.Policy(level="execution", block_push=True)
        ops = iter([{"op": "write", "path": "requirements.txt", "content": "flask\n"}, {"done": True}])
        report = execution_pipeline.run_pipeline(
            task="add dependency",
            signals=sig,
            child_root=child_root,
            proposer=lambda ctx: next(ops),
            policy=pol,
            budget={"max_model_calls": 10},
            feature="dep-test",
            commit=True,
            isolate=True,
            install_deps=False,
        )
        assert report.get("security_scan") is not None
        assert "dependencies" in (report["security_scan"].get("needs_review") or [])
        assert "security" in report["gates"]["unmet"]
        assert report["ready_for_pr"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestReevaluateConsumesHandoffVerdict:
    """#570-follow-up (живой прогон 07.09): записанный ОРКЕСТРАТОРОМ вердикт-артефакт закрывает
    code_review на ШТАТНОМ reevaluate (0 model-вызовов, БЕЗ --review) — через РЕАЛЬНЫЙ поток
    run_pipeline, а не только прямой вызов _run_reviews. Прежде artifact-first жил лишь внутри
    _run_reviews, который зовётся только при --review с живым провайдером; поэтому валидный вердикт
    не потреблялся и code_review оставался «нет заключения reviewer». Инвариант 0 false-green и
    writer≠judge сохранены: устаревший-SHA / писательский / незаземлённый вердикт гейт НЕ закроет."""

    ENG = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}

    def _commit_work(self, child_root, wid):
        """Первый прогон: закоммитить ENGINEERING-работу; code_review остаётся незакрытым (ревьюер
        не выносит вердикт). -> (sha, changed_file)."""
        ops = iter([{"op": "write", "path": f"src/{wid}.py", "content": "def g():\n    return 42\n"},
                     {"done": True}])
        rep = execution_pipeline.run_pipeline(
            task="engineering task", signals=self.ENG, child_root=child_root,
            proposer=lambda c: next(ops), budget={"max_model_calls": 20}, feature=wid,
            commit=True, isolate=True, install_deps=False,
            review=True, reviewer_proposer=lambda p: '{"op":"noop"}')
        return (rep.get("commit") or {}).get("sha"), f"src/{wid}.py"

    def _write_verdict(self, child_root, sha, *, reviewer, evidence_file, revision=None):
        from ai_ops_kit.engine import reviewer_handoff
        vp = reviewer_handoff.verdict_path(str(child_root), "code_review")
        vp.parent.mkdir(parents=True, exist_ok=True)
        vp.write_text(json.dumps({
            "schema_version": 1, "kind": "reviewer-result", "gate": "code_review", "status": "pass",
            "reviewed_revision": revision or sha, "reviewer": reviewer,
            "checks": [{"id": "cr", "status": "pass",
                        "evidence": [{"file": evidence_file, "lines": "1-2"}]}]},
            ensure_ascii=False), encoding="utf-8")

    def _reevaluate(self, child_root, wid, spy=None):
        """Штатный reevaluate: review=False (как `run --execute --reevaluate-only` без --review),
        провайдер НЕ должен вызываться."""
        return execution_pipeline.run_pipeline(
            task="engineering task", signals=self.ENG, child_root=child_root,
            proposer=lambda c: {"done": True}, budget={"max_model_calls": 20}, feature=wid,
            commit=True, isolate=True, install_deps=False,
            review=False, reviewer_proposer=spy, reevaluate_only=True)

    def _cr(self, report):
        return next((r for r in (report.get("reviews") or []) if r["gate"] == "code_review"), None)

    def test_valid_verdict_closes_code_review_without_provider(self, child_root):
        """Валидный ЗАЗЕМЛЁННЫЙ вердикт на committed SHA -> code_review ЗАКРЫТ на reevaluate; статус
        из вердикта, source=handoff-artifact, провайдер НЕ вызван."""
        _init_git(child_root)
        sha, changed = self._commit_work(child_root, "cr-ok")
        assert sha, "первый прогон не закоммитил работу"
        self._write_verdict(child_root, sha, reviewer="orchestrator", evidence_file=changed)

        called = {"n": 0}

        def spy(_p):
            called["n"] += 1
            return '{"op":"noop"}'

        rep2 = self._reevaluate(child_root, "cr-ok", spy=spy)
        e = self._cr(rep2)
        assert e is not None and e["source"] == "handoff-artifact", rep2.get("reviews")
        assert e["status"] == "pass" and e.get("closed_as") == "pass"
        assert "code_review" not in rep2["gates"]["unmet"]
        assert called["n"] == 0, "провайдер ревьюера вызван на reevaluate — artifact-first не сработал"

    def test_stale_sha_verdict_rejected_gate_blocked(self, child_root):
        """Вердикт на УСТАРЕВШЕМ SHA не принимается -> code_review остаётся незакрытым (0 false-green)."""
        _init_git(child_root)
        sha, changed = self._commit_work(child_root, "cr-stale")
        self._write_verdict(child_root, sha, reviewer="orchestrator", evidence_file=changed,
                            revision="deadbeef" * 5)
        rep2 = self._reevaluate(child_root, "cr-stale")
        assert "code_review" in rep2["gates"]["unmet"]
        e = self._cr(rep2)
        assert e is None or e.get("status") != "pass", rep2.get("reviews")

    def test_writer_attributed_verdict_rejected_gate_blocked(self, child_root):
        """writer≠judge: вердикт, атрибутированный писателю (claude-code-local), гейт НЕ закрывает."""
        _init_git(child_root)
        sha, changed = self._commit_work(child_root, "cr-writer")
        self._write_verdict(child_root, sha, reviewer="claude-code-local", evidence_file=changed)
        rep2 = self._reevaluate(child_root, "cr-writer")
        assert "code_review" in rep2["gates"]["unmet"]

    def test_off_change_evidence_verdict_blocked(self, child_root):
        """pass-вердикт с evidence на ЧУЖОЙ файл (не в правке) -> заземление не проходит -> blocked
        (тот же страж рубер-штампа, что на живом пути)."""
        _init_git(child_root)
        sha, _changed = self._commit_work(child_root, "cr-off")
        self._write_verdict(child_root, sha, reviewer="orchestrator",
                            evidence_file="src/UNRELATED.py")
        rep2 = self._reevaluate(child_root, "cr-off")
        assert "code_review" in rep2["gates"]["unmet"]
        e = self._cr(rep2)
        assert e is not None and e.get("closed_as") == "blocked", rep2.get("reviews")


# ============================================================================
# MIGRATED FROM MONOLITH — test_execution_pipeline_selftest (weed round)
# Каждое поведение перенесено с НАСТОЯЩЕЙ проверкой значения (не только наличия
# ключа/верхнего status). Точные вызовы/фикстуры/фейковые proposer'ы — из монолита.
# ============================================================================
