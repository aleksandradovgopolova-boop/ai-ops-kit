"""Заголовок PR — это тема будущего коммита на main.

ЗАМЕР 20.08.2026. PR #211 влит squash'ем, и его человекочитаемый заголовок «Ночной обзор v0:
дельта от подтверждённого обзора и находки вместо количеств (#211)» стал ТЕМОЙ КОММИТА на main.
`cz check` в ветке смотрел коммиты ВЕТКИ — там всё было по формату — и о заголовке не знал ничего.

Итог: main покраснел на lint, и КАЖДАЯ ветка от него унаследовала красный. Это тот самый «красный
фон»: контур перестаёт что-либо значить, потому что красный есть всегда и уже не про твою работу.
Переписать историю защищённой ветки нельзя, значит правило существовало и не исполнялось там, где
решалось.

ПОЧЕМУ ПРОБОЙ, А НЕ СТРОКОЙ В WORKFLOW. Первая редакция этой правки была инлайновым python-скриптом
в pr-smoke.yml — и собственный контур поймал её на инварианте «проверка идёт через pytest»
(`validate_agents_checklist.offending_commands`). Инвариант прав: проверка, живущая только в
workflow, не запускается локально и не покрыта ничем.
"""
from __future__ import annotations

import os
import re

import pytest

# Тот же набор типов, что у commitizen (`cz_conventional_commits`). Держим рядом с пробой, а не в
# workflow: правило, размазанное по двум местам, разъезжается молча.
CONVENTIONAL = re.compile(
    r"^(build|bump|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([^)]+\))?!?: .+")


@pytest.mark.contract
def test_the_pr_title_becomes_a_conventional_commit_subject():
    title = os.environ.get("PR_TITLE")
    if not title:
        # ТРЕТЬЕ СОСТОЯНИЕ, А НЕ УСПЕХ: вне шага-ворот проверять нечего.
        #
        # ПРИЗНАК — СВОЙ ФЛАГ ШАГА, А НЕ `GITHUB_EVENT_NAME`. Замер 20.08.2026: первая редакция
        # краснела при `GITHUB_EVENT_NAME == pull_request`, а он выставлен в КАЖДОЙ джобе сборки
        # по PR — то есть проба падала везде, где её никто не звал воротами. Ложный красный на
        # семи джобах вместо сигнала на одной: признак «меня должны были позвать» обязан ставить
        # тот, кто зовёт, а не окружение вообще.
        if os.environ.get("PR_TITLE_CHECK") == "1":
            pytest.fail("шаг ворот запущен, а PR_TITLE ему не передан: "
                        "проверка объявлена и не исполняется")
        pytest.skip("PR_TITLE не задан — запуск вне шага ворот, проверять нечего")

    assert CONVENTIONAL.match(title), (
        f"Заголовок PR не по формату Conventional Commits:\n  {title}\n\n"
        "При squash-мерже он СТАНЕТ темой коммита на main, и основная ветка покраснеет на lint — "
        "а переписать защищённую историю нельзя. Исправьте заголовок PR, например:\n"
        "  fix(validation): пути манифеста проверяются там, где они существуют")


@pytest.mark.contract
@pytest.mark.parametrize("title", [
    "Ночной обзор v0: дельта от подтверждённого обзора и находки вместо количеств",
    "Четыре работы закрыты по замеру; полевой прогон начат",
    "Update README",
])
def test_real_titles_that_slipped_through_are_caught(title):
    """Три настоящих заголовка сегодняшнего дня. Первый и есть тот, что покрасил main."""
    assert not CONVENTIONAL.match(title), title


@pytest.mark.contract
@pytest.mark.parametrize("title", [
    "fix(validation): пути манифеста проверяются там, где они существуют",
    "chore(plan): четыре работы закрыты по замеру",
    "feat!: ломающее изменение",
    "docs: почему канал зарабатывается",
])
def test_correct_titles_pass(title):
    """Обратная сторона: ворота, отвергающие правильное, обходят, а не исправляют."""
    assert CONVENTIONAL.match(title), title


@pytest.mark.contract
def test_a_pr_build_without_the_gate_step_is_not_red(monkeypatch):
    """ЗАМЕР 20.08.2026: первая редакция краснела в КАЖДОЙ джобе PR-сборки.

    Признаком «меня должны были позвать» стоял `GITHUB_EVENT_NAME == pull_request`, а он выставлен
    во всех джобах сборки по PR. Проба падала там, где её никто не звал воротами: ложный красный на
    семи джобах вместо сигнала на одной. Признак обязан ставить ТОТ, КТО ЗОВЁТ, — иначе проверка
    отвечает не на свой вопрос.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.delenv("PR_TITLE", raising=False)
    monkeypatch.delenv("PR_TITLE_CHECK", raising=False)
    with pytest.raises(Exception) as e:            # skip — это исключение pytest, не провал
        test_the_pr_title_becomes_a_conventional_commit_subject()
    assert "Skipped" in type(e.value).__name__, f"чужая джоба покраснела: {e.value}"
