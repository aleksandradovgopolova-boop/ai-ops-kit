"""Состав top-level имён дистрибутива не растёт молча (v3.33.2).

`pyproject.toml` кладёт в site-packages рядом с `ai_ops_kit` два РОДОВЫХ имени — `tools` и
`validation`. В любом окружении, куда поставлен кит, `import tools` резолвится в него: это конфликт
имён с чужими проектами.

Объявлено границей (`release-claims.standing_boundaries`), а не дефектом, осознанно. Убрать их из
колеса нельзя, пока код пакета зовёт валидаторов по плоскому имени: `validation/` — не пакет
`ai_ops_kit`, пакетного имени у валидаторов нет. Честное решение — перенос `validation/` под
`ai_ops_kit/` — отдельный срез: 74 файла, раскладка `.ai/managed/` в child и точки входа, которые
знают документация и `doctor`.

Здесь — ратчет, а не разрешение: список известных имён вправе сокращаться, но новое родовое имя
(`utils`, `common`, `scripts`…) молча не появится. Тест ловит и обратное — исчезновение имени,
которое кто-то мог начать импортировать.

Три обязательных теста на capability (AGENTS.md):
  * positive     — состав top-level имён ровно тот, что объявлен;
  * fail-closed  — добавление нового имени в конфиг ловится;
  * side-effect  — граница объявлена в release-claims, а не только здесь (иначе о ней узнают из
                   кода теста, а не из публичной поверхности).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[2]

# Ровно то, что кит кладёт в site-packages. Меняется ТОЛЬКО осознанно и вместе с границей в claims.
KNOWN_TOPLEVEL = {"ai_ops_kit", "tools", "validation"}
GENERIC = KNOWN_TOPLEVEL - {"ai_ops_kit"}          # имена, которые может занять кто угодно


def _declared_packages():
    """Список include из pyproject — разбором текста, БЕЗ tomllib.

    `tomllib` появился в 3.11, а объявленный пол кита — 3.9: проверка совместимости не вправе
    сама её нарушать. Читаем ровно одну строку `include = [...]`, значение — литерал списка.
    """
    text = (PKG / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"^\s*include\s*=\s*(\[[^\]]*\])", text, re.M)
    assert m, "в pyproject.toml не найден include для packages.find"
    return {name.split(".")[0] for name in ast.literal_eval(m.group(1))}


def test_toplevel_names_are_exactly_the_declared_set():
    """positive: состав дистрибутива не разошёлся с объявленным."""
    assert _declared_packages() == KNOWN_TOPLEVEL, (
        f"состав top-level имён изменился: {sorted(_declared_packages())} != "
        f"{sorted(KNOWN_TOPLEVEL)}. Каждое родовое имя — конфликт с чужими проектами; "
        "менять только вместе с границей в registry/release-claims.yaml")


def test_new_generic_name_would_be_caught():
    """fail-closed: проба обязана поймать добавленное имя, иначе она бесполезна."""
    pretend = _declared_packages() | {"utils"}
    assert pretend != KNOWN_TOPLEVEL, "проба не отличает расширенный состав от объявленного"


def test_boundary_is_declared_on_the_public_surface():
    """side-effect: про границу написано там, где её видит владелец, а не только в тесте."""
    claims = yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))
    boundaries = claims.get("standing_boundaries") or []
    assert any("toplevel" in str(b) for b in boundaries), (
        "родовые имена в дистрибутиве не объявлены в standing_boundaries — "
        f"известные родовые: {sorted(GENERIC)}; молчаливая граница ничем не лучше дефекта")
