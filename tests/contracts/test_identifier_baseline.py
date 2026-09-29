"""Заморозка не-ASCII имён (`PLC2401`) ходит только вниз — и по файлам, и по числу находок в файле.

ПОВОД (#1183, замер 2026-09-29). Инвариант AGENTS.md «идентификаторы и ключи — английские» кит
требует от дочки, а сам нарушал: 630 кириллических имён в 18 файлах (`_ВЫЗОВ`, `_ЧЕРЕЗ_ОБОЛОЧКУ`
в `ai_ops_kit/security/scan_exec_call.py`). Правило включено в блокирующий набор ruff, а уже
написанное заморожено поштучно в `pyproject.toml -> [tool.ruff.lint.per-file-ignores]`.

ПОЧЕМУ ПОТОЛОК НА КАЖДЫЙ ФАЙЛ, А НЕ ТОЛЬКО СПИСОК. `per-file-ignores` гасит правило для ВСЕГО
файла: новое кириллическое имя, дописанное в любой из 18 замороженных файлов, ruff не видит вовсе.
Список файлов при этом не меняется, и сторож «список только сокращается» остаётся зелёным — ровно
тот дрейф, против которого #1183. Поэтому число находок в каждом файле закреплено ниже, и ruff
(`--isolated`, то есть без заморозки) пересчитывает его на каждом прогоне.

Свойства, каждое своим тестом:
  * записей не больше потолка, и потолок опускается вслед за списком;
  * список в pyproject и потолки здесь — одно множество файлов;
  * каждая запись — существующий файл, не каталог и не glob, и гасит ровно `PLC2401`;
  * число находок в файле не растёт; упало — опусти потолок; дошло до нуля — убери файл из списка.
Тесты с ruff без ruff громко пропускаются; в CI ruff ставится в джобе с шардом `contracts`.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
RULE = "PLC2401"

# ПОТОЛОК ЧИСЛА ФАЙЛОВ = размер заморозки на момент включения правила (2026-09-29, #1183).
# Поднимать нельзя. Исправил файл — убери запись из pyproject, из FROZEN_COUNTS и опусти потолок.
FROZEN_FILES_CEILING = 18

# ПОТОЛОК НАХОДОК В КАЖДОМ ФАЙЛЕ. Замер 2026-09-29: `ruff check --isolated --select PLC2401`
# (ruff 0.16.2, та же версия, что в CI), всего 630. Число только опускается: переименовал имена —
# впиши сюда новое, меньшее; дошло до нуля — файл уходит из заморозки целиком.
FROZEN_COUNTS = {
    "ai_ops_kit/security/scan_exec_call.py": 101,
    "ai_ops_kit/security/scan_inline_code.py": 188,
    "ai_ops_kit/security/scan_prose.py": 39,
    "ai_ops_kit/security/scan_secret_noise.py": 21,
    "ai_ops_kit/security/scan_vendor.py": 11,
    "ai_ops_kit/security/security_pack.py": 1,
    "ai_ops_kit/security/security_scan.py": 17,
    "ai_ops_kit/ui/presenter_graph.py": 1,
    "tests/unit/test_delivered_kit_scan.py": 1,
    "tests/unit/test_security_scan.py": 6,
    "tests/unit/test_security_scan_address_not_led_away.py": 30,
    "tests/unit/test_security_scan_inline_code.py": 38,
    "tests/unit/test_security_scan_literal_binary.py": 62,
    "tests/unit/test_security_scan_placeholder_is_a_word.py": 28,
    "tests/unit/test_security_scan_product_path_vs_harness.py": 6,
    "tests/unit/test_security_scan_secret_false_blocks.py": 15,
    "tests/unit/test_security_scan_tells_the_truth.py": 11,
    "tests/unit/test_security_scan_vendor_section.py": 54,
}

_GLOB_CHARS = frozenset("*?[]{}")


def _lint_config() -> dict:
    with (KIT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]["lint"]


def _frozen() -> dict[str, list[str]]:
    """Записи per-file-ignores, в которых гасится `PLC2401`: путь -> список гашёных правил."""
    ignores = _lint_config().get("per-file-ignores", {})
    return {path: rules for path, rules in ignores.items() if RULE in rules}


def _ruff_cmd() -> list[str] | None:
    # Сначала ruff ТОГО ЖЕ окружения, что гоняет pytest (в CI — пин из package-quality.yml), затем PATH.
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    found = shutil.which("ruff")
    return [found] if found else None


@pytest.fixture(scope="module")
def counts(tmp_path_factory) -> dict[str, int]:
    """Фактическое число находок `PLC2401` в каждом замороженном файле — без самой заморозки."""
    cmd = _ruff_cmd()
    if cmd is None:
        pytest.skip(
            f"РАТЧЕТ {RULE} НЕ ПРОВЕРЕН: ruff не установлен ни в этом окружении, ни в PATH. Это НЕ "
            f"зелёный — рост и устаревание заморозки сейчас не ловятся. Поставить: pip install -e '.[dev]'")
    files = sorted(set(_frozen()) | set(FROZEN_COUNTS))
    existing = [p for p in files if (KIT / p).is_file()]
    # --isolated: игнорировать per-file-ignores репо, иначе замороженные файлы молчат по определению.
    # --no-cache: не писать .ruff_cache в дерево репо; cwd — временный каталог.
    proc = subprocess.run(
        [*cmd, "check", "--isolated", "--no-cache", "--select", RULE,
         "--output-format", "json", "--exit-zero", *(str(KIT / p) for p in existing)],
        cwd=tmp_path_factory.mktemp("ruff"), capture_output=True, text=True, check=False, timeout=120)
    assert proc.returncode == 0, f"ruff не отработал: {proc.stderr.strip()}"
    by_path = Counter(Path(item["filename"]).resolve() for item in json.loads(proc.stdout))
    return {p: by_path.get((KIT / p).resolve(), 0) for p in existing}


@pytest.mark.contract
def test_identifier_rules_stay_in_the_blocking_set():
    select = _lint_config()["select"]
    missing = [r for r in ("PLC2401", "PLC2403") if r not in select]
    assert not missing, (
        f"{missing} выпали из [tool.ruff.lint] select — заморозка ниже теряет смысл: без правила "
        f"новый кириллический идентификатор больше ничем не ловится")


@pytest.mark.contract
def test_ci_pins_one_ruff_for_lint_and_this_guard():
    # ruff теперь ставится в ДВУХ джобах package-quality.yml (lint и матрица с шардом contracts), а
    # `tests/unit/test_linter_version_is_single.py` сверяет с хуком только первый пин. Разъехавшись,
    # два пина дали бы сторожу другие числа, чем линтеру.
    text = (KIT / ".github" / "workflows" / "package-quality.yml").read_text(encoding="utf-8")
    pins = set(re.findall(r"'ruff==([\d.]+)'", text))
    assert len(pins) == 1, f"в package-quality.yml разные пины ruff: {sorted(pins)} — пин должен быть один"


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
def test_frozen_list_matches_per_file_ceilings():
    listed, pinned = set(_frozen()), set(FROZEN_COUNTS)
    assert listed == pinned, (
        f"заморозка в pyproject и FROZEN_COUNTS разошлись: только в pyproject {sorted(listed - pinned)}, "
        f"только в тесте {sorted(pinned - listed)} — у каждого замороженного файла должен быть потолок")


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
        f"и FROZEN_COUNTS и опусти FROZEN_FILES_CEILING")


@pytest.mark.contract
def test_frozen_entries_silence_only_the_identifier_rule():
    wide = {p: rules for p, rules in _frozen().items() if rules != [RULE]}
    assert not wide, (
        f"запись заморозки гасит больше, чем {RULE}: {wide} — другие правила замораживаются своим "
        f"решением, а не попутно")


@pytest.mark.contract
def test_no_frozen_file_gains_identifiers(counts):
    grown = {p: f"{FROZEN_COUNTS[p]} -> {n}" for p, n in counts.items()
             if p in FROZEN_COUNTS and n > FROZEN_COUNTS[p]}
    assert not grown, (
        f"в замороженных файлах прибавилось не-ASCII имён ({RULE}): {grown}. Заморозка гасит правило "
        f"для всего файла, поэтому ruff их не видит — новые имена пишутся по-английски")


@pytest.mark.contract
def test_per_file_ceiling_follows_the_shrinking_count(counts):
    slack = {p: f"потолок {FROZEN_COUNTS[p]}, факт {n}" for p, n in counts.items()
             if p in FROZEN_COUNTS and 0 < n < FROZEN_COUNTS[p]}
    assert not slack, (
        f"находок {RULE} стало меньше, а потолок прежний: {slack} — впиши в FROZEN_COUNTS факт, иначе "
        f"освободившийся запас займут новые не-ASCII имена")


@pytest.mark.contract
def test_every_frozen_file_still_violates(counts):
    clean = sorted(p for p in _frozen() if counts.get(p, 0) == 0 and (KIT / p).is_file())
    assert not clean, (
        f"эти файлы больше не нарушают {RULE}, но всё ещё заморожены: {clean} — убери их из "
        f"per-file-ignores и FROZEN_COUNTS и опусти FROZEN_FILES_CEILING, иначе заморозка прикроет "
        f"новую кириллицу")
