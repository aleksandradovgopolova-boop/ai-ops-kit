#!/usr/bin/env python3
"""`ai-ops setup <dir>` — единая установка вместо ручной цепочки init→onboard→bootstrap→model.

ЧТО ДОКАЗЫВАЕТСЯ (поведение, а не код возврата):
  1. на чистом git-репо `setup .` РЕАЛЬНО готовит managed-зону, детектит стек
     (`.ai/repository-profile.yaml`) и пишет черновики bootstrap;
  2. финальный экран ЧЕСТНО называет «осталось от тебя» — плейсхолдеры `.ai-ops.yaml`
     (провайдеры/имя проекта) не выдаются за заполненный конфиг;
  3. на НЕ-git каталоге — объяснимый отказ про `git init`, rc 2 (без сырого трейсбека);
  4. повторный `setup` идемпотентен: на уже установленном ките не падает.

Общая инфраструктура — `_installer_helpers.py`; `setup` гоняется РЕАЛЬНЫМ подпроцессом
(`_run_cli`), как это делает пользователь: только так виден трейсбек, который in-process вызов
проглотил бы.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from _installer_helpers import _run_cli

pytestmark = pytest.mark.unit

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
    # Финальный коммит остаётся за человеком и назван.
    assert "коммит" in out.lower(), "не сказано, что коммит за человеком"


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
    remaining = installer._setup_remaining(child)
    joined = "\n".join(remaining)
    assert ".ai-ops.yaml" in joined, "остаток не называет конфиг с плейсхолдерами"
    assert any("коммит" in item.lower() for item in remaining), \
        "остаток не называет финальный коммит как шаг человека"
