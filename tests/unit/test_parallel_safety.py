"""Параллельные работы не толкаются на координационных файлах — проверка по ДИФФУ, не по scope.

ЗАМЕР 20.08.2026 на самом ките. Четыре ленты строили операционный слой параллельно, каждая
дописывала свою работу в общий planning/plan.yaml. Конфликты тривиальные, но защита ветки требует
«ветка актуальна перед мержем», и каждый мёрж делал остальные PR DIRTY — дорожка пересдач ~N².

ПОЧЕМУ ПО ДИФФУ, А НЕ ПО write_scope: первая редакция сверяла территорию работы (`registry/`,
`planning/`) со списком координационных файлов и мис-файрила — каталог законно охватывает файл
внутри, не собираясь его править. Смотрим, что PR РЕАЛЬНО изменил.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.validation import validate_parallel_safety as ps  # noqa: E402

COORD = ["planning/plan.yaml", "history/plan-history.yaml", "decisions/registry.yaml"]


@pytest.mark.unit
def test_a_feature_pr_mixing_code_with_the_plan_is_flagged():
    """Код территории + правка plan.yaml в одном PR — тот самый смешанный PR, что ловит DIRTY."""
    changed = ["ai_ops_kit/intelligence/health_product.py", "planning/plan.yaml",
               "tests/unit/test_health.py"]
    rep = ps.diff_mixes_code_with_coordination(changed, COORD)
    assert rep["mixed"] is True
    assert rep["coordination"] == ["planning/plan.yaml"]


@pytest.mark.unit
def test_a_pure_code_pr_is_clean():
    """Фичевый PR без координационных файлов — чисто (так и должно быть по протоколу)."""
    changed = ["ai_ops_kit/intelligence/health_product.py", "tests/unit/test_health.py",
               "newsfragments/health.feat.md"]
    assert ps.diff_mixes_code_with_coordination(changed, COORD)["mixed"] is False


@pytest.mark.unit
def test_a_pure_bookkeeping_pr_is_clean():
    """Только координационные файлы (PR координатора, одна рука) — допустимо, не смешение."""
    changed = ["planning/plan.yaml", "history/plan-history.yaml"]
    assert ps.diff_mixes_code_with_coordination(changed, COORD)["mixed"] is False


@pytest.mark.unit
def test_without_base_the_answer_is_unknown_not_clean(tmp_path):
    """Fail-open честно: нет реестра координаторов — «не проверено», а не «безопасно»."""
    root = tmp_path / "repo"
    root.mkdir()
    rep = ps.assess(root)
    assert rep["checked"] is False
    assert any("не проверено" in f for f in rep["findings"])


@pytest.mark.unit
def test_child_extends_the_coordination_list(tmp_path):
    """Дочка добавляет СВОИ координаторы через .ai/project/coordination-files.yaml."""
    root = tmp_path / "child"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    (root / ".ai" / "project").mkdir(parents=True)
    (root / ".ai" / "project" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [docs/PRODUCT_ROADMAP.md]\n", encoding="utf-8")
    paths = ps.coordination_paths(root)
    assert "planning/plan.yaml" in paths and "docs/PRODUCT_ROADMAP.md" in paths


@pytest.mark.unit
def test_real_diff_mode_on_a_git_repo(tmp_path):
    """Дифф-режим на настоящем git: смешанный коммит ловится, чистый — нет."""
    root = tmp_path / "g"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    (root / "planning").mkdir()
    def git(*a): subprocess.run(["git", "-C", str(root), *a], check=True,
                                capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t"); git("config", "user.name", "t")
    (root / "code.py").write_text("x=1\n", encoding="utf-8")
    (root / "planning" / "plan.yaml").write_text("kind: delivery-plan\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # смешанный коммит: код + план
    (root / "code.py").write_text("x=2\n", encoding="utf-8")
    (root / "planning" / "plan.yaml").write_text("kind: delivery-plan\nwork: []\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "mixed")
    rep = ps.assess(root, base=base)
    assert (rep.get("diff") or {}).get("mixed") is True, rep
