"""Пробы доходят до дефекта даже там, где кит установлен editable (19.08.2026).

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ. На машине разработки пять проверок красные ВСЕГДА при зелёном CI — и
три из пяти по одной причине: `PYTHONPATH` они чистили, а editable-установка ставит meta-path
finder через `.pth` в site-packages, и он отдаёт `ai_ops_kit` ЛЮБОМУ процессу этого интерпретатора.
Проба копировала репозиторий, ломала копию, запускала её — и читала рабочий клон. «Порчу не
заметили» означало не дефект продукта, а то, что портили не то дерево.

ЦЕНА БЫЛА НЕ В ПЯТИ КРАСНЫХ, А В ФОНЕ: постоянная краснота учит не читать красное, и настоящий
красный тест новой работы 17.08 пришлось отличать отдельным прогоном по `origin/main`.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ. Не «пробы зелёные» — это видно и так, — а что они зелёные ПО ДЕЛУ: с поясом
проба обязана поймать поломку, а без изоляции — не поймать. Пара измеряется в двух состояниях
прямо здесь, потому что одно состояние ничего не доказывает.

ПОЯС ЕСТЬ НЕ ВЕЗДЕ. В CI editable-установки нет, и тогда сравнивать не с чем — тест ЧЕСТНО
пропускается с названной причиной, а не притворяется успехом.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ambient

PKG = Path(__file__).resolve().parents[2]
MISSING = "No module named '_bootstrap'"

pytestmark = pytest.mark.unit


def _clone_without_bootstrap(tmp_path: Path) -> Path:
    clone = tmp_path / "clone"
    for rel in ("VERSION", "tools", "ai_ops_kit"):
        src, dst = PKG / rel, clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    (clone / "ai_ops_kit" / "validation" / "_bootstrap.py").unlink()
    return clone


def test_probe_reaches_the_defect(tmp_path):
    """Сломанная КОПИЯ обязана падать — независимо от того, что установлено в окружении."""
    victim = _clone_without_bootstrap(tmp_path) / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py"
    r = ambient.run([victim], cwd=tmp_path, base=tmp_path)
    assert MISSING in r.stderr, (
        f"проба снова не доходит до места дефекта.\nstdout: {r.stdout[-400:]}\n"
        f"stderr: {r.stderr[-400:]}")


def test_without_isolation_the_same_probe_is_blind(tmp_path):
    """ВТОРОЕ СОСТОЯНИЕ ПАРЫ: без изоляции та же проба поломку НЕ видит — значит зелень первой
    даёт именно изоляция, а не удачное стечение обстоятельств.

    Пропуск с причиной, если пояса нет: сравнивать не с чем, и выдать это за успех нельзя."""
    if not ambient.ambient_kit_is_importable():
        pytest.skip("editable-установки кита в этом окружении нет — сравнивать не с чем "
                    "(в CI так и есть, и это нормально)")
    victim = _clone_without_bootstrap(tmp_path) / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, str(victim)], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=180)
    assert MISSING not in r.stderr, (
        "без изоляции проба ВНЕЗАПНО стала видеть поломку — значит пояса больше нет, и первый "
        "тест этой пары перестал что-либо доказывать; проверь окружение прежде чем радоваться")


def test_isolation_does_not_hide_third_party_dependencies(tmp_path):
    """Граница: `-S` выключает site целиком, и без каталога симлинков умер бы `import yaml` —
    то есть проба падала бы по ПОСТОРОННЕЙ причине и снова ничего не проверяла."""
    probe = tmp_path / "probe.py"
    probe.write_text("import yaml; print('OK', bool(yaml))\n", encoding="utf-8")
    r = ambient.run([probe], cwd=tmp_path, base=tmp_path, timeout=60)
    assert r.returncode == 0 and "OK True" in r.stdout, (r.stdout, r.stderr[-400:])


def test_third_party_list_is_explicit():
    """Список зависимостей ЯВНЫЙ: подкладывать «всё, что найдём» значило бы вернуть тот же ambient
    другим путём — только теперь молча и от имени проб."""
    assert ambient.THIRD_PARTY == ("yaml",), ambient.THIRD_PARTY
