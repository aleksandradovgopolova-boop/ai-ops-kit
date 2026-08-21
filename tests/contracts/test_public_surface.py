"""Публичная граница: объявленное обязано совпадать с тем, что есть.

ЗАЧЕМ. До `docs/api/public-surface.md` границы не существовало — а значит, не существовало и
определения breaking change. Канал `stable` обещал дочкам совместимость, ничем не подкреплённую:
любая правка могла оказаться ломающей, и ни одна не была ломающей наверняка.

ЧТО СТОРОЖИТ ЭТОТ ФАЙЛ. Не «правильность» декларации — её решает человек. Только РАСХОЖДЕНИЕ:
появился интент, которого нет в документе; исчез объявленный; в `stable`-схеме прибавилось
обязательное поле. Последнее — и есть breaking change, и он обязан быть решением, а не побочным
эффектом правки схемы.

Правят декларацию, а не тест.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждая объявленная поверхность существует в коде;
  * fail-closed  — каждая существующая поверхность объявлена (незаявленного не бывает);
  * side-effect  — снимок обязательных полей `stable`-схем совпадает с файлами схем.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.contract]

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "api" / "public-surface.md"


def _declaration() -> dict:
    """Декларация — ПЕРВЫЙ yaml-блок документа. Документ и есть источник истины: второй файл
    рядом с ним стал бы второй правдой, и они разъехались бы на первой же правке."""
    text = DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"^```yaml\n(.*?)^```", text, re.S | re.M)
    assert blocks, f"{DOC.name}: машиночитаемой декларации нет — сторожить нечего"
    doc = yaml.safe_load(blocks[0])
    assert doc.get("kind") == "ai-ops-public-surface", "первый yaml-блок — не декларация поверхности"
    return doc


DECL = _declaration()


def _literal_dict_from(path: Path, name: str):
    """Значение модульной константы без импорта модуля: у CLI импорт тянет весь движок."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name}: константа {name} не найдена")


# ---------------------------------------------------------------- positive ---

@pytest.mark.contract
def test_every_declared_intent_exists():
    """Объявленный интент обязан существовать. Иначе документ обещает то, чего нет."""
    real = set(_literal_dict_from(REPO / "ai_ops_kit" / "cli" / "ai_ops_cli.py", "INTENTS"))
    declared = set(DECL["stable"]["cli_intents"]) | set(DECL["experimental"]["cli_intents"])
    ghosts = sorted(declared - real)
    assert not ghosts, (
        f"объявлены несуществующие интенты: {ghosts}. Либо интент вернуть, либо убрать из "
        f"{DOC.name} — но убрать объявленный `stable` интент можно только через окно вывода "
        f"(AGENTS.md, «Публичная граница и breaking change»)")


