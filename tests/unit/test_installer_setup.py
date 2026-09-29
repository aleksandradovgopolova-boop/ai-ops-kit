#!/usr/bin/env python3
"""`ai-ops setup <dir>` — единая установка вместо ручной цепочки init→doctor→onboard→bootstrap→
model --flow.

ЧТО ДОКАЗЫВАЕТСЯ (поведение, а не код возврата):
  1. на чистом git-репо `setup .` РЕАЛЬНО готовит managed-зону, детектит стек
     (`.ai/repository-profile.yaml`) и пишет черновики bootstrap;
  2. финальный экран ЧЕСТНО называет «осталось от тебя» — плейсхолдеры `.ai-ops.yaml`
     (провайдеры/имя проекта) не выдаются за заполненный конфиг;
  3. на НЕ-git каталоге — объяснимый отказ про `git init`, rc 2 (без сырого трейсбека);
  4. повторный `setup` идемпотентен: на уже установленном ките не падает;
  5. `setup` доводит до первого часа: проверяет целостность (doctor) и показывает первый час
     (`model --flow`), а не обрывается на форме вопросов (issue #612).

Общая инфраструктура — `_installer_helpers.py`; `setup` гоняется РЕАЛЬНЫМ подпроцессом
(`_run_cli`), как это делает пользователь: только так виден трейсбек, который in-process вызов
проглотил бы.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from _installer_helpers import _git, _run_cli

# Каждый тест поднимает реальную установку кита (подпроцессы + копирование дерева) — 20–40 c на
# CI, то есть slow по определению маркера (pytest.ini). Снят с шарда `fast` под `--dist loadfile`
# в slow-шарды selftests, где есть запас; на КАЖДОМ PR по-прежнему выполняется. Issue #465.
pytestmark = [pytest.mark.unit, pytest.mark.slow]

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_setup_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_setup_prepares_managed_zone_detects_stack_and_bootstraps(child):
    """(1) Одна команда проходит цепочку: managed-зона + профиль стека + черновики bootstrap."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"setup упал: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    # managed-зона на месте — установка состоялась
    assert (child / ".ai" / "managed").is_dir(), "managed-зона не создана"
    # onboard отработал ПОДПРОЦЕССОМ из managed — профиль стека записан
    assert (child / ".ai" / "repository-profile.yaml").is_file(), \
        "onboard не отработал: нет .ai/repository-profile.yaml"
    # bootstrap с --apply написал черновики направления/плана (артефакты контура планирования)
    prof_gaps = _run_cli(child, "doctor")
    assert "планирование" in prof_gaps.stdout, "doctor не видит контур планирования после setup"


