"""#1525: обещание совместимости не шире того, на что реально опираются.

Повод (замер 11.11.2026, main 32ef0ea6): `ai-ops --help` показывал 7 действий владельца, а
`docs/api/public-surface.md` обещал не ломать 35 других точек (17 интентов и 18 команд кита) и не
упоминал сами 7 действий. Показанное не было обещано, обещанное не было показано.

Что сторожит файл:
  * positive     — у каждой `stable`-записи есть причина, и она подтверждается репозиторием;
  * fail-closed  — запись с причиной, которую репозиторий не подтверждает, краснеет; команда
                   установщика без объявленного уровня краснеет; показанное в `--help`, но не
                   обещанное, краснеет;
  * side-effect  — уровни не пересекаются: команда не может быть одновременно `stable` и
                   `experimental`.
"""
from __future__ import annotations

import re

import pytest

from tests.contracts.test_public_surface import DECL, REPO, _literal_dict_from

pytestmark = [pytest.mark.contract]

INSTRUCTION_SOURCES = ("templates", "plugin", "skills", "README.md", "docs/QUICKSTART.md",
                       "docs/guides/installation.md")
WRAPPER = REPO / "templates" / "runtime" / "ai-ops-entry.sh"
SETUP = REPO / "installer" / "setup_ops.py"
KNOWN_REASONS = {"plugin", "instructed", "setup", "wrapper"}


def _instructions() -> str:
    parts = []
    for rel in INSTRUCTION_SOURCES:
        p = REPO / rel
        files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file())
        parts += [f.read_text(encoding="utf-8", errors="ignore") for f in files]
    return "\n".join(parts)


INSTRUCTIONS = _instructions()
WRAPPER_SRC = WRAPPER.read_text(encoding="utf-8")


def _wrapper_routes_to(name: str) -> bool:
    """Обёртка дочки переадресует свою команду в `name` установщика (`kit-status` -> `status`)."""
    return re.search(rf"\n\s*kit-{re.escape(name)}\)\n\s*shift\n\s*set -- {re.escape(name)} ",
                     WRAPPER_SRC) is not None


def reason_holds(name: str, reason: str) -> bool:
    """Проверяет причину по репозиторию, а не по слову в декларации."""
    if reason == "plugin":
        return (REPO / "plugin" / "commands" / f"{name}.md").is_file()
    if reason == "instructed":
        return re.search(rf"ai-ops {re.escape(name)}(?![\w-])", INSTRUCTIONS) is not None
    if reason == "setup":
        return f'_run_managed_intent(root, "{name}"' in SETUP.read_text(encoding="utf-8")
    if reason == "wrapper":
        return _wrapper_routes_to(name)
    return False


def _stable_entries():
    for section in ("cli_intents", "kit_commands", "wrapper_commands"):
        entries = DECL["stable"][section]
        assert isinstance(entries, dict), f"stable.{section}: у каждой записи должна быть причина"
        for name, reason in entries.items():
            yield section, name, reason


# ---------------------------------------------------------------- positive ---

def test_every_stable_entry_has_a_reason_the_repository_confirms():
    unknown = [(s, n, r) for s, n, r in _stable_entries() if r not in KNOWN_REASONS]
    assert not unknown, f"неизвестные причины (допустимы {sorted(KNOWN_REASONS)}): {unknown}"
    unconfirmed = [(s, n, r) for s, n, r in _stable_entries() if not reason_holds(n, r)]
    assert not unconfirmed, (
        f"stable-записи, причину которых репозиторий не подтверждает: {unconfirmed}. "
        "Либо вернуть опору (плагин, инструкцию, вызов), либо перевести в experimental")


def test_facade_actions_are_exactly_what_help_shows():
    """Показанное владельцу обещано, обещанное — показано (в обе стороны)."""
    shown = set(_literal_dict_from(REPO / "ai_ops_kit" / "cli" / "human_facade.py", "HUMAN_ACTIONS"))
    promised = set(DECL["stable"]["facade_actions"])
    assert shown == promised, (
        f"--help показывает {sorted(shown)}, а stable.facade_actions — {sorted(promised)}")


def test_wrapper_commands_exist_in_the_child_wrapper():
    for name in DECL["stable"]["wrapper_commands"]:
        assert re.search(rf"\n\s*{re.escape(name)}\)\n", WRAPPER_SRC), (
            f"обёртка дочки не разбирает объявленную команду {name}")


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.parametrize("name,reason", [
    ("no-such-command", "plugin"),
    ("no-such-command", "instructed"),
    ("no-such-command", "setup"),
    ("no-such-command", "wrapper"),
    ("init", "because-i-said-so"),
])
def test_unconfirmed_reason_is_rejected(name, reason):
    """Причина — не слово в YAML: несуществующая опора или выдуманная причина не проходят."""
    assert not reason_holds(name, reason)


def test_every_installer_command_has_a_declared_level():
    src = (REPO / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    real = set(re.findall(r'cmd (?:==|in) \(?["\']([a-z][a-z-]*)["\']',
                          src.split("def _dispatch(", 1)[1]))
    declared = (set(DECL["stable"]["kit_commands"]) | set(DECL["experimental"]["kit_commands"])
                | set(DECL["internal"]["kit_commands"]))
    undeclared = sorted(real - declared)
    assert not undeclared, (
        f"команды установщика без уровня: {undeclared} — впишите в stable (с причиной), "
        "experimental или internal")


# ------------------------------------------------------------- side-effect ---

def test_kit_command_levels_do_not_overlap():
    levels = {"stable": set(DECL["stable"]["kit_commands"]),
              "experimental": set(DECL["experimental"]["kit_commands"]),
              "internal": set(DECL["internal"]["kit_commands"])}
    names = list(levels)
    overlaps = {(a, b): sorted(levels[a] & levels[b])
                for i, a in enumerate(names) for b in names[i + 1:] if levels[a] & levels[b]}
    assert not overlaps, f"команда объявлена на двух уровнях сразу: {overlaps}"
