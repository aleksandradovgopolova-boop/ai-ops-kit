"""#405: вердикт readiness не должен ЧЕРЕДОВАТЬСЯ на ОДНОМ входе.

Дорогой live-прогон чередовал READY/NOT_READY, упираясь в implementation_verification /
verification_strategy. Здесь — синтетика (без live-прогона), которая:
  (а) фиксирует ДЕТЕРМИНИЗМ: одно и то же вычисление readiness на ОДНОМ входе, прогнанное ДВАЖДЫ,
      даёт идентичный вердикт (spec_depth, exempt, unstable_checks);
  (б) частичный/битый артефакт plan.yaml -> ДЕТЕРМИНИРОВАННЫЙ исход (не флип): пустой/битый файл
      НЕ засчитывает раздел, валидный — засчитывает;
  (в) `_diff_checks`/`_baseline_status_flips`/exempt на одном baseline+checks -> один результат, а
      flaky pass<->fail проверка НАЗВАНА (атрибуция флипа), а не проглочена молча.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_readiness import _assess_readiness
from ai_ops_kit.engine.pipeline_failure import _diff_checks, _baseline_status_flips
from ai_ops_kit.gates import spec_levels


def _readiness_input():
    gates = {"unmet_gates": ["implementation_verification"]}
    coll = {"checks": {"test": {"status": "fail", "runs": []},
                       "lint": {"status": "pass", "runs": []}},
            "revision": "head1"}
    baseline_checks = {"test": {"status": "fail", "runs": []},
                       "lint": {"status": "pass", "runs": []}}
    signals = {"task_type": "ENGINEERING", "size": "small", "risk": "low",
               "affected_areas": ["core"]}
    plan = {"gates": {"implementation_verification": {"required_evidence": ["tested_revision"]}}}
    return gates, coll, baseline_checks, signals, plan


def _call(tmp_path, gates, coll, baseline_checks, signals, plan):
    return _assess_readiness(
        gates, coll, signals, plan, str(tmp_path), "wi-405", str(tmp_path),
        baseline_diff=True, baseline_checks=baseline_checks,
        committed_sha="head1", base_sha="base0", reviewer_proposer=None, budget={})


@pytest.mark.unit
class TestReadinessDeterminism:
    def test_same_input_twice_identical_verdict(self, tmp_path):
        """(а) ★детерминизм★: два прогона на ОДНОМ входе -> идентичный вердикт."""
        gates, coll, baseline_checks, signals, plan = _readiness_input()
        first = _call(tmp_path, gates, coll, baseline_checks, signals, plan)
        second = _call(tmp_path, gates, coll, baseline_checks, signals, plan)
        # весь ready-релевантный набор совпадает пословно (не только ready-булев)
        for key in ("spec_depth_missing", "spec_depth_ok", "spec_complete_ok",
                    "iv_baseline_exempt", "unstable_checks", "level"):
            assert first[key] == second[key], f"{key} флипнул: {first[key]!r} != {second[key]!r}"

    def test_no_regression_exempts_implementation_verification(self, tmp_path):
        """База красная И правка не внесла регрессий -> impl_verification baseline-освобождён,
        verification_strategy не блокирует spec_depth."""
        gates, coll, baseline_checks, signals, plan = _readiness_input()
        rd = _call(tmp_path, gates, coll, baseline_checks, signals, plan)
        assert rd["iv_baseline_exempt"] is True
        assert "verification_strategy" not in rd["spec_depth_missing"]

    def test_exempt_stable_when_check_stays_failing(self, tmp_path):
        """(в) тот же baseline+checks (test:fail<->fail) -> тот же exempt при повторе."""
        gates, coll, baseline_checks, signals, plan = _readiness_input()
        e1 = _call(tmp_path, gates, coll, baseline_checks, signals, plan)["iv_baseline_exempt"]
        e2 = _call(tmp_path, gates, coll, baseline_checks, signals, plan)["iv_baseline_exempt"]
        assert e1 == e2 is True


@pytest.mark.unit
class TestFlakyCheckIsNamed:
    """flaky pass<->fail проверка переворачивает exempt между прогонами — но теперь НАЗВАНА."""

    def test_flip_source_is_named_both_directions(self):
        base_pass = {"test": {"status": "pass"}}
        after_fail = {"test": {"status": "fail"}}
        # pass->fail: выглядит регрессом -> exempt снят; flaky назван
        assert _diff_checks(base_pass, after_fail)[0] == ["test"]
        assert _baseline_status_flips(base_pass, after_fail) == ["test"]
        # fail->pass: выглядит починкой -> exempt дан; та же проверка названа нестабильной
        assert _diff_checks(after_fail, base_pass)[0] == []
        assert _baseline_status_flips(after_fail, base_pass) == ["test"]

    def test_stable_check_is_not_flagged(self):
        same = {"test": {"status": "fail"}, "lint": {"status": "pass"}}
        assert _baseline_status_flips(same, same) == []

    def test_flips_are_sorted_and_deterministic(self):
        base = {"b": {"status": "pass"}, "a": {"status": "pass"}, "c": {"status": "fail"}}
        after = {"b": {"status": "fail"}, "a": {"status": "fail"}, "c": {"status": "fail"}}
        assert _baseline_status_flips(base, after) == ["a", "b"]
        # повтор -> тот же порядок
        assert _baseline_status_flips(base, after) == _baseline_status_flips(base, after)


@pytest.mark.unit
class TestArtifactCreditDeterministic:
    """(б) частичный/битый plan.yaml -> детерминированный исход (не флип credit)."""

    ENG = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}

    def _plan_path(self, tmp_path, wid):
        d = tmp_path / ".ai" / "runplan" / wid
        d.mkdir(parents=True, exist_ok=True)
        return d / "plan.yaml"

    def test_valid_plan_credits_verification_strategy(self, tmp_path):
        self._plan_path(tmp_path, "ok").write_text("steps:\n  - do x\n", encoding="utf-8")
        prov = spec_levels.provided_from_artifacts(tmp_path, "ok", work_root=tmp_path)
        assert prov.get("verification_strategy", {}).get("status") == "complete"
        assert prov.get("implementation_plan", {}).get("status") == "complete"

    def test_empty_plan_does_not_credit(self, tmp_path):
        """0-байтный (недописанный) plan.yaml НЕ засчитывает — детерминированно, не 'то да, то нет'."""
        self._plan_path(tmp_path, "empty").write_text("", encoding="utf-8")
        prov = spec_levels.provided_from_artifacts(tmp_path, "empty", work_root=tmp_path)
        assert prov.get("verification_strategy", {}).get("status") != "complete"

    def test_corrupt_plan_does_not_credit(self, tmp_path):
        """Битый YAML -> fail-closed: не засчитывает (а не молча complete по факту существования)."""
        self._plan_path(tmp_path, "bad").write_text("a: b:\n  - [unterminated\n", encoding="utf-8")
        prov = spec_levels.provided_from_artifacts(tmp_path, "bad", work_root=tmp_path)
        assert prov.get("verification_strategy", {}).get("status") != "complete"

    def test_missing_and_empty_agree_across_repeat(self, tmp_path):
        """Один и тот же битый файл читается ОДИНАКОВО дважды (детерминизм чтения артефакта)."""
        self._plan_path(tmp_path, "rep").write_text("", encoding="utf-8")
        a = spec_levels.provided_from_artifacts(tmp_path, "rep", work_root=tmp_path)
        b = spec_levels.provided_from_artifacts(tmp_path, "rep", work_root=tmp_path)
        assert a == b
