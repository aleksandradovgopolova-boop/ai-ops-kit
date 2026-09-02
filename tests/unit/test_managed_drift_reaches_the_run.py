"""Предупреждение о незакоммиченном managed-слое ДОХОДИТ до прогона, а не только существует.

ПОВОД — СОБСТВЕННАЯ ПРОВЕРКА КИТА. `validate_mutation_probes` требует: у механизма с охранными
пробами обязана быть проба ШВА, потому что охранная доказывает, что проверка внутри механизма
чем-то проверяется, и НЕ доказывает, что механизм кто-то зовёт. У `pipeline_git.py` охранная проба
была (`managed-drift-checks-the-right-path`), шовной — не было, и валидатор говорил об этом прямо:
«снятие охраны поймается, а отключённый ВЫЗОВ механизма — нет».

Цена молчания названа замером B2-27: `update --in-place` оставляет managed-файлы в рабочем дереве,
а прогон изолируется в worktree от HEAD. Незакоммиченное туда не попадает — прогон идёт на СТАРОМ
ките, и `doctor` при этом говорит «версии ✓». Владелец обновил кит, запустил прогон и получил
поведение прежней версии, без единого слова о причине.

Три обязательных теста на capability (AGENTS.md):
  * positive     — конвейер зовёт проверку и печатает её предупреждение человеку;
  * fail-closed  — предупреждение появляется ДО изоляции, то есть до первого вызова модели;
  * side-effect  — чистое дерево не порождает предупреждения (проверка не шумит вхолостую).
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.engine import execution_pipeline as ep
# deep-cut: _setup_isolation вынесен в pipeline_setup и резолвит _managed_drift_preflight из ЕГО
# globals — подмену ставим там, где механизм реально живёт, а не на реэкспорте в execution_pipeline.
from ai_ops_kit.engine import pipeline_setup as ps

pytestmark = pytest.mark.unit

MARKER = "managed-файлы изменены, но не закоммичены (7 файл(ов))"


@pytest.fixture
def child(tmp_path):
    """Минимальный git-репозиторий: `_resolve_base` обязан отвечать настоящим git'ом."""
    root = tmp_path / "child"
    (root / ".ai" / "managed").mkdir(parents=True)
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", *a], cwd=str(root), capture_output=True, check=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-qm", "base")
    return root


def _run_until_isolation(child, monkeypatch, preflight):
    """Прогон, остановленный сразу ПОСЛЕ преflight'ов: явная несуществующая база — объявленный
    отказ до модели и до worktree. Дальше конвейер не идёт, и тест не платит за живой прогон."""
    monkeypatch.setattr(ps, "_managed_drift_preflight", preflight)
    return ep.run_pipeline(
        task="проба шва", signals={}, child_root=child, proposer=None,
        plan={"workitem_id": "wi-seam-probe"}, isolate=True, base="ветки-такой-нет")


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_the_pipeline_calls_the_check_and_prints_its_warning(child, monkeypatch, capsys):
    """ШОВ: снятие вызова из конвейера обязано ронять тест, а не оставлять его зелёным."""
    calls = []

    def spy(root):
        calls.append(root)
        return {"warning": MARKER}

    _run_until_isolation(child, monkeypatch, spy)

    assert calls, "конвейер не позвал проверку дрейфа managed — прогон молча пойдёт на старом ките"
    assert str(calls[0]) == str(child), f"проверку позвали не для того репозитория: {calls[0]}"
    assert MARKER in capsys.readouterr().out, "проверка позвана, а человеку ничего не сказано"


def test_the_real_check_is_the_one_that_is_wired(child, capsys):
    """Позван НАСТОЯЩИЙ механизм, а не тёзка: подложенный дрейф доходит до человека без подмен."""
    drifted = child / ".ai" / "managed" / "VERSION"
    drifted.write_text("9.9.9\n", encoding="utf-8")

    ep.run_pipeline(task="проба шва", signals={}, child_root=child, proposer=None,
                    plan={"workitem_id": "wi-seam-probe"}, isolate=True, base="ветки-такой-нет")

    assert "managed-файлы изменены, но не закоммичены" in capsys.readouterr().out


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_the_warning_comes_before_isolation(child, monkeypatch, capsys):
    """Предупреждение обязано звучать ДО первого вызова модели — иначе оно бесплатно только на словах.

    Признак: прогон остановлен объявленным отказом base-preflight, а предупреждение уже напечатано.
    """
    rep = _run_until_isolation(child, monkeypatch, lambda root: {"warning": MARKER})

    assert rep["status"] == "error" and "base-preflight" in (rep["error"] or ""), rep
    assert MARKER in capsys.readouterr().out, (
        "прогон уже остановлен, а предупреждение не прозвучало — значит, оно звучит позже изоляции")


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_a_clean_tree_produces_no_warning(child, capsys):
    """КОНТРОЛЬ: без дрейфа проверка молчит. Иначе тесты выше были бы зелёными и на коде,
    который печатает предупреждение всегда."""
    ep.run_pipeline(task="проба шва", signals={}, child_root=child, proposer=None,
                    plan={"workitem_id": "wi-seam-probe"}, isolate=True, base="ветки-такой-нет")

    assert "managed-файлы изменены" not in capsys.readouterr().out
