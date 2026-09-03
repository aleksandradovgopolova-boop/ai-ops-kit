#!/usr/bin/env python3
"""Тесты инсталлятора `installer/ai_ops.py` — версия, конфиг, планирование, .gitignore, опт-аут CI.

Разрез монолита tests/unit/test_installer.py; общая инфраструктура — в `_installer_helpers.py`.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

from _installer_helpers import (
    child, installed, installed_copy, _run_cli, _git,
    LEAKY_PATHS, KEPT_PATHS, _check_ignored, _record_path,
)

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


# ---------------------------------------------------------------- внутренние функции

@pytest.mark.parametrize("version,rng,expected", [
    ("2.14.1", ">=2.0.0 <3.0.0", True),
    ("2.14.1", ">=1.0.0 <2.0.0", False),
    ("9.9.9", "", True),
    ("3.0.0", ">=3.0.0", True),
])
def test_version_in_range(ai_ops, version, rng, expected):
    assert ai_ops.version_in_range(version, rng) is expected


def test_broken_child_config_raises_named_error(ai_ops, child, monkeypatch):
    """Битый конфиг даёт доменную ошибку с именем файла — её и ловит main()."""
    cfg = child / ".ai-ops.yaml"
    cfg.write_text("parent: [oops\n", encoding="utf-8")
    monkeypatch.setattr(ai_ops, "CHILD_CONFIG", cfg)
    with pytest.raises(ai_ops.ChildConfigError) as exc:
        ai_ops.installed_version()
    assert ".ai-ops.yaml" in str(exc.value)


def test_fresh_install_does_not_report_planning_as_ready(installed, ai_ops):
    """F-018 (живой прогон severnaya_traektoriya, 2026-08-12): doctor рапортовал «✓ артефакты на
    месте» СРАЗУ после установки — про черновики, которые сам же и положил.

    Кит собственным кодом знает разницу (`delivery_plan.is_template()` на этом же файле даёт True),
    но doctor спрашивал только `Path.exists()`. Владелец на свежей установке читал зелёное про
    пустой контур. Комментарий над проверкой обещал обратное: «пробел ВИДЕН, а не молчит».
    """
    req, gaps, unfilled = ai_ops._planning_gaps(installed)
    assert req, "контур планирования не объявлен в манифесте — тест потерял предмет"
    assert unfilled, "свежая установка объявлена заполненной: заготовки посчитаны за план"
    assert not gaps, f"заготовки посчитаны ПРОБЕЛОМ — это испортит первый экран: {gaps}"


def test_filled_planning_artifacts_are_not_reported_as_gap(installed, ai_ops):
    """Обратная сторона: заполненные артефакты пробелом не считаются.

    Без этой проверки F-018 можно было бы «закрыть», объявив контур пустым всегда.
    """
    (installed / "ROADMAP.md").write_text(
        "# ROADMAP\n\n## Сейчас\n\n- `real-goal` — настоящая цель\n\n"
        "## Следующий результат\n\n- `next-goal` — пользователь сможет…\n\n"
        "## Дальше\n\n- крупная возможность\n\n## Later\n\n- идея — не берём\n",
        encoding="utf-8")
    (installed / "planning").mkdir(exist_ok=True)
    (installed / "planning" / "plan.yaml").write_text(
        "schema_version: 1\nkind: delivery-plan\ngoals:\n  - id: real-goal\n    status: active\n"
        "work:\n  - id: w-01\n    title: Работа\n    type: engineering\n    goal: real-goal\n"
        "    status: todo\n    owner_role: engineer\n    write_scope: [src/]\n",
        encoding="utf-8")

    _req, gaps, unfilled = ai_ops._planning_gaps(installed)
    assert not gaps and not unfilled, f"заполненные артефакты объявлены незаполненными: {gaps} {unfilled}"


def test_init_hides_kit_service_state_from_child_git(installed):
    """side-effect proof: после install git САМ говорит, что служебное состояние скрыто."""
    assert (installed / ".gitignore").is_file(), "install не создал .gitignore в дочке"
    not_hidden = [f"{rel} ({why})" for rel, why in LEAKY_PATHS if not _check_ignored(installed, rel)]
    assert not not_hidden, (
        "служебное состояние кита уедет в коммит владельца по `git add -A`:\n  "
        + "\n  ".join(not_hidden))


def test_init_does_not_hide_product_artifacts(installed):
    """Обратная сторона, обязательная: правило не вправе спрятать продукт.

    Без неё F-021 «закрывался» бы строкой `.ai/` — и вместе с мусором из истории исчезли бы
    managed-слой, ответы владельца и история эффекта.
    """
    hidden = [f"{rel} ({why})" for rel, why in KEPT_PATHS if _check_ignored(installed, rel)]
    assert not hidden, "правило спрятало от git продуктовые артефакты:\n  " + "\n  ".join(hidden)


def test_existing_gitignore_is_appended_not_overwritten(child, ai_ops):
    """`.gitignore` — документ владельца: его правила обязаны выжить, а блок не должен дублироваться."""
    gi = child / ".gitignore"
    gi.write_text("# правила владельца\nnode_modules/\n*.log\n", encoding="utf-8")

    assert ai_ops.ensure_gitignore(child) == "appended"
    text = gi.read_text(encoding="utf-8")
    assert "# правила владельца" in text and "node_modules/" in text, "правила владельца утрачены"
    assert ".ai/worktrees/" in text, "блок кита не дописан"

    assert ai_ops.ensure_gitignore(child) == "present", "повторный вызов не распознал свой блок"
    assert gi.read_text(encoding="utf-8") == text, "повторный вызов изменил файл"
    assert text.count(".ai/worktrees/") == 1, "блок кита продублирован"


def test_gitignore_is_created_when_child_has_none(child, ai_ops):
    assert not (child / ".gitignore").exists()
    assert ai_ops.ensure_gitignore(child) == "created"
    assert ".ai/runtime/active-work.yaml" in (child / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_change_is_named_in_the_report(child, ai_ops):
    """Дописка в чужой файл обязана быть НАЗВАНА: иначе владелец узнаёт о ней из диффа."""
    line = ai_ops._assets_report_line({"gitignore": "appended"})
    assert ".gitignore" in line and "дополнен" in line, line
    assert "не затронуты" in line, "отчёт не говорит, что продуктовые артефакты не тронуты"
    assert ai_ops._assets_report_line({"gitignore": "present"}).strip() == "", (
        "нечего сообщать, а отчёт говорит — это шум, из-за которого перестают читать отчёты")


def test_deleted_workflow_is_opted_out_not_absent(installed_copy, ai_ops):
    """Состояние различает решение владельца и «ещё не ставили»."""
    _record_path(installed_copy).unlink()
    state = {r["file"]: r["state"] for r in ai_ops.ci_workflow_state(installed_copy)}
    assert state["ai-ops-record.yml"] == "opted-out", state
    # обратная сторона: файл, которого кит НИКОГДА не ставил, остаётся absent
    prints = ai_ops._ci_prints(installed_copy)
    prints.pop("ai-ops-record.yml", None)
    ai_ops._ci_prints_path(installed_copy).write_text(
        __import__("json").dumps(prints, ensure_ascii=False), encoding="utf-8")
    state2 = {r["file"]: r["state"] for r in ai_ops.ci_workflow_state(installed_copy)}
    assert state2["ai-ops-record.yml"] == "absent", (
        "без отпечатка отсутствие обязано читаться как «не установлен» — иначе первая установка "
        "перестанет ставить шаблоны вовсе")


def test_opt_out_survives_sync_and_is_named(installed_copy, ai_ops):
    """Доставка не возвращает удалённое и ГОВОРИТ об этом, а не молчит."""
    _record_path(installed_copy).unlink()
    acts = ai_ops.sync_ci_workflows(installed_copy)
    assert not _record_path(installed_copy).exists(), "удалённый владельцем workflow вернулся"
    kept = [a for a in acts if a["file"] == "ai-ops-record.yml"]
    assert kept and kept[0]["action"] == "kept-opted-out", acts


def test_opt_out_survives_refresh_ci(installed_copy, ai_ops):
    """`--refresh-ci` означает «перезапиши мои правки», а НЕ «верни удалённое».

    Иначе флаг об обновлении толковал бы согласие шире выданного.
    """
    _record_path(installed_copy).unlink()
    ai_ops.sync_ci_workflows(installed_copy, refresh=True)
    assert not _record_path(installed_copy).exists(), "--refresh-ci отменил решение владельца"


def test_first_install_still_delivers_the_workflow(child, ai_ops):
    """positive, обязательный: на репозитории без кита шаблон по-прежнему ставится."""
    r = _run_cli(child, "init", ".")
    assert r.returncode == 0, r.stdout[-400:]
    assert _record_path(child).exists(), "первая установка перестала ставить рекордер"


# ------------------------------------------- 12. установка не выглядит началом работы

def test_fresh_install_is_not_a_code_change(installed):
    """Свежая установка НЕ читается как «код уже правится» (проба шва 2026-08-17).

    Потолок траты на описание применяется только пока код не тронут, а «тронут» выводится из
    `git status`. Пока список путей кита состоял из трёх каталогов, свежеустановленная дочка давала
    `code_changed=True` — и потолок не срабатывал НИКОГДА. Ни один тест этого не видел: все они
    мерили репозиторий кита, где своей же поставки в `git status` нет. Поймалось установкой в пустую
    дочку, и проверка живёт ЗДЕСЬ — рядом с установкой, а не рядом с механизмом.
    """
    from ai_ops_kit.engops import process_spend
    assert process_spend.code_changed(installed) is False, \
        "поставка кита принята за правку кода: " + subprocess.run(
            ["git", "-C", str(installed), "status", "--porcelain"],
            capture_output=True, text=True, check=False).stdout

    (installed / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n", encoding="utf-8")
    try:
        assert process_spend.code_changed(installed) is True, \
            "правка кода продукта в той же дочке не замечена — исключения съели всё"
    finally:
        _git(installed, "checkout", "--", "src/calc.py")
