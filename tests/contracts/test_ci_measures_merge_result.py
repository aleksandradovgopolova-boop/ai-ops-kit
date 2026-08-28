"""CI меряет coverage и footprint против итога слияния, а не ветки PR.

Работа `gate-measures-merge-result`, цель `checks-that-run`.

ЗАМЕР 20.08.2026 (docs/parallel-execution-retro.md §1 п.3): гейты меряют ветку PR; код лент,
сложенный в main, дрейфует выше порога незаметно и всплывает на первом следующем PR, а не на
виновнике (main тихо ушёл 490→498 файлов).

РЕШЕНИЕ: workflows, в которых меряются пороги (coverage, footprint/delivery-budget), обязаны
иметь триггер `merge_group`. Merge queue создаёт временный merge-коммит (PR + base); checkout
в этом контексте даёт именно результат слияния — дрейф main невозможен.

Три invariant-проверки:
  * coverage-джоба (порог 70%) живёт в workflow с merge_group-триггером;
  * джоба, исполняющая тесты поставки (delivery budget), тоже;
  * качество `quality`-джобы не падает на merge_group-событии (if-условие корректно).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
WORKFLOWS = KIT / ".github" / "workflows"

pytestmark = [pytest.mark.contract, pytest.mark.critical_path]


@pytest.fixture(scope="module")
def package_quality():
    return yaml.safe_load((WORKFLOWS / "package-quality.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pr_smoke():
    return yaml.safe_load((WORKFLOWS / "pr-smoke.yml").read_text(encoding="utf-8"))


class TestMergeGroupTriggerExists:
    """Пороги меряются на результате слияния, а не на ветке PR."""

    def test_package_quality_has_merge_group_trigger(self, package_quality):
        """Coverage (порог 70%) и тесты поставки (delivery budget) живут в package-quality.
        Без merge_group-триггера они меряют ветку PR — main дрейфует выше незаметно."""
        triggers = package_quality.get("on", package_quality.get(True, {}))
        assert "merge_group" in triggers, (
            "package-quality.yml не имеет триггера merge_group: coverage и footprint "
            "меряются на ветке PR, а не на результате слияния — дрейф main невозможен "
            "только когда пороги проверяются на merge-коммите (gate-measures-merge-result)")

    def test_pr_smoke_has_merge_group_trigger(self, pr_smoke):
        """Smoke-слой тоже должен запускаться на merge-коммите: критические тесты, включая
        контрактные, меряются против того, что реально ляжет в main."""
        triggers = pr_smoke.get("on", pr_smoke.get(True, {}))
        assert "merge_group" in triggers, (
            "pr-smoke.yml не имеет триггера merge_group: критические тесты меряются "
            "на ветке PR, а не на результате слияния")

    def test_merge_group_requests_checks(self, package_quality):
        """Тип `checks_requested` — единственный, при котором merge queue ждёт результат CI."""
        triggers = package_quality.get("on", package_quality.get(True, {}))
        mg = triggers["merge_group"]
        # YAML: `types: [checks_requested]` парсится как список; `merge_group: {}` как dict
        if isinstance(mg, dict):
            assert "checks_requested" in mg.get("types", []), (
                "merge_group без types: [checks_requested] — queue не дождётся CI")


class TestQualityJobRunsOnMergeGroup:
    """if-условие quality-джобы не должно отсекать merge_group-события."""

    def test_quality_job_does_not_skip_merge_group(self, package_quality):
        """Прежнее условие `github.event.pull_request.draft == false` отсекало merge_group:
        у merge_group-события нет pull_request-объекта, и условие давало false. Джоба
        пропускалась — и coverage/footprint на merge-коммите не мерялись вовсе.

        Два допустимых паттерна (оба доказанно работают):
          * явное упоминание merge_group: `event_name == 'merge_group' || ...`
          * отрицание pull_request: `event_name != 'pull_request' || ...` — покрывает
            merge_group, push и workflow_dispatch; merge_group != pull_request → true
        """
        jobs = package_quality.get("jobs", {})
        quality = jobs.get("quality", {})
        if_condition = quality.get("if", "")
        mentions_merge_group = "merge_group" in if_condition
        negates_pull_request = "!= 'pull_request'" in if_condition or '!= "pull_request"' in if_condition
        assert mentions_merge_group or negates_pull_request, (
            f"if-условие quality-джобы не разрешает merge_group: '{if_condition}'. "
            "Ожидается явное упоминание merge_group или отрицание pull_request "
            "(event_name != 'pull_request') — иначе джоба пропускается на merge-коммите")
