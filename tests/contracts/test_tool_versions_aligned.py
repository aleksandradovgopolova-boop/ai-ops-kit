"""Версия инструмента ОДНА во всех объявлениях — расхождение краснеет (#1402, #1414).

ПОВОД. Ревью main@55d8d8fa, п.9: CI и pre-commit держали Ruff одной версии, dev-инструкции —
другой. Разные версии линтера дают разные находки — «зелёно локально» и «зелёно в CI» становятся
утверждениями про РАЗНЫЕ линтеры, и правки ходят теми же кругами, что при дрейфе версии Python
(тот же класс, см. замер единой версии Python, PR #1502). Инструмент объявлялся в пяти местах
(`pyproject.toml`, `requirements-dev.txt`, `.pre-commit-config.yaml`, CI-workflow'ы, теперь
`uv.lock`), и ничто не стерегло их согласованность.

ЕДИНЫЙ ИСТОЧНИК — `pyproject.toml`: `[project].dependencies` (pyyaml) и
`[project.optional-dependencies].dev` (остальные). Пол, объявленный там, — истина; любое другое
объявление обязано ему соответствовать:

  * ruff и mypy — находко-чувствительные: РОВНО та же версия везде (CI-пин, pre-commit rev,
    uv.lock, requirements-dev пол) == пол в pyproject. 0.1 версии ruff меняет набор находок.
  * pytest / pytest-xdist / pytest-cov / hypothesis / pyyaml — по СЕРИИ: мажор CI-пина (`==N.*`),
    зафиксированной версии в uv.lock и пола requirements-dev обязан совпадать с мажором пола
    pyproject, а зафиксированное в uv.lock — быть не ниже пола. Поймал реальный дрейф: pyproject
    держал `pytest>=8.0`, а CI и lock — pytest 9 (пол ниже того, что реально требует CI).

Проверка — контракт МАТЕРИНСКОГО репозитория (CI-workflow'ы и uv.lock в дочку не едут,
`tests/` вне managed_set), поэтому живёт здесь, а не в shipped-валидаторе.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())

# Инструмент -> как сверять. EXACT: находко-чувствительные, равенство полной версии.
# SERIES: сверяем мажор и «не ниже пола».
EXACT = {"ruff", "mypy"}
SERIES = {"pytest", "pytest-xdist", "pytest-cov", "hypothesis", "pyyaml"}
ALIGNED = EXACT | SERIES


def _ver(text):
    """'v0.17.3' / '9.2.0' / '9.*' / '==6.*' -> кортеж int-компонент (звезда и хвост отброшены)."""
    text = text.strip().lstrip("v")
    nums = []
    for part in text.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        nums.append(int(m.group()))
    return tuple(nums)


def _floors_from_pyproject():
    """{tool: (floor_tuple, raw)} из единого источника."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specs = list(data["project"].get("dependencies", []))
    specs += data["project"].get("optional-dependencies", {}).get("dev", [])
    floors = {}
    for spec in specs:
        m = re.match(r"([A-Za-z0-9_.-]+)\s*>=\s*([0-9][0-9.*]*)", spec)
        if m and m.group(1).lower() in ALIGNED:
            floors[m.group(1).lower()] = (_ver(m.group(2)), spec)
    return floors


def _observed():
    """[(tool, version_str, source, is_exact_pin)] — все прочие объявления версий."""
    seen = []

    # requirements-dev.txt — зеркало полов.
    req = ROOT / "requirements-dev.txt"
    if req.is_file():
        for line in req.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*>=\s*([0-9][0-9.*]*)", line)
            if m and m.group(1).lower() in ALIGNED:
                seen.append((m.group(1).lower(), m.group(2), "requirements-dev.txt", False))

    # .pre-commit-config.yaml — rev хука ruff.
    pc = ROOT / ".pre-commit-config.yaml"
    if pc.is_file():
        cfg = yaml.safe_load(pc.read_text(encoding="utf-8")) or {}
        for repo in cfg.get("repos", []):
            if str(repo.get("repo", "")).endswith("ruff-pre-commit"):
                seen.append(("ruff", str(repo.get("rev", "")), ".pre-commit-config.yaml", True))

    # CI-workflow'ы — пины в строках установки (pip/uv).
    wf_re = re.compile(r"([A-Za-z0-9_.-]+)(==|>=)([0-9][0-9.*]*)")
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in wf.read_text(encoding="utf-8").splitlines():
            if "install" not in line:
                continue
            for name, op, ver in wf_re.findall(line):
                if name.lower() in ALIGNED:
                    seen.append((name.lower(), ver, f".github/workflows/{wf.name}", op == "=="))

    # uv.lock — зафиксированные версии.
    lock = ROOT / "uv.lock"
    if lock.is_file():
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
        for pkg in data.get("package", []):
            name = str(pkg.get("name", "")).lower()
            if name in ALIGNED and pkg.get("version"):
                seen.append((name, str(pkg["version"]), "uv.lock", True))

    return seen


