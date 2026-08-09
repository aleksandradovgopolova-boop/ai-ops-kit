"""Установка пакета не правит sys.path чужих процессов (v3.33.1).

`setup.py` на уровне модуля писал `.pth` в site-packages ПОЛЬЗОВАТЕЛЯ, подкладывая корень
репозитория, `tools/` и `validation/` в каждый процесс Python на машине. Файл писался при любом
запуске setup.py — включая установку в venv, откуда он всё равно попадал в общий пользовательский
site, за пределы целевого окружения; путь зашивался абсолютный, от каталога сборки.

Главное даже не мусор в системе. Это ровно тот пояс, который прячет дефекты: весь август
репозиторий чинил класс «работает локально из-за editable-установки» — и ставил себе эту установку
сам, на любом `pip install`. Пакет, правящий пути чужих процессов, лишает и себя, и пользователя
возможности увидеть, что он сломан. В этой сессии пояс успел замаскировать fail-closed-проверку
`test_missing_bootstrap_is_caught`, которая перестала краснеть на удалённом файле.

Три обязательных теста на capability (AGENTS.md):
  * positive     — сборочные файлы не пишут ничего за пределы своего каталога;
  * fail-closed  — возврат старого приёма ловится: пробе подсовывается setup.py, который так делает;
  * side-effect  — пакету пути и не нужны: `_bootstrap` находит корень по маркеру в рантайме.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]

# Приёмы записи в окружение интерпретатора. Имя `.pth` — не единственный способ, поэтому ловим
# и обращения к site-каталогам: любой из них в сборочном файле означает выход за свои границы.
FORBIDDEN_CALLS = {"getusersitepackages", "getsitepackages", "USER_SITE"}


def _environment_writes(source: str) -> list[str]:
    """Признаки правки чужого окружения в сборочном файле."""
    found = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
            found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            found.append(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.endswith(".pth"):
            found.append(node.value)
    return found


@pytest.mark.parametrize("rel", ["setup.py", "pyproject.toml"])
def test_build_files_do_not_write_into_site_packages(rel):
    """positive: сборка не трогает site-packages пользователя."""
    path = PKG / rel
    if not path.is_file():
        pytest.skip(f"{rel} отсутствует")
    source = path.read_text(encoding="utf-8")
    if rel.endswith(".toml"):
        assert ".pth" not in source, f"{rel} упоминает .pth — установка правит чужое окружение"
        return
    found = _environment_writes(source)
    assert not found, (
        f"{rel} пишет в окружение интерпретатора ({found}) — установка пакета не вправе менять "
        "sys.path чужих процессов; пути кит находит в рантайме по маркеру VERSION")


def test_old_trick_would_be_caught(tmp_path):
    """fail-closed: вернут приём — проба обязана его назвать."""
    victim = tmp_path / "setup.py"
    victim.write_text(
        "import os, site\n"
        "from setuptools import setup\n"
        "pth = os.path.join(site.getusersitepackages(), 'ai_ops_kit.pth')\n"
        "open(pth, 'w').write('import sys')\n"
        "setup()\n", encoding="utf-8")

    found = _environment_writes(victim.read_text(encoding="utf-8"))
    assert "getusersitepackages" in found and any(f.endswith(".pth") for f in found), (
        f"старый приём не пойман ({found}) — проба не удержит возврат")


def test_runtime_bootstrap_finds_root_by_marker():
    """side-effect: пути ставятся в рантайме, поэтому .pth при установке не нужен."""
    source = (PKG / "ai_ops_kit" / "shared" / "_bootstrap.py").read_text(encoding="utf-8")
    assert "VERSION" in source and "sys.path" in source, (
        "рантайм-bootstrap перестал искать корень по маркеру — без него установка снова "
        "потребует правки чужого окружения")
