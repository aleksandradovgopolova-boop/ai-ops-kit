"""Навык, который в дочке никто не правил, обновляется МОЛЧА (#1224).

НАЙДЕНО НА ИИ-СРЕДЕ (обновление 4.8.0 -> 4.9.0): кит напечатал «локальные правки сохранены» для
навыка `user-documentation`, хотя в его истории были только коммиты обновлений кита. Причина:
`sync_skills` сравнивал копию в дочке с НОВОЙ версией пакета, поэтому любой выпуск, менявший навык,
читался как чужая правка в каждой дочке, а в «резервную копию» уходил текст самого кита.

Теперь копия сверяется с тем, что кит ПОСТАВИЛ в прошлый раз (`.ai/runtime/skill-prints.json`):
  * нетронутая копия + изменённый пакет -> молча, без резервной копии;
  * настоящая правка -> резервная копия + предупреждение;
  * записи о поставке нет (старая установка) -> копия на всякий случай и честная формулировка.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
SID = "demo-skill"
PRINTS = ".ai/runtime/skill-prints.json"


def _installer(child: Path, pkg: Path):
    """Установщик с REPO_ROOT = child (модуль читает корень при импорте) и подменённым пакетом."""
    old = os.getcwd()
    os.chdir(child)
    try:
        spec = importlib.util.spec_from_file_location(
            f"ai_ops_skill_prints_{abs(hash(str(child)))}", KIT / "installer" / "ai_ops.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        os.chdir(old)
    mod.PKG = pkg
    return mod


def _release(pkg: Path, text: str) -> None:
    """Выпуск кита, в котором навык имеет текст `text`."""
    (pkg / "manifest").mkdir(parents=True, exist_ok=True)
    (pkg / "manifest" / "ai-ops-manifest.yaml").write_text(
        f"skills:\n  shipped:\n    - id: {SID}\n      path: skills/{SID}/SKILL.md\n",
        encoding="utf-8")
    (pkg / "skills" / SID).mkdir(parents=True, exist_ok=True)
    (pkg / "skills" / SID / "SKILL.md").write_text(text, encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    child, pkg = tmp_path / "child", tmp_path / "pkg"
    child.mkdir()
    _release(pkg, "версия 1 от кита\n")
    return child, pkg, _installer(child, pkg)


def _sync(inst, child):
    return inst._core().sync_skills(child)


def _skill(child: Path) -> Path:
    return child / ".claude" / "skills" / SID / "SKILL.md"


def _backup(child: Path) -> Path:
    return child / ".ai" / "runtime" / "backups" / "skills" / SID


def test_untouched_copy_is_updated_silently_when_package_changed(env, capsys):
    """Главный случай #1224: навык в дочке не трогали, выпуск его изменил — ни слова, ни копии."""
    child, pkg, inst = env
    _sync(inst, child)
    capsys.readouterr()
    _release(pkg, "версия 2 от кита: новый триггер\n")

    _sync(inst, child)

    out = capsys.readouterr().out
    assert _skill(child).read_text(encoding="utf-8") == "версия 2 от кита: новый триггер\n"
    assert SID not in out, f"ложное предупреждение о правке: {out!r}"
    assert not _backup(child).exists(), "в резервную копию ушёл текст самого кита"


def test_real_local_edit_is_backed_up_with_warning(env, capsys):
    """Настоящая правка в дочке по-прежнему сохраняется, и владелец это видит."""
    child, pkg, inst = env
    _sync(inst, child)
    _skill(child).write_text("версия 1 от кита\nмоя правка\n", encoding="utf-8")
    capsys.readouterr()
    _release(pkg, "версия 2 от кита\n")

    _sync(inst, child)

    out = capsys.readouterr().out
    assert (_backup(child) / "SKILL.md").read_text(encoding="utf-8") == "версия 1 от кита\nмоя правка\n"
    assert _skill(child).read_text(encoding="utf-8") == "версия 2 от кита\n"
    assert f"навык '{SID}': его правили в репозитории" in out
    assert ".ai/runtime/backups/skills/" + SID in out


def test_real_local_edit_is_backed_up_even_if_package_unchanged(env, capsys):
    """Правка сверяется с поставленным, а не с «изменился ли пакет»: при том же выпуске она тоже не теряется."""
    child, _pkg, inst = env
    _sync(inst, child)
    _skill(child).write_text("моя правка\n", encoding="utf-8")
    capsys.readouterr()

    _sync(inst, child)

    assert (_backup(child) / "SKILL.md").read_text(encoding="utf-8") == "моя правка\n"
    assert "его правили в репозитории" in capsys.readouterr().out