def check(floors, observed):
    """ЧИСТОЕ ядро сверки: -> список находок (строк). Пусто = согласовано.

    Вынесено из чтения файлов, чтобы fail-closed доказывался на синтетике, а не только
    на реальном дереве (AGENTS.md: три теста на capability)."""
    findings = []
    for tool, raw, source, is_exact_pin in observed:
        if tool not in floors:
            continue
        floor, floor_raw = floors[tool]
        obs = _ver(raw)
        if not obs:
            continue
        if tool in EXACT:
            # Находко-чувствительный: РОВНО пол pyproject во всех объявлениях.
            if obs != floor:
                findings.append(
                    f"{tool}: {source} объявляет {raw}, а единый источник (pyproject "
                    f"`{floor_raw}`) — {'.'.join(map(str, floor))}; для {tool} версия обязана "
                    f"совпадать точно (находки зависят от версии)")
        else:
            # Серийный: мажор обязан совпасть; зафиксированное — не ниже пола.
            if obs[0] != floor[0]:
                findings.append(
                    f"{tool}: {source} объявляет мажор {obs[0]} (из {raw}), а единый источник "
                    f"(pyproject `{floor_raw}`) — мажор {floor[0]}")
            elif is_exact_pin and len(obs) >= len(floor) and obs < floor:
                findings.append(
                    f"{tool}: {source} фиксирует {raw} ниже пола pyproject `{floor_raw}`")
    return findings


@pytest.mark.contract
def test_aligned_tool_versions_have_single_source():
    """Positive: реальное дерево согласовано с единым источником."""
    floors = _floors_from_pyproject()
    # Все выравниваемые инструменты обязаны иметь пол в едином источнике.
    missing = sorted(ALIGNED - set(floors))
    assert not missing, (
        "нет пола в pyproject (единый источник) для: " + ", ".join(missing))

    findings = check(floors, _observed())
    assert not findings, (
        "версии инструментов разошлись с единым источником (pyproject.toml):\n  - "
        + "\n  - ".join(findings))


@pytest.mark.contract
def test_real_tree_declares_each_tool_somewhere():
    """Side-effect proof: сверка видит РЕАЛЬНЫЕ объявления, а не пустоту (иначе зелень бессмысленна).
    Каждый выравниваемый инструмент встречается хотя бы в одном не-pyproject источнике."""
    declared = {tool for tool, *_ in _observed()}
    missing = sorted(ALIGNED - declared)
    assert not missing, (
        "сверять нечего — инструмент не объявлен нигде, кроме pyproject: " + ", ".join(missing))


@pytest.mark.contract
def test_drift_is_caught_fail_closed():
    """Fail-closed: расхождение любого класса даёт находку."""
    floors = {
        "ruff": ((0, 17, 3), "ruff>=0.17.3"),
        "pytest": ((9, 0), "pytest>=9.0"),
    }
    # ruff (exact): иная патч-версия в CI -> находка.
    assert check(floors, [("ruff", "0.17.2", ".github/workflows/x.yml", True)])
    # ruff (exact): иной rev в pre-commit -> находка.
    assert check(floors, [("ruff", "v0.18.0", ".pre-commit-config.yaml", True)])
    # pytest (series): иной мажор -> находка.
    assert check(floors, [("pytest", "8.0", "requirements-dev.txt", False)])
    # pytest (series): зафиксировано ниже пола того же мажора -> находка.
    assert check({"pytest": ((9, 2), "pytest>=9.2")},
                 [("pytest", "9.1.0", "uv.lock", True)])
    # Согласованное -> находок нет.
    assert check(floors, [
        ("ruff", "0.17.3", ".pre-commit-config.yaml", True),
        ("pytest", "9.2.0", "uv.lock", True),
        ("pytest", "9.*", ".github/workflows/x.yml", True),
    ]) == []
