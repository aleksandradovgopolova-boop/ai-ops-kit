"""Гранулярные тесты qual_run (мигрировано из test_qual_run_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import json
import tempfile

import pytest

from qual_run import (
    Path,
    evaluate_report,
    print_summary,
    run_qualification,
    slugify,
)
import run_plan


@pytest.fixture
def good_report():
    return {
        "kind": "execution-pipeline", "status": None,
        "loop": {"stopped": "done", "denied": 0},
        "commit": {"sha": "a" * 40, "evidence_on_exact_sha": True},
        "gates": {"blocked": False, "unmet": []}, "ready_for_pr": True,
    }


# ── slugify ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSlugify:
    @pytest.mark.parametrize("title", [
        "Мелкий БАГ-фикс: список!!!", "  ", "----", "UPPER Case Task", "🚀🚀",
    ])
    def test_slug_is_valid_workitem_id(self, title):
        s = slugify(title)
        try:
            run_plan.validate_workitem_id(s)
            valid = True
        except ValueError:
            valid = False
        assert valid, f"slug {s!r} from {title!r} is not a valid workitem_id"

    def test_cyrillic_transliterated(self):
        assert slugify("Добавить фильтр").startswith("dobavit")

    def test_different_russian_tasks_unique_slugs(self):
        slugs = [slugify(x) for x in ["Добавить фильтр", "Исправить баг", "Обновить доки"]]
        assert len(set(slugs)) == 3


# ── evaluate_report ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEvaluateReport:
    def test_good_report_ok(self, good_report):
        assert evaluate_report(good_report)["ok"] is True

    def test_not_ready_fails(self, good_report):
        good_report["ready_for_pr"] = False
        assert evaluate_report(good_report)["ok"] is False

    def test_gates_blocked_reason(self, good_report):
        good_report["ready_for_pr"] = False
        good_report["gates"] = {"blocked": True, "unmet": ["x"]}
        r = evaluate_report(good_report)
        assert r["ok"] is False
        assert any("gates" in reason for reason in r["reasons"])

    def test_sha_mismatch_reason(self, good_report):
        good_report["ready_for_pr"] = False
        good_report["commit"] = {"sha": "a" * 40, "evidence_on_exact_sha": False}
        r = evaluate_report(good_report)
        assert r["ok"] is False
        assert any("SHA" in reason for reason in r["reasons"])

    def test_regression_reason(self, good_report):
        good_report["ready_for_pr"] = False
        good_report["baseline"] = {"regressions": ["build"], "no_regressions": False}
        r = evaluate_report(good_report)
        assert r["ok"] is False
        assert any("регресс" in reason for reason in r["reasons"])

    def test_ready_overrides_gates_blocked(self, good_report):
        good_report["gates"] = {"blocked": True, "unmet": ["x"]}
        assert evaluate_report(good_report)["ok"] is True

    def test_status_error_fails(self):
        assert evaluate_report({"status": "error", "error": "boom"})["ok"] is False

    def test_none_fails(self):
        assert evaluate_report(None)["ok"] is False


# ── run_qualification ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRunQualification:
    def test_mixed_series(self, good_report):
        with tempfile.TemporaryDirectory() as td:
            scripted = {
                "ok task": good_report,
                "bad task": {
                    "kind": "execution-pipeline", "loop": {"stopped": "done"},
                    "commit": {"sha": "b" * 40, "evidence_on_exact_sha": True},
                    "gates": {"blocked": True, "unmet": ["security"]},
                    "ready_for_pr": False,
                },
            }

            def runner(task):
                if task == "boom task":
                    raise RuntimeError("provider down")
                return scripted[task]

            res = run_qualification(["ok task", "bad task", "boom task"], td, runner)
            by = {r["task"]: r for r in res}
            assert by["ok task"]["ok"] is True
            assert by["bad task"]["ok"] is False
            assert by["bad task"]["reasons"]
            assert by["boom task"]["ok"] is False
            assert (Path(td) / "01-ok-task.json").exists()
            assert (Path(td) / "summary.json").exists()
            assert print_summary(res) is False

    def test_all_pass(self, good_report):
        with tempfile.TemporaryDirectory() as td:
            allgood = run_qualification(["ok task"], td, lambda t: good_report)
            assert print_summary(allgood) is True