def test_without_recorded_print_copy_is_saved_with_honest_message(env, capsys):
    """Старая установка без записи о поставке: копия на всякий случай, но это не «ваши правки»."""
    child, pkg, inst = env
    _sync(inst, child)
    (child / PRINTS).unlink()                 # так выглядит всё, что установлено до записи
    capsys.readouterr()
    _release(pkg, "версия 2 от кита\n")

    _sync(inst, child)

    out = capsys.readouterr().out
    assert (_backup(child) / "SKILL.md").read_text(encoding="utf-8") == "версия 1 от кита\n"
    assert "не могу отличить вашу правку от прежней версии кита" in out
    assert "правки сохранены" not in out and "его правили" not in out


def test_without_recorded_print_identical_copy_is_not_backed_up(env, capsys):
    """Нет записи, но копия уже совпадает с новой версией — терять нечего, копировать нечего."""
    child, _pkg, inst = env
    _sync(inst, child)
    (child / PRINTS).unlink()
    capsys.readouterr()

    _sync(inst, child)

    assert not _backup(child).exists()
    assert SID not in capsys.readouterr().out


def test_print_is_recorded_and_updated_after_sync(env):
    """Запись о поставке появляется при первой доставке и меняется вместе с выпуском."""
    child, pkg, inst = env
    _sync(inst, child)
    first = json.loads((child / PRINTS).read_text(encoding="utf-8"))
    assert set(first) == {SID}

    _release(pkg, "версия 2 от кита\n")
    _sync(inst, child)
    second = json.loads((child / PRINTS).read_text(encoding="utf-8"))

    assert second[SID] != first[SID]
    ms = sys.modules["managed_state"]
    assert second[SID] == ms._signature_print(ms._dir_signature(pkg / "skills" / SID))


def test_repeat_sync_is_idempotent(env, capsys):
    """Повторный прогон ничего не меняет: ни навык, ни запись, ни резервных копий, ни слов."""
    child, _pkg, inst = env
    _sync(inst, child)
    before = (child / PRINTS).stat().st_mtime_ns, (child / PRINTS).read_bytes()
    capsys.readouterr()

    assert _sync(inst, child) == [SID]

    assert ((child / PRINTS).stat().st_mtime_ns, (child / PRINTS).read_bytes()) == before
    assert not _backup(child).exists()
    assert SID not in capsys.readouterr().out


def test_print_record_is_rolled_back_with_skills(env):
    """Запись входит в снимок обновления: откат навыков без неё сверял бы старый текст с новым отпечатком."""
    child, _pkg, inst = env
    paths = [p.relative_to(child).as_posix() for p in inst._core()._footprint_paths()]
    assert PRINTS in paths


# ── старые установки: записи нет, но прежний выпуск кита есть в его клоне под тегом ──────────────

def _tag_release(pkg: Path, version: str) -> None:
    """Сделать из подменённого пакета клон кита с тегом выпуска `v<version>`."""
    import subprocess
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-qm", version],
                 ["tag", f"v{version}"]):
        subprocess.run(["git", "-C", str(pkg), *args], check=True, capture_output=True)


def test_without_print_copy_equal_to_previous_release_is_silent(env, capsys):
    """Главный случай для УЖЕ подключённых дочек: записи нет, копия = прежний выпуск -> молча."""
    child, pkg, inst = env
    _tag_release(pkg, "1.0.0")
    _sync(inst, child)
    (child / PRINTS).unlink()                 # установка старше записи
    capsys.readouterr()
    _release(pkg, "версия 2 от кита\n")

    inst._core().sync_skills(child, previous_version="1.0.0")

    out = capsys.readouterr().out
    assert _skill(child).read_text(encoding="utf-8") == "версия 2 от кита\n"
    assert SID not in out, f"ложное сообщение: {out!r}"
    assert not _backup(child).exists()
    assert SID in json.loads((child / PRINTS).read_text(encoding="utf-8")), "запись не появилась"


def test_without_print_edit_against_previous_release_is_saved_honestly(env, capsys):
    """Копия разошлась с прежним выпуском, записи нет: копия сохраняется, правкой не называется."""
    child, pkg, inst = env
    _tag_release(pkg, "1.0.0")
    _sync(inst, child)
    (child / PRINTS).unlink()
    _skill(child).write_text("моя правка\n", encoding="utf-8")
    capsys.readouterr()
    _release(pkg, "версия 2 от кита\n")

    inst._core().sync_skills(child, previous_version="1.0.0")

    out = capsys.readouterr().out
    assert (_backup(child) / "SKILL.md").read_text(encoding="utf-8") == "моя правка\n"
    assert "не могу отличить вашу правку" in out


def test_without_print_unknown_previous_release_falls_back_to_honest_message(env, capsys):
    """Тега прежнего выпуска в клоне нет — сверять не с чем: копия и честная формулировка."""
    child, pkg, inst = env
    _tag_release(pkg, "1.0.0")
    _sync(inst, child)
    (child / PRINTS).unlink()
    capsys.readouterr()
    _release(pkg, "версия 2 от кита\n")

    inst._core().sync_skills(child, previous_version="0.9.0")

    assert _backup(child).exists()
    assert "не могу отличить вашу правку" in capsys.readouterr().out
