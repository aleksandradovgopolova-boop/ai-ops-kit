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


@pytest.mark.unit
def test_render_speaks_each_state(tmp_path):
    """render даёт человеку строку в каждом состоянии: не проверено / чисто / нарушение."""
    root = tmp_path / "r"; (root / "registry").mkdir(parents=True)
    # не проверено (нет реестра)
    assert "не проверено" in ps.render(ps.assess(tmp_path / "empty"))
    # чисто
    (root / "registry" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    assert "OK" in ps.render(ps.assess(root))
    # нарушение
    bad = {"checked": True, "coordination_files": ["planning/plan.yaml"],
           "findings": ["PR смешивает код с planning/plan.yaml"]}
    assert "✗" in ps.render(bad)


@pytest.mark.unit
def test_main_json_and_exit_code(tmp_path, capsys):
    """main: --json печатает отчёт; --strict даёт код 1 на смешанном диффе, 0 без него."""
    root = tmp_path / "g"; (root / "registry").mkdir(parents=True)
    (root / "registry" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    rc = ps.main(["x", str(root), "--json"])
    assert rc == 0
    assert '"kind": "parallel-safety"' in capsys.readouterr().out
    # без --base «не проверено» диффа — но strict без нарушения = 0
    assert ps.main(["x", str(root), "--strict"]) == 0


@pytest.mark.unit
def test_a_broken_registry_is_skipped_not_crashed(tmp_path):
    """Битый reg-файл не роняет: yaml-ошибка проглатывается, список остаётся из читаемых."""
    root = tmp_path / "r"; (root / "registry").mkdir(parents=True)
    (root / "registry" / "coordination-files.yaml").write_text("{битый: yaml: :", encoding="utf-8")
    assert ps.coordination_paths(root) == []


@pytest.mark.unit
def test_changed_files_returns_none_outside_git(tmp_path):
    """Вне git-репо changed_files -> None (не пустой список, не падение)."""
    assert ps.changed_files(tmp_path, "HEAD") is None


@pytest.mark.unit
def test_defaults_supplies_base_list_when_child_has_none(tmp_path):
    """--defaults: у дочки своего реестра нет, база берётся из клона кита -> есть что проверять.

    Без этого дочкин контур структурно не мог покраснеть (coordination_paths=[] -> checked=False),
    и вторая половина done-when («краснит в контуре дочки») была бы недостижима."""
    child = tmp_path / "child"; child.mkdir()            # у дочки НЕТ registry/coordination-files.yaml
    kit = tmp_path / "kit" / "registry"; kit.mkdir(parents=True)
    (kit / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    assert ps.coordination_paths(child) == []            # сама по себе дочка — пусто
    paths = ps.coordination_paths(child, defaults=str(kit / "coordination-files.yaml"))
    assert paths == ["planning/plan.yaml"]               # база из клона докатилась
    # и дочка всё ещё расширяет своим .ai/project/...
    (child / ".ai" / "project").mkdir(parents=True)
    (child / ".ai" / "project" / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [docs/ROADMAP.md]\n", encoding="utf-8")
    both = ps.coordination_paths(child, defaults=str(kit / "coordination-files.yaml"))
    assert both == ["docs/ROADMAP.md", "planning/plan.yaml"]


def _git_repo_with_base(root, coord_registry=True):
    """Собрать git-репо с базовым коммитом. -> (git, base_sha). Опционально с реестром координаторов."""
    (root / "planning").mkdir(parents=True)
    if coord_registry:
        (root / "registry").mkdir(parents=True)
        (root / "registry" / "coordination-files.yaml").write_text(
            "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    def git(*a): subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t"); git("config", "user.name", "t")
    (root / "code.py").write_text("x=1\n", encoding="utf-8")
    (root / "planning" / "plan.yaml").write_text("kind: delivery-plan\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return git, base


@pytest.mark.unit
def test_strict_reddens_a_mixed_pr_and_passes_a_clean_one(tmp_path):
    """DONE-WHEN (контур кита): --strict -> код 1 на PR, смешавшем код с планом; 0 на чистом."""
    # ГРЯЗНЫЙ: код + план в одном диффе -> красный (код 1)
    dirty = tmp_path / "dirty"; git, base = _git_repo_with_base(dirty)
    (dirty / "code.py").write_text("x=2\n", encoding="utf-8")
    (dirty / "planning" / "plan.yaml").write_text("kind: delivery-plan\nwork: []\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "mixed")
    assert ps.main(["x", str(dirty), "--base", base, "--strict"]) == 1

    # ЧИСТЫЙ: только код -> зелёный (код 0)
    clean = tmp_path / "clean"; git2, base2 = _git_repo_with_base(clean)
    (clean / "code.py").write_text("x=2\n", encoding="utf-8")
    git2("add", "-A"); git2("commit", "-qm", "code only")
    assert ps.main(["x", str(clean), "--base", base2, "--strict"]) == 0


@pytest.mark.unit
def test_strict_reddens_in_the_child_context_via_defaults(tmp_path):
    """DONE-WHEN (контур дочки): у дочки нет своего реестра, база — через --defaults из клона кита.

    Смешанный PR дочки краснит проверку (код 1), чистый — нет (код 0). Так вторая половина
    done-when («краснит в обоих контурах») достижима, а не структурно невозможна."""
    kit = tmp_path / "kit" / "registry"; kit.mkdir(parents=True)
    (kit / "coordination-files.yaml").write_text(
        "schema_version: 1\npaths: [planning/plan.yaml]\n", encoding="utf-8")
    defaults = str(kit / "coordination-files.yaml")

    # ГРЯЗНЫЙ дочкин PR: у дочки СВОЕГО реестра нет — красный держится только на --defaults
    dirty = tmp_path / "child-dirty"; git, base = _git_repo_with_base(dirty, coord_registry=False)
    (dirty / "code.py").write_text("x=2\n", encoding="utf-8")
    (dirty / "planning" / "plan.yaml").write_text("kind: delivery-plan\nwork: []\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "mixed")
    assert ps.coordination_paths(dirty) == []            # без --defaults проверять было бы нечего
    assert ps.main(["x", str(dirty), "--base", base, "--defaults", defaults, "--strict"]) == 1

    # ЧИСТЫЙ дочкин PR: только код -> зелёный
    clean = tmp_path / "child-clean"; git2, base2 = _git_repo_with_base(clean, coord_registry=False)
    (clean / "code.py").write_text("x=2\n", encoding="utf-8")
    git2("add", "-A"); git2("commit", "-qm", "code only")
    assert ps.main(["x", str(clean), "--base", base2, "--defaults", defaults, "--strict"]) == 0


@pytest.mark.unit
def test_a_kit_update_pr_is_not_flagged_though_it_touches_the_plan():
    """#384: install/update-PR кита (правит .ai/managed/VERSION) + миграция плана — НЕ смешение.

    Апдейт сам мигрирует план/историю; эти координационные правки — вывод машинной миграции, а не
    рука параллельной ленты. Признак — `.ai/managed/VERSION` в диффе."""
    changed = [".ai/managed/VERSION", ".ai/managed/manifest/ai-ops-manifest.yaml",
               "planning/plan.yaml", "history/plan-history.yaml"]
    rep = ps.diff_mixes_code_with_coordination(changed, COORD)
    assert rep["kit_update"] is True
    assert rep["mixed"] is False
    # МУТАЦИОННЫЙ КОНТРОЛЬ: тот же смешанный дифф, но БЕЗ маркера апдейта — снова смешение.
    # Уберёшь `and not kit_update` в фиксе — этот assert (и верхний) покраснеют.
    no_marker = ["ai_ops_kit/intelligence/health_product.py", "planning/plan.yaml"]
    assert ps.diff_mixes_code_with_coordination(no_marker, COORD)["mixed"] is True


@pytest.mark.unit
def test_strict_passes_a_kit_update_pr_that_migrates_the_plan(tmp_path):
    """DONE-WHEN #384: --strict пропускает апдейт-PR (managed VERSION + миграция плана) кодом 0;
    тот же смешанный дифф БЕЗ .ai/managed/VERSION остаётся красным (код 1) — маркер и решает."""
    # АПДЕЙТ: managed VERSION + план в одном диффе -> зелёный (это и был случай wow-repo #11)
    upd = tmp_path / "upd"; git, base = _git_repo_with_base(upd)
    (upd / ".ai" / "managed").mkdir(parents=True)
    (upd / ".ai" / "managed" / "VERSION").write_text("3.39.0\n", encoding="utf-8")
    (upd / "planning" / "plan.yaml").write_text("kind: delivery-plan\nwork: []\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "chore(ai-ops): update")
    assert ps.main(["x", str(upd), "--base", base, "--strict"]) == 0

    # КОНТРОЛЬ: тот же смешанный дифф, но без managed VERSION -> по-прежнему красный
    plain = tmp_path / "plain"; git2, base2 = _git_repo_with_base(plain)
    (plain / "code.py").write_text("x=2\n", encoding="utf-8")
    (plain / "planning" / "plan.yaml").write_text("kind: delivery-plan\nwork: []\n", encoding="utf-8")
    git2("add", "-A"); git2("commit", "-qm", "feature + plan")
    assert ps.main(["x", str(plain), "--base", base2, "--strict"]) == 1
