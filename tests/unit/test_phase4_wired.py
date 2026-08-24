"""Фаза 4 подключена к пути (закрытие «мёртвого острова» аудита 24.08.2026).

Аудит нашёл, что агрегаторы Фазы 4 (team_sync + governance) built+tested, но звали только тесты.
Здесь проверяется, что их read-функции реально ИСПОЛНЯЮТ осмысленную работу на репозитории — то,
что теперь делает CLI (`ai-ops team`, `ai-ops governance`), а не только модульный тест механизма.
Достижимость из CLI проверяет tests/contracts/test_capability_reachability.py (KNOWN_UNREACHABLE пуст).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.governance import decision_log, human_override, policy_engine
from ai_ops_kit.intelligence import team_sync


@pytest.mark.unit
def test_team_status_composes_health_risks_and_plan(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n\nсервис.\n", encoding="utf-8")
    status = team_sync.team_status(tmp_path)
    assert status["kind"]  # схема на месте
    # три измерения здоровья + риски + блокеры + следующие задачи — агрегат, а не одно измерение
    assert set(status["health"]) == {"product", "tech", "delivery"}
    assert "count_by_severity" in status["risks"]
    for key in ("blockers", "next_tasks", "milestone", "blind_spots"):
        assert key in status
    # _render не падает и даёт человекочитаемый снимок
    assert "СТАТУС КОМАНДЫ" in team_sync._render(status)


@pytest.mark.unit
def test_governance_reads_are_honest_on_empty_repo(tmp_path):
    # нет POLICY.yaml -> дефолт require_approval, а не выдуманное execute (fail-safe)
    policy = policy_engine.load_policy(tmp_path)
    assert policy["default"] == "require_approval"
    assert "отсутствует" in policy["source"]
    # нет журнала -> пусто, а не ошибка
    assert decision_log.ai_decisions(tmp_path) == []
    assert human_override.overrides(tmp_path) == []


@pytest.mark.unit
def test_governance_reads_a_declared_policy(tmp_path):
    (tmp_path / ".ai-ops").mkdir()
    (tmp_path / ".ai-ops" / "POLICY.yaml").write_text(
        "default: prepare\nactions:\n  merge: require_approval\n", encoding="utf-8")
    policy = policy_engine.load_policy(tmp_path)
    assert policy["default"] == "prepare"
    assert policy_engine.level_for("merge", policy) == "require_approval"
    # незаявленное действие падает на default
    assert policy_engine.level_for("scaffold", policy) == "prepare"