@pytest.mark.contract
def test_every_declared_kit_command_exists():
    """Команда кита объявлена — значит, установщик обязан её разбирать."""
    src = (REPO / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    dispatch = src.split("def _dispatch(", 1)[1]
    real = set(re.findall(r'cmd (?:==|in) \(?["\']([a-z][a-z-]*)["\']', dispatch))
    ghosts = sorted(set(DECL["stable"]["kit_commands"]) - real)
    assert not ghosts, f"объявлены команды кита, которых нет в установщике: {ghosts}"


@pytest.mark.contract
def test_every_declared_schema_file_exists():
    for name in DECL["stable"]["schemas"]:
        assert (REPO / "schemas" / f"{name}.schema.json").is_file(), \
            f"схема {name} объявлена стабильной, а файла нет"


@pytest.mark.contract
def test_every_declared_internal_package_exists():
    real = {d.name for d in (REPO / "ai_ops_kit").iterdir()
            if d.is_dir() and d.name != "__pycache__"}
    ghosts = sorted(set(DECL["internal"]["packages"]) - real)
    assert not ghosts, f"объявлены несуществующие пакеты: {ghosts}"


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.contract
def test_no_undeclared_intent():
    """Незаявленной поверхности не бывает: новый интент обязан получить уровень.

    Это и есть смысл границы. Интент, попавший в CLI без записи здесь, автоматически считался бы
    контрактом — ровно так `stable` и оказался обещанием без содержания.
    """
    real = set(_literal_dict_from(REPO / "ai_ops_kit" / "cli" / "ai_ops_cli.py", "INTENTS"))
    declared = set(DECL["stable"]["cli_intents"]) | set(DECL["experimental"]["cli_intents"])
    undeclared = sorted(real - declared)
    assert not undeclared, (
        f"интенты без объявленного уровня: {undeclared}. Впишите их в {DOC.name} — в `stable`, "
        f"если дочка вправе на них опираться, иначе в `experimental`")


@pytest.mark.contract
def test_no_undeclared_internal_package():
    real = {d.name for d in (REPO / "ai_ops_kit").iterdir()
            if d.is_dir() and d.name != "__pycache__"}
    undeclared = sorted(real - set(DECL["internal"]["packages"]))
    assert not undeclared, f"пакеты без объявленного уровня: {undeclared}"


@pytest.mark.contract
def test_no_undeclared_advisory_gate():
    """Advisory-гейт — `experimental`: он не блокирует, и дочка вправе знать, что форма ещё меняется."""
    gates = yaml.safe_load((REPO / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    real = {gid for gid, g in gates.items() if not g.get("blocking")}
    declared = set(DECL["experimental"]["advisory_gates"])
    assert real == declared, (
        f"разошлись advisory-гейты: только в реестре {sorted(real - declared)}, "
        f"только в декларации {sorted(declared - real)}")


@pytest.mark.contract
def test_exit_codes_of_the_engine_are_only_the_declared_ones():
    """Код возврата — часть контракта: по нему CI дочки решает, останавливать ли конвейер.

    Незаявленный код читался бы дочкой как «что-то третье» — то есть никак.
    """
    src = (REPO / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    declared = {int(c) for c in DECL["stable"]["exit_codes"]}
    used = set()
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == "main":
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, int):
                    used.add(node.value.value)
    assert used, "в main() не нашлось ни одного явного кода возврата — разбор сломан, а не чист"
    undeclared = sorted(used - declared)
    assert not undeclared, (
        f"движок возвращает необъявленные коды: {undeclared}. Смысл кода — контракт; "
        f"впишите его в {DOC.name} вместе с тем, что он означает для человека")


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.contract
def test_required_fields_of_stable_schemas_did_not_change():
    """Новое обязательное поле в `stable`-схеме — breaking change по определению.

    Существующие документы дочки перестают проходить валидацию в тот же день. Снимок в декларации
    делает это ВИДИМЫМ: правка схемы краснеет, и человек решает — major с окном вывода или поле
    становится необязательным.
    """
    drift = []
    for name, snapshot in DECL["stable"]["schemas"].items():
        schema = json.loads((REPO / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
        real = list(schema.get("required") or [])
        if real != list(snapshot):
            added = sorted(set(real) - set(snapshot))
            removed = sorted(set(snapshot) - set(real))
            drift.append(f"{name}: добавлено обязательным {added or '—'}, "
                         f"перестало быть обязательным {removed or '—'}")
    assert not drift, (
        "обязательные поля stable-схем разошлись со снимком в декларации — это breaking change:\n  "
        + "\n  ".join(drift))


@pytest.mark.contract
def test_declared_ai_layout_is_what_the_installer_really_writes():
    """Раскладка `.ai/` — контракт: `.ai/project/` и `.ai/custom/` обновление не трогает."""
    src = (REPO / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    missing = [path for path in DECL["stable"]["ai_layout"] if path.rstrip("/") not in src]
    assert not missing, (
        f"объявленные каталоги `.ai/` установщику неизвестны: {missing} — либо декларация "
        f"описывает раскладку, которой нет, либо каталог перестал создаваться")


@pytest.mark.contract
def test_deprecated_level_points_at_a_real_registry():
    """`deprecated` без реестра — обещание вывода без списка выводимого."""
    rel = DECL["deprecated"]["flat_module_aliases"]["registry"]
    registry = REPO / rel
    assert registry.is_file(), f"реестр уходящей поверхности объявлен ({rel}), а файла нет"
    doc = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert doc.get("flat_module_aliases"), f"{rel}: реестр пуст — сокращать нечего"
