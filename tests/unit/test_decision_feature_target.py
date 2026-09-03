"""Acceptance для исхода feature_has_baseline_target_and_guardrails (#417).

Продуктовое решение о фиче обязано нести три измеримых обязательства — baseline
(где мы сейчас), target (куда идём) и guardrails (что не должно сломаться), — и
это ПРОВЕРЯЕТ механизм, а не декларация человека. Три критерия приёмки:

  1. positive     — полное решение проходит check_feature_target и пишется propose;
  2. fail-closed  — без target / без guardrails / с пустой метрикой propose не пишет;
  3. side-effect  — гейт validate_decisions краснит каталог с неполным feature-decision
                    и называет, чего не хватает; на полном — зелёный.
"""
from __future__ import annotations

import yaml
import pytest

from ai_ops_kit.intelligence.decision_loop import (
    check_feature_target,
    gate_feature_decisions,
    propose,
)


def _full_target() -> dict:
    return {
        "baseline": {"metric": "p95_latency_ms", "value": 800},
        "target": {"value": 400, "direction": "decrease"},
        "guardrails": [{"metric": "error_rate", "bound": "<0.5%"}],
    }


@pytest.mark.unit
class TestFeatureTargetContract:

    # 1. positive
    def test_full_target_passes_and_is_written(self, tmp_path):
        ft = _full_target()
        assert check_feature_target(ft) == []
        result = propose(tmp_path, "feat-1", "ускорить выдачу", feature_target=ft)
        assert result["status"] == "proposed"
        assert result["decision"]["kind"] == "feature-decision"
        files = list((tmp_path / ".ai" / "project" / "decisions").glob("*.yaml"))
        assert len(files) == 1
        stored = yaml.safe_load(files[0].read_text(encoding="utf-8"))
        assert stored["feature_target"] == ft

    # 2. fail-closed
    @pytest.mark.parametrize("mutate,missing", [
        (lambda ft: ft.pop("target"), "target"),
        (lambda ft: ft.__setitem__("guardrails", []), "guardrails"),
        (lambda ft: ft["baseline"].__setitem__("metric", ""), "baseline.metric"),
        (lambda ft: ft["target"].__setitem__("direction", "up"), "direction"),
    ])
    def test_incomplete_target_is_rejected_and_not_written(self, tmp_path, mutate, missing):
        ft = _full_target()
        mutate(ft)
        errors = check_feature_target(ft)
        assert errors, f"неполный feature_target ({missing}) обязан дать ошибки"
        assert any(missing in e for e in errors)
        result = propose(tmp_path, "feat-bad", "фича без обязательства", feature_target=ft)
        assert "error" in result
        assert not (tmp_path / ".ai" / "project" / "decisions").exists() or \
            not list((tmp_path / ".ai" / "project" / "decisions").glob("*.yaml"))

    # 3. side-effect proof — гейт на каталоге решений
    def test_gate_fails_on_incomplete_feature_decision(self, tmp_path):
        ddir = tmp_path / ".ai" / "project" / "decisions"
        ddir.mkdir(parents=True)
        incomplete = {"schema_version": 1, "kind": "feature-decision", "id": "x",
                      "feature_target": {"baseline": {"metric": "m", "value": 1}}}
        (ddir / "2026-09-03-x.yaml").write_text(
            yaml.dump(incomplete, allow_unicode=True), encoding="utf-8")
        errors = gate_feature_decisions(ddir)
        assert errors, "гейт обязан упасть на неполном feature-decision"
        assert any("target" in e for e in errors)
        assert any("guardrails" in e for e in errors)

    def test_gate_passes_on_complete_feature_decision(self, tmp_path):
        propose(tmp_path, "ok", "полная фича", feature_target=_full_target())
        ddir = tmp_path / ".ai" / "project" / "decisions"
        assert gate_feature_decisions(ddir) == []

    def test_gate_ignores_non_feature_decisions(self, tmp_path):
        propose(tmp_path, "plain", "просто решение")  # kind=product-decision
        ddir = tmp_path / ".ai" / "project" / "decisions"
        assert gate_feature_decisions(ddir) == []

    def test_gate_on_missing_dir_is_not_error(self, tmp_path):
        assert gate_feature_decisions(tmp_path / "nope") == []
