"""Факт работы считается по git, а не по счётчику брокера.

НАХОДКА ИИ-СРЕДЫ, МЕШАВШАЯ КАЖДЫЙ ДЕНЬ. Движок брал «есть ли правки» из `loop.applied_writes` —
счётчика write-операций, прошедших через брокера. Но писать можно иначе: writer уровня `claude -p`
правит файлы своими инструментами, `sed -i` правит через shell, а модель может закоммитить сама.
Тогда счётчик ноль при живом коммите, и работа получала статус «blocked: код не написан — правок 0».
Дважды за один день. По отчёту выглядело, будто кит не работает, хотя он работал — и это путало не
только владельца, но и любого, кто читал бы такой отчёт.

Три обязательных теста на capability:
  * positive     — коммит с файлами считается работой, каким бы каналом она ни была произведена;
                   свой коммит модели (чистое дерево, HEAD ушёл от базы) виден движку;
  * fail-closed  — пустой прогон остаётся пустым: предикат не начинает возвращать True всегда;
  * side-effect  — статус активной работы и человеческий вывод следуют ТОМУ ЖЕ предикату, а не
                   каждый своему (иначе отчёт и реестр снова разойдутся).
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine.pipeline_helpers import work_produced  # noqa: E402
from ai_ops_kit.engine.pipeline_git import _head_advanced     # noqa: E402


# ── positive ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rep,why", [
    ({"loop": {"applied_writes": 2}}, "правки через брокера"),
    ({"loop": {"applied_writes": 0},
      "commit": {"sha": "a" * 40, "changed_files": ["src/a.py"]}}, "writer своими инструментами"),
    ({"commit": {"sha": "b" * 40, "changed_files": ["x.ts", "y.ts"],
                 "produced_by": "model-commit"}}, "модель закоммитила сама"),
])
def test_any_channel_counts_as_work(rep, why):
    assert work_produced(rep) is True, f"работа не засчитана: {why}"


def test_model_own_commit_is_visible_to_the_engine(tmp_path):
    """Дерево ЧИСТОЕ, `applied` пусто — и всё же работа есть: HEAD ушёл от базы прогона.

    Именно так выглядит прогон, в котором модель сама позвала `git commit`.
    """
    root = tmp_path / "repo"
    root.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()

    # До правок HEAD на базе — движок не должен считать это работой.
    moved, _ = _head_advanced(root, base)
    assert moved is False

    # Модель правит и коммитит САМА.
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "модель сделала сама")

    moved, head = _head_advanced(root, base)
    assert moved is True, "свой коммит модели не виден: дерево чистое, и движок решит, что правок нет"
    assert head and head != base


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rep", [
    {}, {"loop": {"applied_writes": 0}},
    {"commit": {"sha": None, "changed_files": []}},
    # Коммит есть, а файлов в нём нет — работы не произведено, и выдавать это за работу нельзя.
    {"loop": {"applied_writes": 0}, "commit": {"sha": "c" * 40, "changed_files": []}},
])
def test_empty_run_stays_empty(rep):
    assert work_produced(rep) is False, "предикат стал возвращать True на пустом прогоне"


def test_head_advanced_is_silent_without_a_base(tmp_path):
    """Без базы сравнивать не с чем — это «не знаю», а не «работа есть»."""
    moved, head = _head_advanced(tmp_path, None)
    assert moved is False and head is None


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_status_and_human_output_use_the_same_predicate():
    """Реестр активной работы и человеческий вывод обязаны судить по ОДНОМУ правилу.

    Пока каждый считал по-своему, отчёт говорил «правок 0», статус — «код не написан», а в коммите
    лежали файлы. Проверяем разбором: `applied_writes` больше не является судьёй.
    """
    src = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "work_produced"]
    assert len(calls) >= 2, ("общий предикат зовётся реже двух раз — значит кто-то снова судит "
                             "по счётчику брокера")
    # И самого счётчика в роли судьи больше нет.
    assert '_wrote = ((rep.get("loop") or {}).get("applied_writes") or 0) > 0' not in src


def test_pipeline_reports_how_the_work_was_produced():
    """Канал работы назван в отчёте: «правок 0» рядом с живым коммитом читается как «кит не работает»."""
    src = (KIT / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")
    assert '"produced_by": work_produced_by' in src, "происхождение работы не попадает в отчёт"
    assert 'work_produced_by = "model-commit"' in src, "свой коммит модели не называется в отчёте"
    tree = ast.parse(src)
    called = {getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_head_advanced" in called, "конвейер не проверяет, ушёл ли HEAD от базы"
