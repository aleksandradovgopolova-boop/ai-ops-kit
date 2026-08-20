# -*- coding: utf-8 -*-
"""План и состояние работы в git показывают ОДНО, и расхождение краснеет проверкой.

Работа `plan-agrees-with-git`, цель `plan-as-control-plane`.

ЗАМЕР 20.08.2026 на плане самого кита, до правки — две находки:

1. `audit-public-surface-and-guards` стояла `in_progress`, а её ветка `lane-b` целиком в
   `origin/main` (впереди 0): изменения работы в базе, план держал её открытой. Ни одна проверка
   этого не видела. Ровно класс аудита 19.08 («тридцать работ объявили закрытыми, настоящими были
   23; семь закрыли вопреки уликам»), только в другую сторону — и заметил снова не механизм.
2. Правило «открытый PR не сосуществует со статусом `todo`» живёт с 14.08 и СРАБОТАТЬ НЕ МОЖЕТ:
   оно смотрит поле `pr`, а в плане кита это поле встречается НОЛЬ раз — работы объявляют `branch`.
   Проверка без входных данных — то же «объявлено, но не исполняется».

ПОЧЕМУ ГИТ, А НЕ GITHUB. Прежнее решение — «проверяем форму, потому что объявленное состояние чужой
системы стареет молча» — верно про форж и неверно про git: он лежит рядом, отвечает мгновенно и не
требует сети. Поэтому здесь измеряется ровно то, что git знает точно.

Три обязательных теста на capability (AGENTS.md):
  * positive     — согласованный план не краснеет (иначе проверку выключат первым же днём);
  * fail-closed  — оба измеримых противоречия дают ОШИБКУ, и каждое названо своим;
  * side-effect  — неизвестность НЕ выдаётся за согласованность: ветки нет или ствола нет —
                   предупреждение словами, а не молчаливый зелёный.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import delivery_plan as dp   # noqa: E402

pytestmark = pytest.mark.unit

PLAN = {
    "schema_version": 1,
    "kind": "delivery-plan",
    "goals": [{"id": "g1", "status": "active"}],
    "work": [],
}


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


def _work(wid, status, branch=None):
    w = {"id": wid, "title": wid, "type": "engineering", "goal": "g1", "status": status,
         "owner_role": "engineer", "depends_on": [], "write_scope": ["src/"], "value": "medium"}
    if branch:
        w["branch"] = branch
    return w


def _plan(*works):
    return dict(PLAN, work=list(works))


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий со стволом `main` и одним коммитом — база для всех состояний ниже."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


def _branch_ahead(root, name):
    """Ветка с собственным коммитом — впереди ствола."""
    _git(root, "checkout", "-q", "-b", name)
    (root / f"{name.replace('/', '-')}.txt").write_text("y\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", f"feat: {name}")
    _git(root, "checkout", "-q", "main")


def _branch_in_base(root, name):
    """Ветка, чьи коммиты уже в стволе: её изменения влиты."""
    _branch_ahead(root, name)
    _git(root, "merge", "--no-ff", "-m", f"merge {name}", name)


# ─── positive ───────────────────────────────────────────────────────────────────────────────────

class TestAgreementIsQuiet:
    def test_matching_plan_has_no_findings(self, repo):
        _branch_ahead(repo, "feature/alpha")
        rep = dp.git_disagreements(_plan(_work("alpha", "in_progress", "feature/alpha")), repo)
        assert rep["measured"] is True
        assert rep["errors"] == [], rep["errors"]
        assert rep["warnings"] == [], rep["warnings"]

    def test_work_without_a_branch_is_not_judged(self, repo):
        """Работа без ветки — законное состояние (`todo` его и означает), а не расхождение."""
        rep = dp.git_disagreements(_plan(_work("alpha", "todo")), repo)
        assert rep["errors"] == [] and rep["warnings"] == []

    def test_closed_work_with_a_merged_branch_is_fine(self, repo):
        """`done` и ветка в базе — согласие, а не противоречие: именно так и выглядит закрытая работа."""
        _branch_in_base(repo, "feature/alpha")
        rep = dp.git_disagreements(_plan(_work("alpha", "done", "feature/alpha")), repo)
        assert rep["errors"] == [], rep["errors"]


# ─── fail-closed ────────────────────────────────────────────────────────────────────────────────

class TestMeasuredContradictionsAreErrors:
    def test_changes_in_base_while_the_plan_holds_the_work_open(self, repo):
        """ЗАМЕР 20.08 в чистом виде: ветка влита, работа объявлена идущей."""
        _branch_in_base(repo, "feature/alpha")
        rep = dp.git_disagreements(_plan(_work("alpha", "in_progress", "feature/alpha")), repo)
        assert len(rep["errors"]) == 1, rep
        e = rep["errors"][0]
        assert "УЖЕ в" in e and "feature/alpha" in e, e
        assert "alpha" in e, "ошибка не называет работу — искать придётся вручную"
        assert "history" in e, f"отказ без выхода — тупик, а не проверка: {e}"

    def test_todo_while_the_branch_moved_ahead(self, repo):
        """«Не начата» при ветке впереди ствола — работа начата, и это видно без форжа."""
        _branch_ahead(repo, "feature/beta")
        rep = dp.git_disagreements(_plan(_work("beta", "todo", "feature/beta")), repo)
        assert len(rep["errors"]) == 1, rep
        assert "'todo'" in rep["errors"][0] and "впереди" in rep["errors"][0], rep["errors"][0]

    def test_each_contradiction_is_named_separately(self, repo):
        """Две работы — две ошибки: свёрнутые в одну, они не дают понять, что именно править."""
        _branch_in_base(repo, "feature/alpha")
        _branch_ahead(repo, "feature/beta")
        rep = dp.git_disagreements(
            _plan(_work("alpha", "in_progress", "feature/alpha"),
                  _work("beta", "todo", "feature/beta")), repo)
        assert len(rep["errors"]) == 2, rep["errors"]
        # УТВЕРЖДЕНИЕ, А НЕ ВИДИМОСТЬ ЕГО. Первая версия этой строки была
        # `assert {...} == {True, False} or True` — то есть зелёной всегда: `or True` съедает
        # результат. Тот же класс, что `return` вместо `assert`, из-за которого в этом репозитории
        # были фактически отключены четыре валидатора.
        joined = " | ".join(rep["errors"])
        assert "work[alpha]" in joined and "work[beta]" in joined, joined
        assert sum("work[alpha]" in e for e in rep["errors"]) == 1, rep["errors"]
        assert sum("work[beta]" in e for e in rep["errors"]) == 1, rep["errors"]

    def test_the_error_reaches_the_validator_report(self, repo):
        """ШОВ: расхождение обязано доходить до отчёта `validate`, иначе механизм есть, а CI зелёный."""
        _branch_in_base(repo, "feature/alpha")
        (repo / "planning").mkdir(parents=True, exist_ok=True)
        (repo / "planning" / "plan.yaml").write_text(
            yaml.safe_dump(_plan(_work("alpha", "in_progress", "feature/alpha")),
                           allow_unicode=True, sort_keys=False), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "ai_ops_kit.planning.delivery_plan",
                            "validate", str(repo), "--json"],
                           cwd=str(KIT), capture_output=True, text=True)
        assert '"errors"' in r.stdout, r.stdout + r.stderr
        assert "УЖЕ в" in r.stdout, (
            "расхождение не доехало до отчёта validate — проверка живёт, а контур её не спрашивает:\n"
            + r.stdout + r.stderr)
        assert r.returncode != 0, "отчёт с ошибками вернул успех — CI такого не заметит"


# ─── side-effect proof: неизвестность не равна согласованности ───────────────────────────────────

class TestUnknownIsNotAgreement:
    def test_missing_branch_is_a_warning_that_says_so(self, repo):
        """Ветку удалили после слияния ИЛИ не выкачали — различить нельзя, и мы не угадываем."""
        rep = dp.git_disagreements(_plan(_work("alpha", "in_progress", "feature/gone")), repo)
        assert rep["errors"] == [], "неизмеренное подано как противоречие"
        assert len(rep["warnings"]) == 1, rep
        w = rep["warnings"][0]
        assert "НЕ ИЗМЕРЕНО" in w and "feature/gone" in w, w
        assert "не «согласовано»" in w, f"предупреждение читается как зелёное: {w}"

    def test_no_trunk_means_unmeasured_not_agreed(self, tmp_path):
        """Нет ствола (или не git) — `measured: False`, и об этом сказано словами."""
        bare = tmp_path / "nogit"
        bare.mkdir()
        rep = dp.git_disagreements(_plan(_work("alpha", "in_progress", "feature/alpha")), bare)
        assert rep["measured"] is False
        assert rep["errors"] == []
        assert any("не измерено" in w for w in rep["warnings"]), rep["warnings"]

    def test_trunk_is_the_trunk_not_the_current_branch(self, repo):
        """ГРАНИЦА, ОПЛАЧЕННАЯ ЗАМЕРОМ 20.08: `pipeline_git._resolve_base` в рабочей копии работы
        отдаёт САМУ эту ветку, и сверка `ai-ops/w` против `ai-ops/w` объявляла любую запись влитой.
        Здесь ствол берётся явным списком кандидатов, поэтому ответ не зависит от того, где стоит
        HEAD."""
        _branch_ahead(repo, "feature/alpha")
        _git(repo, "checkout", "-q", "feature/alpha")
        assert dp._trunk_ref(repo) in ("main", "origin/main")
        rep = dp.git_disagreements(_plan(_work("alpha", "in_progress", "feature/alpha")), repo)
        assert rep["errors"] == [], (
            f"стоя НА ветке работы, сверка объявила её влитой: {rep['errors']}")


# ─── план самого кита согласован ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_the_kits_own_plan_agrees_with_git():
    """Кит применяет правило к себе. Пропуск ТОЛЬКО без истории git — и с названной причиной:
    прогон мутационных проб копирует дерево без `.git`, и там сверять нечем."""
    if not (KIT / ".git").exists():
        pytest.skip("нет истории git (копия дерева) — состояние работ здесь измерить нечем")
    plan = dp.load(KIT)
    assert plan is not None, "у кита нет плана — сверять нечего"
    rep = dp.git_disagreements(plan, KIT)
    assert rep["errors"] == [], (
        "план кита расходится с git — то самое, что 19.08 нашёл человек при аудите:\n  "
        + "\n  ".join(rep["errors"]))
