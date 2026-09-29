"""Заморозка не-ASCII имён (`PLC2401`) ходит только вниз.

ПОВОД (#1183, замер 2026-09-29). Инвариант AGENTS.md «идентификаторы и ключи — английские» кит
требует от дочки, а сам нарушал: 630 кириллических имён в 18 файлах (`_ВЫЗОВ`, `_ЧЕРЕЗ_ОБОЛОЧКУ`
в `ai_ops_kit/security/scan_exec_call.py`). Правило включено в блокирующий набор ruff, а уже
написанное заморожено поштучно в `pyproject.toml -> [tool.ruff.lint.per-file-ignores]`.

Заморозка без сторожа — это дыра, которая только растёт: файл дописывают в список вместо
переименования, или исправленный файл остаётся в списке и тихо прикрывает следующую кириллицу.
Здесь держатся три свойства списка, каждое своим тестом:
  * записей не больше потолка — добавить файл нельзя, только убрать;
  * каждая запись — существующий файл, а не каталог и не glob, и гасит ровно `PLC2401`;
  * каждый файл в списке ВСЁ ЕЩЁ нарушает правило (нужен ruff; без него — громкий пропуск).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
RULE = "PLC2401"

# ПОТОЛОК = число замороженных файлов на момент включения правила (2026-09-29, #1183: 630 находок в
# 18 файлах). Поднимать нельзя. Исправил файл — убери запись из pyproject и опусти потолок сюда же:
# иначе освободившееся место молча займёт следующий файл.
FROZEN_FILES_CEILING = 18

_GLOB_CHARS = frozenset("*?[]{}")


def _lint_config() -> dict:
    with (KIT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]["lint"]


def _frozen() -> dict[str, list[str]]:
    """Записи per-file-ignores, в которых гасится `PLC2401`: путь -> список гашёных правил."""
    ignores = _lint_config().get("per-file-ignores", {})
    return {path: rules for path, rules in ignores.items() if RULE in rules}


def _ruff_cmd() -> list[str] | None:
    # Сначала ruff ТОГО ЖЕ окружения, что гоняет pytest (версия из dev-зависимостей), затем PATH.
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    found = shutil.which("ruff")
    return [found] if found else None


@pytest.mark.contract
def test_identifier_rules_stay_in_the_blocking_set():
    select = _lint_config()["select"]
    missing = [r for r in ("PLC2401", "PLC2403") if r not in select]
    assert not missing, (
        f"{missing} выпали из [tool.ruff.lint] select — заморозка ниже теряет смысл: без правила "
        f"новый кириллический идентификатор больше ничем не ловится")


@pytest.mark.contract
def test_frozen_list_only_shrinks():
    frozen = _frozen()
    assert len(frozen) <= FROZEN_FILES_CEILING, (
        f"в заморозке {RULE} {len(frozen)} файлов при потолке {FROZEN_FILES_CEILING}: новый файл "
        f"переименовывают на английские имена, а не дописывают в per-file-ignores")


@pytest.mark.contract
def test_ceiling_follows_the_shrinking_list():
    frozen = _frozen()
    assert len(frozen) >= FROZEN_FILES_CEILING, (
        f"в заморозке {RULE} {len(frozen)} файлов, а потолок всё ещё {FROZEN_FILES_CEILING}: опусти "
        f"FROZEN_FILES_CEILING до {len(frozen)}, иначе освободившееся место займёт новый файл")


@pytest.mark.contract
def test_frozen_entries_are_files_not_globs():
    bad = [p for p in _frozen() if _GLOB_CHARS & set(p) or not p.endswith(".py")]
    assert not bad, (
        f"заморозка {RULE} — поштучная, а эти записи накрывают больше одного файла: {bad}")


@pytest.mark.contract
def test_frozen_entries_point_at_existing_files():
    gone = [p for p in _frozen() if not (KIT / p).is_file()]
    assert not gone, (
        f"в заморозке {RULE} записи на несуществующие файлы: {gone} — удали их из per-file-ignores "
        f"и опусти FROZEN_FILES_CEILING")


@pytest.mark.contract
def test_frozen_entries_silence_only_the_identifier_rule():
    wide = {p: rules for p, rules in _frozen().items() if rules != [RULE]}
    assert not wide, (
        f"запись заморозки гасит больше, чем {RULE}: {wide} — другие правила замораживаются своим "
        f"решением, а не попутно")


@pytest.mark.contract
def test_every_frozen_file_still_violates(tmp_path):
    cmd = _ruff_cmd()
    if cmd is None:
        pytest.skip(
            f"РАТЧЕТ {RULE} НЕ ПРОВЕРЕН: ruff не установлен ни в этом окружении, ни в PATH. Это НЕ "
            f"зелёный — устаревшие записи заморозки сейчас не ловятся. Поставить: pip install -e '.[dev]'")
    frozen = sorted(_frozen())
    # --isolated: игнорировать per-file-ignores репо, иначе замороженные файлы молчат по определению.
    # --no-cache: не писать .ruff_cache в дерево репо; cwd=tmp_path — на случай побочных файлов.
    proc = subprocess.run(
        [*cmd, "check", "--isolated", "--no-cache", "--select", RULE,
         "--output-format", "json", "--exit-zero", *(str(KIT / p) for p in frozen)],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=120)
    assert proc.returncode == 0, f"ruff не отработал: {proc.stderr.strip()}"
    violating = {Path(item["filename"]).resolve() for item in json.loads(proc.stdout)}
    stale = [p for p in frozen if (KIT / p).resolve() not in violating]
    assert not stale, (
        f"эти файлы больше не нарушают {RULE}, но всё ещё заморожены: {stale} — убери их из "
        f"per-file-ignores и опусти FROZEN_FILES_CEILING, иначе заморозка прикроет новую кириллицу")
