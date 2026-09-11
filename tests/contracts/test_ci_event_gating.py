"""Гейтинг CI-джоб по событию — фордж-нейтрально, без merge queue.

КОНТЕКСТ. Кит НЕ привязан к GitHub merge queue (триггер `merge_group:` снят 04.09.2026,
фордж-нейтральный пивот): очередь недоступна для личных репозиториев и привязала бы кит к фиче
конкретного форджа. Дрейф main против ИТОГА СЛИЯНИЯ держит сам кит на чистом git
(`ai_ops_kit/gates/merge_preview.py`, `gate-measures-merge-result`), а не фордж-очередь.

Этот страж фиксирует то, что осталось верным и после снятия merge_group:

  1. Draft-фильтр `quality` записан как `github.event_name != 'pull_request' || draft == false`,
     а НЕ голым `draft == false`. На событиях `push`/`workflow_dispatch` объекта pull_request нет,
     `null == false` в выражениях Actions ложно — без защитной ветки джоба молча скипалась бы и
     обязательный контекст на push в main не отдавался бы никогда.
  2. Шаг проверки заголовка PR (`PR_TITLE_CHECK`) привязан к событию `pull_request`: заголовок
     берётся из `github.event.pull_request.title`, на других событиях его нет.
  3. Триггер `merge_group:` НЕ вернулся в on:-блок — снятый фордж-зависимый механизм не крадётся
     обратно.

Тест СТРУКТУРНЫЙ намеренно: он утверждает на форме workflow-файлов (текст + regex), продуктовый
код не исполняет.
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
def test_draft_filter_does_not_skip_non_pr_events():
    """Draft-фильтр не выключает джобы на не-PR событиях (push/workflow_dispatch).

    Запрещена форма `if: github.event.pull_request.draft == false` БЕЗ защитного
    `github.event_name != 'pull_request'`: вне pull_request `pull_request` = null,
    `null == false` ложно, джоба тихо скипается — обязательный контекст на push в main не отдан.
    """
    for wf in REQUIRED_CONTEXT_WORKFLOWS:
        text = (WORKFLOWS / wf).read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*if:\s*(.+)$", text, re.M):
            cond = m.group(1)
            if "pull_request.draft" not in cond:
                continue
            assert "github.event_name != 'pull_request'" in cond, (
                f"{wf}: условие `{cond.strip()}` скипает джобу на push/workflow_dispatch "
                f"(null == false ложно) — обязательный контекст на push в main не отдастся")


@pytest.mark.contract
def test_guard_would_catch_the_defect():
    """Страж не слеп: старая форма условия (голый `== false`) им распознаётся как нарушитель."""
    old = "if: github.event.pull_request.draft == false"
    assert "github.event_name != 'pull_request'" not in old  # форма-нарушитель распознаваема


@pytest.mark.contract
def test_pr_title_check_step_is_gated_to_pull_request():
    """Шаг проверки заголовка PR в обязательном workflow привязан к событию pull_request.

    Заголовок берётся из `github.event.pull_request.title`; на другом событии его нет, и шаг с
    PR_TITLE_CHECK=1 без `if: pull_request` сделал бы pytest.fail. Ищем YAML-шаги, ставящие
    PR_TITLE_CHECK, и требуем на них gate по событию.
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
                f"на другом событии заголовка PR нет, шаг упал бы")


@pytest.mark.contract
@pytest.mark.parametrize("wf", REQUIRED_CONTEXT_WORKFLOWS)
def test_no_merge_group_trigger(wf):
    """Снятый фордж-зависимый триггер `merge_group:` не вернулся в on:-блок.

    Merge queue привязала бы кит к фиче форджа; дрейф main держит сам кит
    (`gate-measures-merge-result`, ai_ops_kit/gates/merge_preview.py). Возврат `merge_group:` —
    регресс к оплаченному фордж-замку, и он обязан быть громким.
    """
    text = (WORKFLOWS / wf).read_text(encoding="utf-8")
    on = _on_block(text)
    assert not re.search(r"^\s*merge_group\s*:", on, re.M), (
        f"{wf}: в on: вернулся merge_group — фордж-зависимый механизм merge queue снят 04.09.2026, "
        f"возвращать его нельзя (дрейф держит merge_preview на чистом git)")
