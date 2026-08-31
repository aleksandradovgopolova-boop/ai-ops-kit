"""Одна работа = один малый PR: код+тесты+newsfragment, green сам — проверка размера/охвата PR.

ПОВОД ЗАМЕРЕН (docs/parallel-execution-retro.md §1.7, §2). Лента 5 сложила всю Фазу 4 в ОДИН PR на
+2589 строк — незарегистрированный пакет, четыре модуля на 0% покрытия, пробитые потолки; долг лёг
на координатора серией мелких правок. Durable-fix — не договорённость, а ПРОВЕРКА размера PR.

Потолок берётся ИЗ ДАННЫХ (quality/pr-budget.yaml), а не вписан числом в тест: иначе реестр и
проверка разъедутся молча, как это уже было с derived-числами (ретро §1.2). Fail-open: без базы
диффа проверять нечего — «не проверено», а не «в пределах».
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.validation import validate_pr_size as ps  # noqa: E402

pytestmark = pytest.mark.unit

BUDGET_REL = "quality/pr-budget.yaml"
PREFIXES = ["newsfragments/", "docs/"]
COORD = {"planning/plan.yaml", "history/plan-history.yaml"}


# ─── потолок живёт В ДАННЫХ, а не в тесте ───────────────────────────────────────────────────────

def test_the_real_budget_lives_in_data_not_in_code():
    """Реестр потолков существует, числа читаются, и их НЕТ хардкодом в валидаторе."""
    budget = yaml.safe_load((PKG_ROOT / BUDGET_REL).read_text(encoding="utf-8"))
    ceilings = budget["ceilings"]
    assert isinstance(ceilings["max_diff_lines"], int)
    assert isinstance(ceilings["max_changed_files"], int)
    src = (PKG_ROOT / "ai_ops_kit" / "validation" / "validate_pr_size.py").read_text(encoding="utf-8")
    # Число потолка не должно быть вписано в исходник валидатора: оно приходит из данных.
    assert str(ceilings["max_diff_lines"]) not in src, "потолок строк захардкожен в валидаторе"
    assert str(ceilings["max_changed_files"]) not in src, "потолок файлов захардкожен в валидаторе"


# ─── измеритель: над/под/вровень с потолком, исключения ─────────────────────────────────────────

def _budget(max_files=15, max_lines=800):
    return {"ceilings": {"max_changed_files": max_files, "max_diff_lines": max_lines},
            "exemptions": {"prefixes": PREFIXES, "paths": sorted(COORD)}}


def test_a_pr_over_the_line_ceiling_is_flagged():
    numstat = [{"path": "ai_ops_kit/big.py", "added": 900, "deleted": 100}]
    m = ps.measure(numstat, PREFIXES, COORD)
    assert m["diff_lines"] == 1000
    assert m["diff_lines"] > 800


def test_a_pr_under_the_ceiling_is_clean():
    numstat = [{"path": "ai_ops_kit/small.py", "added": 40, "deleted": 10},
               {"path": "tests/unit/test_small.py", "added": 30, "deleted": 0}]
    m = ps.measure(numstat, PREFIXES, COORD)
    assert m["diff_lines"] == 80 and m["changed_files"] == 2


def test_a_pr_exactly_at_the_ceiling_is_not_over():
    """Ровно на потолке — ещё не превышение (строго >, как footprint)."""
    numstat = [{"path": "ai_ops_kit/x.py", "added": 800, "deleted": 0}]
    m = ps.measure(numstat, PREFIXES, COORD)
    assert m["diff_lines"] == 800
    assert not (m["diff_lines"] > 800)


def test_newsfragments_docs_and_coordination_are_exempt():
    """Сопроводительное и координационные файлы в размер PR не входят."""
    numstat = [
        {"path": "newsfragments/x.feat.md", "added": 50, "deleted": 0},
        {"path": "docs/guide.md", "added": 500, "deleted": 0},
        {"path": "planning/plan.yaml", "added": 400, "deleted": 300},
        {"path": "ai_ops_kit/code.py", "added": 20, "deleted": 5},
    ]
    m = ps.measure(numstat, PREFIXES, COORD)
    assert m["diff_lines"] == 25 and m["changed_files"] == 1
    assert m["counted"] == ["ai_ops_kit/code.py"]
    assert set(m["exempt"]) == {"newsfragments/x.feat.md", "docs/guide.md", "planning/plan.yaml"}


def test_a_huge_bookkeeping_pr_is_not_flagged_for_size():
    """Чистый chore(plan)-PR (только координация+newsfragment) — не «код территории», размер 0."""
    numstat = [{"path": "planning/plan.yaml", "added": 800, "deleted": 900},
               {"path": "history/plan-history.yaml", "added": 700, "deleted": 0},
               {"path": "newsfragments/close.quality.md", "added": 5, "deleted": 0}]
    m = ps.measure(numstat, PREFIXES, COORD)
    assert m["diff_lines"] == 0 and m["changed_files"] == 0


# ─── fail-open ──────────────────────────────────────────────────────────────────────────────────

def test_without_base_the_answer_is_unknown_not_clean(tmp_path):
    """Fail-open честно: есть потолки, но нет базы диффа — «не проверено», не «в пределах»."""
    root = tmp_path / "repo"
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "pr-budget.yaml").write_text(
        yaml.safe_dump(_budget()), encoding="utf-8")
    rep = ps.assess(root)                       # без base
    assert rep["checked"] is True
    assert rep["diff"] is None and rep["findings"] == []


def test_without_budget_the_answer_is_unknown_not_clean(tmp_path):
    """Нет реестра потолков — «не проверено», а не «в пределах»."""
    root = tmp_path / "repo"
    root.mkdir()
    rep = ps.assess(root)
    assert rep["checked"] is False
    assert any("не проверено" in f for f in rep["findings"])


def test_changed_numstat_returns_none_outside_git(tmp_path):
    """Вне git-репо changed_numstat -> None (не пустой список, не падение)."""
    assert ps.changed_numstat(tmp_path, "HEAD") is None


def test_a_broken_budget_is_skipped_not_crashed(tmp_path):
    """Битый реестр не роняет: yaml-ошибка проглатывается, потолков нет -> «не проверено»."""
    root = tmp_path / "r"
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "pr-budget.yaml").write_text("{битый: yaml: :", encoding="utf-8")
    assert ps.load_budget(root) == {}
    assert ps.assess(root)["checked"] is False


# ─── render говорит в каждом состоянии ──────────────────────────────────────────────────────────

def test_render_speaks_each_state(tmp_path):
    """render даёт человеку строку в каждом состоянии: не проверено / в пределах / превышение."""
    assert "не проверено" in ps.render(ps.assess(tmp_path / "empty"))
    root = tmp_path / "r"
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "pr-budget.yaml").write_text(yaml.safe_dump(_budget()), encoding="utf-8")
    assert "OK" in ps.render(ps.assess(root))
    over = {"checked": True, "ceilings": {"max_changed_files": 15, "max_diff_lines": 800},
            "diff": {"available": True, "over": True, "changed_files": 20, "diff_lines": 2589},
            "findings": ["PR меняет 2589 строк (потолок 800)"]}
    assert "✗" in ps.render(over)


# ─── main / exit-code + настоящий git ───────────────────────────────────────────────────────────

def _git_repo(root, max_files=15, max_lines=800):
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "pr-budget.yaml").write_text(
        yaml.safe_dump(_budget(max_files, max_lines)), encoding="utf-8")
    def git(*a): subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t"); git("config", "user.name", "t")
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return git, base


def test_main_json_and_exit_code(tmp_path, capsys):
    """main: --json печатает отчёт; --strict даёт 0 без диффа (не проверено ≠ нарушение)."""
    root = tmp_path / "g"; git, base = _git_repo(root)
    rc = ps.main(["x", str(root), "--json"])
    assert rc == 0
    assert '"kind": "pr-size"' in capsys.readouterr().out
    assert ps.main(["x", str(root), "--strict"]) == 0        # без --base «не проверено» диффа


def test_strict_reddens_an_oversized_pr_and_passes_a_small_one(tmp_path):
    """DONE-WHEN: --strict -> код 1 на PR сверх потолка; 0 на малом."""
    # ПРЕВЫШЕНИЕ: потолок строк искусственно мал (5), одна работа его пробивает -> красный
    big = tmp_path / "big"; git, base = _git_repo(big, max_lines=5)
    (big / "code.py").write_text("\n".join(f"x = {i}" for i in range(40)) + "\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "big")
    assert ps.main(["x", str(big), "--base", base, "--strict"]) == 1

    # МАЛЫЙ: тот же дифф, но потолок нормальный -> зелёный
    small = tmp_path / "small"; git2, base2 = _git_repo(small, max_lines=800)
    (small / "code.py").write_text("x = 2\n", encoding="utf-8")
    git2("add", "-A"); git2("commit", "-qm", "small")
    assert ps.main(["x", str(small), "--base", base2, "--strict"]) == 0


def test_strict_does_not_redden_a_big_but_exempt_pr(tmp_path):
    """Большой, но целиком исключённый (docs/newsfragments/координация) PR — не красный."""
    root = tmp_path / "exempt"; git, base = _git_repo(root, max_lines=5)
    (root / "docs").mkdir()
    (root / "docs" / "big.md").write_text("\n".join(str(i) for i in range(50)) + "\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "docs only")
    assert ps.main(["x", str(root), "--base", base, "--strict"]) == 0


def test_budget_flag_supplies_ceilings_when_child_has_none(tmp_path):
    """--budget: у дочки своего реестра нет, потолки берутся из клона кита -> есть чем мерить.

    Без этого дочкин контур структурно не мог покраснеть (нет ceilings -> checked=False)."""
    kit = tmp_path / "kit" / "quality"; kit.mkdir(parents=True)
    (kit / "pr-budget.yaml").write_text(yaml.safe_dump(_budget(max_lines=5)), encoding="utf-8")
    budget = str(kit / "pr-budget.yaml")

    child = tmp_path / "child"                              # у дочки СВОЕГО pr-budget.yaml нет
    def git(*a): subprocess.run(["git", "-C", str(child), *a], check=True, capture_output=True)
    child.mkdir()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t"); git("config", "user.name", "t")
    (child / "code.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(child), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert ps.assess(child)["checked"] is False            # сама по себе дочка — не проверено
    (child / "code.py").write_text("\n".join(f"x = {i}" for i in range(40)) + "\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "big")
    assert ps.main(["x", str(child), "--base", base, "--budget", budget, "--strict"]) == 1
