"""Обновление убирает своё старьё — даже когда миграция перенесла его в другой каталог.

НАЙДЕНО ПРИ ПЕРЕДАЧЕ ОБНОВЛЕНИЯ В ИИ-СРЕДУ. Диff показал −8152 строки: удалялись 47 валидаторов
кита, приехавших к ребёнку с 3.7.3, когда в поставку шло всё. Уйти они должны были ещё при обновлении
до 3.36.4, но уцелели, и вычистило их только СЛЕДУЮЩЕЕ обновление.

Причина — порядок в `cmd_update`:

    build_diff()            # посчитал: удалить `validation/x.py`
    миграция 3.33->3.34     # перенесла `validation/` -> `ai_ops_kit/validation/`
    удаление по списку      # путь `validation/x.py` уже не существует -> no-op

Копия по новому пути оставалась навсегда и вдобавок попадала под контроль целостности как managed:
ребёнок носил мёртвый груз, который кит считал своим.

Три обязательных теста на capability:
  * positive     — перенесённый миграцией лишний файл удаляется В ТОМ ЖЕ обновлении;
  * fail-closed  — файл, который ДОЛЖЕН быть в managed, не удаляется;
  * side-effect  — отчёт называет то, что реально применено (диф пересчитан после миграций).

F-022: вызовы здесь идут с `in_place=True` — предмет этих тестов механика обновления
(перенос устаревших файлов миграцией и состав отчёта), а не политика доставки. Без флага
они уходили бы в отложенный режим и проверяли не то, что обещают в имени.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

# Валидатор кита, которого НЕТ в белом списке поставки: именно такие и остались у ии-среды.
STALE = "validate_decisions.py"


def _load(root: Path):
    """Загрузить installer с REPO_ROOT = root (модуль читает корень при импорте)."""
    import os
    old = os.getcwd()
    os.chdir(root)
    try:
        spec = importlib.util.spec_from_file_location(
            f"inst_mig_{abs(hash(str(root)))}", INSTALLER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(old)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Настоящая установка: только так виден порядок шагов обновления."""
    root = tmp_path_factory.mktemp("mig") / "child"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"init упал: {r.stdout}\n{r.stderr}"
    return root


@pytest.mark.unit
def test_stale_file_moved_by_migration_is_removed_in_the_same_update(child, tmp_path):
    """Файл лежит по СТАРОМУ пути; миграция переносит его на новый; обновление обязано убрать его.

    Проверяем не рассуждение о порядке, а факт: после одного `update` файла нет ни по старому пути,
    ни по новому.
    """
    import shutil
    root = tmp_path / "work"
    shutil.copytree(child, root)

    old_dir = root / ".ai" / "managed" / "validation"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / STALE).write_text("# валидатор кита, ребёнку не нужен\n", encoding="utf-8")
    new_path = root / ".ai" / "managed" / "ai_ops_kit" / "validation" / STALE

    inst = _load(root)
    rc = inst.cmd_update(force=True, in_place=True)

    assert rc == 0, "обновление не прошло"
    assert not (old_dir / STALE).exists(), "файл остался по старому пути"
    assert not new_path.exists(), (
        "миграция перенесла лишний файл, и уборка его не увидела — мёртвый груз остался у ребёнка")


@pytest.mark.unit
def test_files_that_belong_to_managed_survive(child, tmp_path):
    """Обратная сторона: уборка не должна выносить то, что киту принадлежит."""
    import shutil
    root = tmp_path / "keep"
    shutil.copytree(child, root)
    must_stay = root / ".ai" / "managed" / "VERSION"
    assert must_stay.is_file(), "предпосылка: VERSION в managed есть"

    inst = _load(root)
    inst.cmd_update(force=True, in_place=True)

    assert must_stay.is_file(), "уборка вынесла файл, который обязан быть в managed"
    assert (root / ".ai" / "managed" / "ai_ops_kit" / "validation" / "_bootstrap.py").is_file(), \
        "загрузчик путей валидаторов удалён — уехавшие валидаторы умрут на первой строке"


@pytest.mark.unit
def test_diff_is_recomputed_after_the_migration_chain():
    """Порядок закреплён разбором: иначе следующая миграция с переносом повторит это молча.

    Дефект не в одной строке, а в ПОСЛЕДОВАТЕЛЬНОСТИ, и именно её надо держать.
    """
    tree = ast.parse(INSTALLER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_update")
    diffs = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "build_diff"]
    chain = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(getattr(n.func, "attr", None), "__class__", None) is not None
             and getattr(n.func, "attr", "") == "run"]
    assert len(diffs) >= 2, ("диф считается один раз — значит он либо до миграций (и удаление идёт "
                             "по устаревшим путям), либо решение о раннем выходе принимается после "
                             "лишней работы")
    assert chain, "не нашлось запуска цепочки миграций"
    assert max(diffs) > min(chain), ("диф не пересчитывается после миграций — перенесённый файл "
                                    "снова уцелеет")


@pytest.mark.unit
def test_report_names_what_was_actually_applied(child, tmp_path):
    """Отчёт обязан называть применённое, а не запланированное до миграций."""
    import json
    import shutil
    root = tmp_path / "report"
    shutil.copytree(child, root)
    old_dir = root / ".ai" / "managed" / "validation"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / STALE).write_text("# лишний\n", encoding="utf-8")

    inst = _load(root)
    inst.cmd_update(force=True, in_place=True)

    rep = json.loads((root / ".ai" / "runtime" / "last-update-report.json").read_text("utf-8"))
    removed = [c["path"] for c in (rep.get("managed_changes") or [])
               if c.get("action") == "remove"]
    assert any(STALE in p for p in removed), (
        f"удаление лишнего файла не названо в отчёте: {removed[:5]}")
    assert all(not (root / p).exists() for p in removed), \
        "отчёт называет удалённым то, что осталось на диске"
