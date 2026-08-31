"""События ядра не декоративны: объявленное «ИСПУСКАЕТСЯ» эмитится, «НЕ ИСПУСКАЕТСЯ» — нет.

ПОВОД (Волна 5, 26.08.2026). KernelEvent объявлял три типа события, а испускался ровно один
(`run_completed`). `gate_evaluated`/`delivery_completed` жили как контракт без единого `emit()` и без
подписчика — ровно та ловушка, что K7 закрыл для каталога инвариантов: объявлено, выглядит активным,
не делает ничего. Автор-подписчик, привязавшийся к такому событию, не получил бы НИКОГДА.

Этот тест держит контракт честным В ОБЕ СТОРОНЫ, по докстрингу самого KernelEvent:
  * тип, помеченный «ИСПУСКАЕТСЯ», обязан иметь хотя бы один реальный emit() в пакете;
  * тип, помеченный «НЕ ИСПУСКАЕТСЯ», не должен эмититься (иначе док врёт — обнови док вместе с кодом);
  * каждый реально эмитируемый тип обязан быть перечислен в докстринге (без «тихих» событий).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
CONTRACTS = PKG / "ai_ops_kit" / "shared" / "contracts.py"
SRC = PKG / "ai_ops_kit"


def _documented() -> tuple[set[str], set[str]]:
    """(emitted, not_emitted) — множества типов событий по докстрингу KernelEvent."""
    text = CONTRACTS.read_text(encoding="utf-8")
    block = re.search(r"class KernelEvent.*?\"\"\"(.*?)\"\"\"", text, re.S)
    assert block, "не найден докстринг KernelEvent"
    body = block.group(1)
    emitted, not_emitted = set(), set()
    for m in re.finditer(r"^\s*([a-z_]+)\s+—\s+(.*)$", body, re.M):
        name, desc = m.group(1), m.group(2)
        if "НЕ ИСПУСКАЕТСЯ" in desc:
            not_emitted.add(name)
        elif "ИСПУСКАЕТСЯ" in desc:
            emitted.add(name)
    assert emitted or not_emitted, "докстринг KernelEvent не размечает статусы событий"
    return emitted, not_emitted


def _really_emitted() -> set[str]:
    """Типы событий, реально передаваемые в emit(...) где-либо в пакете (кроме шины и тестов)."""
    found = set()
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts or p.name == "events.py":
            continue
        for m in re.finditer(r"""_?emit\(\s*["']([a-z_]+)["']""", p.read_text(encoding="utf-8")):
            found.add(m.group(1))
    return found


@pytest.mark.contract
def test_documented_emitted_events_are_actually_emitted():
    emitted, _ = _documented()
    real = _really_emitted()
    missing = emitted - real
    assert not missing, (
        f"события помечены «ИСПУСКАЕТСЯ», но emit() в пакете нет: {sorted(missing)} — "
        f"декоративный контракт (объявлено, не делает ничего)")


@pytest.mark.contract
def test_not_emitted_events_are_not_emitted():
    _, not_emitted = _documented()
    real = _really_emitted()
    lying = not_emitted & real
    assert not lying, (
        f"события помечены «НЕ ИСПУСКАЕТСЯ», но реально эмитятся: {sorted(lying)} — "
        f"док врёт, обнови докстринг вместе с кодом (событие стало активным)")


@pytest.mark.contract
def test_every_emitted_event_is_documented():
    emitted, not_emitted = _documented()
    real = _really_emitted()
    undocumented = real - emitted - not_emitted
    assert not undocumented, (
        f"эмитятся события, не перечисленные в докстринге KernelEvent: {sorted(undocumented)} — "
        f"тихое событие, спутник о нём не узнает")