def test_setup_names_what_is_left_to_the_human(child):
    """(2) Финал перечисляет «осталось от тебя» — незаполненный конфиг НЕ выдан за готовый."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    out = r.stdout
    assert "Осталось от тебя" in out, "нет раздела «осталось от тебя» — остаток спрятан"
    # Плейсхолдеры .ai-ops.yaml (провайдеры/имя проекта) названы конкретно, а не общими словами.
    assert ".ai-ops.yaml" in out and (
        "провайдер" in out.lower() or "заготовк" in out.lower()), \
        "остаток конфига не назван — незаполненный .ai-ops.yaml выдан за готовый"
    # Коммит служебных файлов теперь делает САМ setup — он не должен оставаться «за человеком».
    assert "это делает человек" not in out, \
        "коммит всё ещё свален на человека, хотя setup фиксирует свои файлы сам"


def test_setup_reaches_first_hour_via_doctor_and_flow(child):
    """(5) `setup` доводит до первого часа: называет шаг проверки целостности (doctor) и шаг первого
    часа (model --flow), а не останавливается на подготовке формы вопросов (issue #612)."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"setup упал: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    out = r.stdout
    assert "doctor" in out.lower(), "setup не проверяет целостность установки (нет шага doctor)"
    assert "первый час" in out.lower() and "model --flow" in out.lower(), \
        "setup не доводит до первого часа (нет шага model --flow)"
    # Первый час должен оставить форму ответов: `--flow` — надмножество обычного `model`, иначе
    # остаток «ответь на вопросы» не на что опереть. Минимальный репо даёт продуктовые вопросы.
    assert (child / ".ai" / "project" / "onboarding-answers.yaml").is_file(), \
        "первый час не оставил форму ответов — где человеку отвечать?"


def test_setup_on_non_git_dir_refuses_with_git_init_hint(tmp_path):
    """(3) Не-git каталог — честный отказ про `git init`, rc 2, без сырого трейсбека."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "file.txt").write_text("x\n", encoding="utf-8")
    r = _run_cli(plain, "setup", ".")
    assert r.returncode == 2, f"ожидался rc 2 на не-git, получен {r.returncode}\n{r.stdout}"
    assert "git init" in r.stdout, "отказ не подсказывает `git init`"
    assert "Traceback" not in r.stdout and "Traceback" not in r.stderr, \
        "не-git должен отказывать объяснимо, а не трейсбеком"
    # managed-зону в не-git каталоге не создаём
    assert not (plain / ".ai" / "managed").exists(), "в не-git каталоге не должно быть установки"


def test_setup_is_idempotent_on_already_installed(child):
    """(4) Повторный `setup` на уже установленном ките не падает (можно перезапускать)."""
    first = _run_cli(child, "setup", ".")
    assert first.returncode == 0, f"первый setup упал: {first.stdout}\n{first.stderr}"
    second = _run_cli(child, "setup", ".")
    assert second.returncode == 0, f"повторный setup упал: {second.stdout}\n{second.stderr}"
    # Идемпотентность названа человеку, а не молча проглочена.
    assert "уже была" in second.stdout or "перезапус" in second.stdout.lower(), \
        "повторный запуск не отмечен как идемпотентный"
    assert (child / ".ai" / "managed").is_dir()


def test_remaining_names_config_placeholders_in_process(child):
    """`_setup_remaining` называет незаполненный конфиг остатком — на свежей установке (in-process).

    Прямой вызов функции установщика: остаток «от человека» вычисляется из валидатора конфига, а
    не из общих слов, и заготовки `.ai-ops.yaml` НЕ выдаются за заполненный конфиг.
    """
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    installer = _load_installer()
    remaining = installer._setup_ops()._setup_remaining(child)
    joined = "\n".join(remaining)
    assert ".ai-ops.yaml" in joined, "остаток не называет конфиг с плейсхолдерами"
    # Коммит служебных файлов setup делает сам — его больше НЕТ в остатке «за человеком».
    assert not any("коммит" in item.lower() for item in remaining), \
        "коммит остался в остатке, хотя его теперь делает setup"


def test_remaining_depends_on_first_hour_stage_in_process(child):
    """`_setup_remaining` спрашивает ответы ПО СТАДИИ первого часа, а не по наличию формы.

    ready — вопросов не остаётся; needs_answers — просит ответить и перечисляет блокирующие;
    blocked_understanding — честно говорит, что репозиторий пока не читается."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    setup_ops = _load_installer()._setup_ops()

    ready = {"kind": "first-hour", "stage": "ready",
             "next": {"next_best": {"id": "W1", "title": "нарезать монолит"}}}
    r_ready = setup_ops._setup_remaining(child, ready)
    assert not any("продуктовые вопросы" in x for x in r_ready), \
        "при stage=ready кит всё ещё просит ответить на вопросы — фактов же хватило"

    needs = {"kind": "first-hour", "stage": "needs_answers",
             "blocking_questions": [{"id": "primary_user", "ask": "кто главный пользователь?"}]}
    r_needs = setup_ops._setup_remaining(child, needs)
    assert any("продуктовые вопросы" in x for x in r_needs), "needs_answers не просит ответить"
    assert any("primary_user" in x for x in r_needs), "не перечислен блокирующий вопрос по id"

    blocked = {"kind": "first-hour", "stage": "blocked_understanding"}
    r_blocked = setup_ops._setup_remaining(child, blocked)
    assert any("не читается" in x for x in r_blocked), \
        "blocked_understanding не сказал честно, что репозиторий пока не читается"


def test_first_hour_done_lines_names_first_work_at_ready():
    """При stage=ready блок «сделано» называет первую работу человеческим языком."""
    setup_ops = _load_installer()._setup_ops()
    ready = {"kind": "first-hour", "stage": "ready",
             "next": {"next_best": {"id": "W1", "title": "нарезать монолит installer"}}}
    lines = setup_ops._first_hour_done_lines(ready)
    joined = "\n".join(lines)
    assert "направление и план собраны" in joined, "не сказано, что первый час пройден"
    assert "нарезать монолит installer" in joined, "не названа первая работа"
    assert any("Дальше имеет смысл взять" in x for x in lines), "первая работа названа не по-человечески"
    # needs_answers первую работу НЕ называет (её ещё нет).
    needs = {"kind": "first-hour", "stage": "needs_answers", "blocking_questions": []}
    assert not any("Дальше имеет смысл взять" in x for x in setup_ops._first_hour_done_lines(needs))


def test_first_result_lead_leads_with_result_per_stage(tmp_path):
    """`_first_result_lead` ВЕДЁТ первым результатом, а не строкой «установлено» (issue #1140).

    Прямой вызов: ready называет первую работу; needs_answers зовёт ответить без правки YAML;
    blocked честно говорит, что результата пока нет; неразобранный первый час не выдаёт
    «установлено» за результат. Строку про файл показывает, только если файл реально есть."""
    setup_ops = _load_installer()._setup_ops()

    ready = {"kind": "first-hour", "stage": "ready",
             "next": {"next_best": {"id": "W1", "title": "нарезать монолит"}}}
    lead_ready = "\n".join(setup_ops._first_result_lead(tmp_path, ready))
    assert "Первый результат" in lead_ready
    assert "нарезать монолит" in lead_ready
    # Результат назван ПРОТИВОПОСТАВЛЕНИЕМ «установлено», а не выдан за него.
    assert "не «кит установлен»" in lead_ready
    assert "AI Ops установлен одной командой" not in lead_ready
    # Файла ещё нет — ссылку на него не показываем (не обещаем несуществующее).
    assert "first-result.md" not in lead_ready

    # Создаём файл результата — тогда ссылка на него появляется.
    (tmp_path / ".ai" / "generated").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai" / "generated" / "first-result.md").write_text("x\n", encoding="utf-8")
    lead_with_file = "\n".join(setup_ops._first_result_lead(tmp_path, ready))
    assert ".ai/generated/first-result.md" in lead_with_file

    needs = {"kind": "first-hour", "stage": "needs_answers", "blocking_questions": []}
    lead_needs = "\n".join(setup_ops._first_result_lead(tmp_path, needs))
    assert "Первый результат" in lead_needs
    assert "--answer" in lead_needs and "YAML" in lead_needs

    blocked = {"kind": "first-hour", "stage": "blocked_understanding"}
    lead_blocked = "\n".join(setup_ops._first_result_lead(tmp_path, blocked))
    assert "первого результата пока нет" in lead_blocked.lower()

    # Первый час не разобрался (None / старый managed) — «установлено» за результат не выдаём.
    lead_none = "\n".join(setup_ops._first_result_lead(tmp_path, None))
    assert "вручную" in lead_none and "model --flow --apply" in lead_none


def test_first_result_lead_names_project_state_right_under_the_header(tmp_path):
    """(#1200) Итог «в каком состоянии проект» стоит сразу под заголовком экрана; нет итога — нет строки."""
    setup_ops = _load_installer()._setup_ops()
    ready = {"kind": "first-hour", "stage": "ready",
             "health": {"verdict": "По коду и безопасности проект в порядке — срочно править нечего."}}
    lead = setup_ops._first_result_lead(tmp_path, ready)
    assert lead[1] == "Состояние проекта: По коду и безопасности проект в порядке — срочно править нечего."
    assert not any("Состояние проекта" in x
                   for x in setup_ops._first_result_lead(tmp_path, {"kind": "first-hour", "stage": "ready"}))


def test_setup_leaves_first_result_artifact_and_leads_with_it(child):
    """(issue #1140) Конец установки — первый РЕЗУЛЬТАТ: setup оставляет открываемый файл
    `.ai/generated/first-result.md` и ведёт им экран, а не строкой «AI Ops установлен»."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"setup упал: {r.stdout}\n{r.stderr}"
    out = r.stdout
    # Файл первого результата создан и его можно открыть.
    artifact = child / ".ai" / "generated" / "first-result.md"
    assert artifact.is_file(), "setup не оставил файл первого результата .ai/generated/first-result.md"
    assert "Первый результат" in artifact.read_text(encoding="utf-8")
    # Экран ВЕДЁТ первым результатом и ссылается на файл — а не старой строкой «установлен одной…».
    assert "Первый результат" in out, "финальный экран не ведёт первым результатом"
    assert ".ai/generated/first-result.md" in out, "экран не показывает, где лежит первый результат"
    assert "AI Ops установлен одной командой" not in out, \
        "экран всё ещё ведёт строкой «установлено», а не результатом"


def test_setup_names_blocking_questions_at_needs_answers(child):
    """(needs_answers, подпроцесс) минимальный репозиторий даёт вопросы: экран просит ответить и
    перечисляет блокирующие с их id — человек видит, чего именно не хватает."""
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"setup упал: {r.stdout}\n{r.stderr}"
    out = r.stdout
    assert "продуктовые вопросы" in out, "не попросил ответить на продуктовые вопросы"
    # Блокирующие вопросы перечислены с id в [скобках] под пунктом остатка.
    import re as _re
    assert _re.search(r"—\s*\[[a-z_]+\]", out), \
        f"блокирующие вопросы не перечислены с id:\n{out[-800:]}"


def test_setup_commits_only_kit_files_not_foreign(child):
    """(C) setup фиксирует ТОЛЬКО пути кита; посторонний файл рабочего дерева остаётся не тронут.

    Кладём посторонний файл ДО установки и проверяем, что после setup он остался незакоммиченным
    (untracked), а служебные файлы кита (`.ai-ops.yaml`) — закоммичены."""
    foreign = child / "MY-OWN-NOTES.txt"
    foreign.write_text("личные заметки пользователя\n", encoding="utf-8")
    r = _run_cli(child, "setup", ".")
    assert r.returncode == 0, f"setup упал: {r.stdout}\n{r.stderr}"
    # Экран называет фиксацию как СДЕЛАННОЕ.
    assert "закоммичены" in r.stdout, f"не сказано, что setup зафиксировал свои файлы:\n{r.stdout[-600:]}"
    # Служебные файлы кита — под контролем git (закоммичены).
    tracked = _git(child, "ls-files").stdout.splitlines()
    assert ".ai-ops.yaml" in tracked, "setup не зафиксировал .ai-ops.yaml"
    assert any(t.startswith(".ai/") for t in tracked), "setup не зафиксировал .ai/"
    # Посторонний файл НЕ закоммичен: git его не отслеживает.
    assert "MY-OWN-NOTES.txt" not in tracked, \
        "setup закоммитил посторонний файл пользователя — граница фиксации нарушена"
    status = _git(child, "status", "--porcelain", "MY-OWN-NOTES.txt").stdout
    assert status.strip().startswith("??"), \
        f"посторонний файл должен остаться нетронутым (untracked), а статус: {status!r}"
