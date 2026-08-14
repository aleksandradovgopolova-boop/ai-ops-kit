"""Команда, напечатанная человеку, обязана быть исполнимой как напечатана (B2-10, 2026-08-14).

ПОВОД — ЖИВОЙ ПРОГОН. Блокирующее сообщение кита велело владельцу «передай resume=True (--resume) …
discard_previous=True (--discard)». Оба флага существуют — но у ВНУТРЕННЕЙ точки входа
`ai_ops_run.py`, а человек в этот момент работает через `ai-ops`. Он набирает напечатанную строку и
получает отказ.

ПОЧЕМУ ЭТО НЕ МЕЛОЧЬ. У кита объявлена цель «каждая объявленная точка входа работает», и она
проверяется по точкам входа. А человек набирает не точку входа, а СТРОКУ, которую кит ему напечатал.
Такие строки живут в ветках отказа — там, куда тесты не ходят, и куда человек попадает в худший
момент: когда у него уже что-то не получилось.

КАК ПРОВЕРЯЕТСЯ. Словарь флагов берётся ИЗ КОДА CLI разбором AST — не переписывается в тест, иначе
появилась бы вторая правда об одном наборе флагов (ровно та ошибка, из-за которой `ARCH-01` проходил
валидатор плана и падал в движке). Напечатанные команды тоже извлекаются из кода: любая строковая
константа пакета, содержащая `ai-ops <intent>`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
#: У `ai-ops` ДВЕ поверхности, и обе настоящие: интент-CLI движка и установщик в child-репозитории.
#: Проверять по одной значило бы объявлять несуществующим флаг, который у человека работает.
CLI_SURFACES = (PKG / "ai_ops_kit" / "cli" / "ai_ops_cli.py", PKG / "installer" / "ai_ops.py")
#: Что кит печатает как «наберите это». Команда ограничена ОДНОЙ строкой: без этого регулярка
#: съедала полдокстринга и «находила» флаг, стоящий абзацем ниже (найдено этим же тестом).
CMD_RE = re.compile(r"ai-ops[ \t]+([a-z][a-z-]*)((?:[ \t]+[^\s`'\"]+)*)")
#: Плейсхолдеры в напечатанных строках: `{a.child_root}`, `<wid>`, `…`.
PLACEHOLDER = re.compile(r"\{[^}]*\}|<[^>]*>")


def _known_flags() -> set:
    """Флаги обеих поверхностей `ai-ops` — из КОДА, а не из списка в тесте.

    Две правды об одном наборе флагов уже стоили дефекта (`ARCH-01` проходил валидатор плана и падал
    в движке). Интент-CLI объявляет флаги через argparse; установщик разбирает `argv` вручную,
    поэтому у него флаг — это строковая константа, начинающаяся с `--`.
    """
    flags = set()
    for path in CLI_SURFACES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if v.startswith("--") and len(v) > 2 and " " not in v:
                    flags.add(v)
    return flags


def _string_constants(path: Path):
    """Строковые константы модуля вместе с номером строки (f-string склеивается по частям)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                      # pragma: no cover — чужой файл
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            parts = "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str)
                            else "{}" for v in node.values)
            yield node.lineno, parts


def _printed_commands():
    """[(файл, строка, команда, [флаги])] — всё, что кит печатает как `ai-ops …`."""
    out = []
    for p in sorted((PKG / "ai_ops_kit").rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        for lineno, s in _string_constants(p):
            for m in CMD_RE.finditer(s):
                cmd = PLACEHOLDER.sub("X", m.group(0))
                flags = re.findall(r"--[a-z][a-z-]*", cmd)
                out.append((p.relative_to(PKG).as_posix(), lineno, cmd.strip(), flags))
    return out


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_the_flag_vocabulary_is_read_from_the_cli_itself():
    """Механизм опирается на код, а не на список в тесте: иначе он устареет молча."""
    flags = _known_flags()

    assert "--execute" in flags and "--feature" in flags, sorted(flags)[:10]
    assert len(flags) > 10, f"словарь флагов подозрительно мал: {sorted(flags)}"


def test_the_kit_prints_at_least_one_command_to_the_human():
    """Если строк не нашлось — тест проверяет пустоту и молчит о настоящих командах."""
    assert _printed_commands(), "напечатанных команд не найдено — механизм смотрит не туда"


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_every_printed_command_uses_only_flags_that_exist():
    """ГЛАВНОЕ: в напечатанной человеку команде нет флага, которого у `ai-ops` нет.

    Замер B2-10: сообщение велело передать `--resume` и `--discard`. Эти флаги есть — у внутренней
    точки входа `ai_ops_run.py`, а человек в этот момент работает через `ai-ops`. Он набирает строку
    и получает отказ ровно тогда, когда у него уже что-то не получилось.
    """
    known = _known_flags()
    bad = [(f, ln, cmd, fl) for f, ln, cmd, flags in _printed_commands()
           for fl in flags if fl not in known]

    assert not bad, "напечатанные команды с несуществующими флагами:\n" + "\n".join(
        f"  {f}:{ln}: «{cmd}» — флага {fl} у `ai-ops` нет" for f, ln, cmd, fl in bad)


@pytest.mark.parametrize("sample,expected_flag", [
    ("продолжить: ai-ops resume . X --execute", "--execute"),
    ("запусти `ai-ops run . --feature X --open-pr`", "--open-pr"),
])
def test_the_extractor_really_sees_flags(sample, expected_flag):
    """Side-effect proof: извлекатель находит флаги в реальных формах строк.

    Без этого главный тест мог бы «проходить» просто потому, что ничего не извлёк, — самый тихий
    способ для проверки перестать проверять.
    """
    flags = re.findall(r"--[a-z][a-z-]*", PLACEHOLDER.sub("X", CMD_RE.search(sample).group(0)))

    assert expected_flag in flags, flags
