"""Пороги меряются против итога слияния, а не ветки PR (gate-measures-merge-result).

ПОВОД (разбор 20.08.2026): гейты меряли ветку PR; код лент, сложенный в main, дрейфовал выше
порога незаметно (490 -> 498 файлов тихо) и всплывал на первом СЛЕДУЮЩЕМ PR, а не на виновнике.

МЕХАНИЗМ: родной GitHub merge queue строит временный merge-коммит и требует все обязательные
контексты НА НЁМ. Механизм живёт в двух местах, и оба умеют тихо сломаться:

  1. Триггер `merge_group:` в workflow. Без него джоба в очереди не запускается вовсе —
     обязательный контекст не отдан, очередь висит вечно (капкан статусов: 20.08 удаление джобы
     python39-compat повесило ВСЕ PR до admin-действия владельца).
  2. Условие draft-фильтра. `github.event.pull_request.draft == false` при merge_group даёт
     `null == false` = ложь — джоба тихо скипается, исход тот же. Правильная форма:
     `github.event_name != 'pull_request' || ...`.

Этот тест — страж обоих. Снятие триггера или возврат старой формы условия = возвращение
оплаченного дефекта, и оно обязано быть громким, а не тихим.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
WORKFLOWS = PKG / ".github" / "workflows"

# Workflow, отдающие ОБЯЗАТЕЛЬНЫЕ контексты защиты main (smoke — pr-smoke; остальные —
# package-quality). Список закрыт намеренно: новый required-workflow добавляется сюда осознанно.
REQUIRED_CONTEXT_WORKFLOWS = ("package-quality.yml", "pr-smoke.yml")


def _on_block(text: str) -> str:
    """Блок `on:` верхнего уровня (до первого другого top-level ключа)."""
    m = re.search(r"^on:\n((?:[ \t#].*\n|\n)*)", text, re.M)
    assert m, "workflow без блока on:"
    return m.group(1)


@pytest.mark.contract
@pytest.mark.parametrize("wf", REQUIRED_CONTEXT_WORKFLOWS)
def test_required_workflow_triggers_on_merge_group(wf):
    """Каждый workflow с обязательными контекстами объявляет merge_group."""
    text = (WORKFLOWS / wf).read_text(encoding="utf-8")
    on = _on_block(text)
    assert re.search(r"^\s*merge_group\s*:", on, re.M), (
        f"{wf}: в on: нет merge_group — обязательные контексты этого workflow в очереди слияния "
        f"не запустятся, и очередь повиснет (капкан статусов 20.08)")


@pytest.mark.contract
def test_draft_filter_does_not_skip_merge_group():
    """Draft-фильтр не выключает джобы вне pull_request (merge_group/push).

    Запрещена форма `if: github.event.pull_request.draft == false` БЕЗ защитного
    `github.event_name != 'pull_request'`: при merge_group `pull_request` = null,
    `null == false` ложно, джоба тихо скипается — обязательный контекст не отдан.
    """
    for wf in REQUIRED_CONTEXT_WORKFLOWS:
        text = (WORKFLOWS / wf).read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*if:\s*(.+)$", text, re.M):
            cond = m.group(1)
            if "pull_request.draft" not in cond:
                continue
            assert "github.event_name != 'pull_request'" in cond, (
                f"{wf}: условие `{cond.strip()}` скипает джобу в merge_group "
                f"(null == false ложно) — обязательный контекст не отдастся, очередь повиснет")


@pytest.mark.contract
def test_guard_would_catch_the_defect():
    """Страж не слеп: старая форма условия (ровно та, что жила до v3.38) им ловится."""
    old = "if: github.event.pull_request.draft == false"
    assert "github.event_name != 'pull_request'" not in old  # форма-нарушитель распознаваема
    # и merge_group-детектор реагирует на отсутствие триггера
    assert not re.search(r"^\s*merge_group\s*:", "on:\n  pull_request:\n", re.M)


@pytest.mark.contract
def test_pr_title_check_step_is_gated_to_pull_request():
    """Шаг проверки заголовка PR в обязательном workflow не запускается на merge_group.

    В merge_group заголовка PR нет; шаг с PR_TITLE_CHECK=1 без `if: pull_request` сделал бы
    pytest.fail, обязательный контекст упал бы и очередь слияния повисла навсегда (капкан
    статусов). Ищем YAML-шаги, ставящие PR_TITLE_CHECK, и требуем на них gate по событию.
    """
    for wf in REQUIRED_CONTEXT_WORKFLOWS:
        text = (WORKFLOWS / wf).read_text(encoding="utf-8")
        # разбить на шаги по маркеру "- name:"; в шаге с PR_TITLE_CHECK обязан быть if pull_request
        steps = re.split(r"\n      - (?=name:|uses:|run:)", text)
        for step in steps:
            # env-ключ с двоеточием, не слово в прозе-комментарии (там "PR_TITLE_CHECK=1")
            if not re.search(r"PR_TITLE_CHECK:\s", step):
                continue
            assert "github.event_name == 'pull_request'" in step, (
                f"{wf}: шаг с PR_TITLE_CHECK без `if: github.event_name == 'pull_request'` — "
                f"на merge_group он уронит обязательный контекст, очередь повиснет")
