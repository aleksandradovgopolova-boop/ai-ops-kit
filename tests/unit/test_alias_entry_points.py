"""Плоское имя остаётся ЗАПУСКАЕМОЙ точкой входа, а не только импортируемой (v3.31.1).

`tools/<module>.py` — алиас на модуль пакета. Пока алиас делал `sys.modules[__name__] = _target`,
запуск скриптом подменял собой `__main__`: блок `if __name__ == "__main__"` внутри цели не
срабатывал никогда (у неё `__name__` — имя модуля в пакете), скрипт не делал ничего и возвращал 0.
Так сломались ВСЕ 94 точки входа сразу — включая те, что вызывает установленный `/ai-start-task`
в child-репозитории.

Ключевой урок в критерии проверки. Переезд проверяли запуском и записали «прямой запуск rc=0» как
доказательство — но ноль и есть симптом: скрипт, который ничего не делает, завершается успешно.
Поэтому здесь мерило — РАБОТА (непустой вывод), а не код возврата.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждый алиас, чья цель имеет main-guard, на `--help` печатает непустой вывод;
  * fail-closed  — синтетический алиас в СТАРОМ стиле ловится этой же пробой как молчаливый no-op
                   (иначе проба подтверждала бы сама себя);
  * side-effect  — импорт по имени по-прежнему даёт ОДИН объект модуля (инвариант v3.30 не сломан).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
TOOLS = PKG / "tools"


def _aliases_with_main():
    """[(имя алиаса, целевой модуль)] — только те, чья цель объявляет main-guard."""
    out = []
    for f in sorted(TOOLS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "sys.modules[__name__]" not in src:
            continue
        target = next((ln.split()[1] for ln in src.splitlines()
                       if ln.strip().startswith("import ai_ops_kit.")), None)
        if not target:
            continue
        tf = PKG / (target.replace(".", "/") + ".py")
        if tf.is_file() and "__main__" in tf.read_text(encoding="utf-8"):
            out.append((f.name, target))
    return out


def _clean_env():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)          # окружение пользователя, а не CI
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _probe(script: Path, cwd: Path):
    """Запустить как скрипт и вернуть объём проделанной работы в байтах вывода.

    Именно вывод, а не returncode: молчаливый no-op возвращает 0 и выглядит успехом.
    """
    r = subprocess.run([sys.executable, str(script), "--help"], cwd=str(cwd), env=_clean_env(),
                       capture_output=True, text=True, timeout=120)
    return len((r.stdout + r.stderr).strip())


@pytest.mark.slow
def test_every_alias_actually_runs(tmp_path):
    """positive: точка входа делает работу, а не молча возвращает 0."""
    pairs = _aliases_with_main()
    assert pairs, "алиасов с main-guard не найдено — тест потерял предмет"

    silent = [name for name, _ in pairs if _probe(TOOLS / name, tmp_path) == 0]
    assert not silent, (
        f"{len(silent)} из {len(pairs)} точек входа не делают ничего и возвращают 0: {silent[:10]}")


@pytest.mark.slow
def test_old_style_alias_is_caught(tmp_path):
    """fail-closed: проба обязана ловить подмену __main__, иначе она бесполезна."""
    stub = tmp_path / "run_plan_oldstyle.py"
    stub.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(TOOLS)!r})\n"
        "import _bootstrap  # noqa: F401\n"
        "import ai_ops_kit.engine.run_plan as _target\n"
        "sys.modules[__name__] = _target\n",          # ровно то, что было до v3.31.1
        encoding="utf-8")

    assert _probe(stub, tmp_path) == 0, (
        "алиас старого стиля выдал вывод — проба измеряет не то, и молчаливый no-op пройдёт мимо")


def test_flat_name_and_package_name_are_one_object():
    """side-effect: правка запуска не сломала инвариант единственного объекта модуля."""
    sys.path.insert(0, str(TOOLS))
    import ai_ops_kit.engine.run_plan as pkg_mod      # noqa: E402
    import run_plan as flat_mod                       # noqa: E402

    assert flat_mod is pkg_mod, "плоское имя и пакетное дали РАЗНЫЕ объекты — состояние разъедется"
