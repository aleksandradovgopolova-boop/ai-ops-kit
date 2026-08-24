"""Поставляемый модуль обязан быть ДОСТИЖИМ из точки входа — иначе он едет мёртвым грузом.

ПОВОД — АУДИТ (24.08.2026). Существующий `test_unwired_modules` ловит модули, ОБЪЯВЛЕННЫЕ
неподключёнными (исключённые из поставки), и проверяет, что их правда никто не зовёт. Но он считает
подключением ЛЮБОЕ упоминание — в том числе импорт соседним модулем и строку в footprint-леджере
`quality/delivery-budget.yaml`. Поэтому он слеп к МЁРТВОМУ ОСТРОВУ: группе модулей, которые
импортируют друг друга, но до которой не доходит ни одна настоящая точка входа. Аудит нашёл ровно
такой остров — продуктовые операции Фазы 4 (health-полосы, risk_register, team_sync, decision_log,
human_override, policy_engine, drift_artifacts): написаны, протестированы, ЕДУТ в дочку — и не
вызываются ниоткуда, кроме тестов и друг друга.

Этот тест закрывает разрыв ДОСТИЖИМОСТЬЮ. Точка входа — это то, что вызывает модуль ИЗВНЕ графа
импортов пакета:
  * CLI (`ai_ops_kit.cli.ai_ops_cli`) и движок прогона (`ai_ops_kit.engine.ai_ops_run`);
  * установщик (`installer/ai_ops.py`) и то, что он импортирует;
  * валидаторы (`ai_ops_kit/validation/*` — гейты зовут их процессом);
  * команды рантайма и Robin (`commands/**`, `runtime/**`, `workflows/**`), называющие модуль;
  * процессный шим `tools/<name>.py` (модуль вызывается как инструмент).
Достижимое = транзитивное замыкание импортов от этих корней. Поставляемый модуль вне замыкания и
вне списков-исключений — МЁРТВ.

РАТЧЕТ, как `known_violations` в layering и как `UNWIRED_MODULES`: список известного-мёртвого вправе
только СОКРАЩАТЬСЯ. Подключили модуль (интентом, командой, шимом) — он ушёл из замыкания-исключения
сам; убрали из поставки — переехал в `UNWIRED_MODULES`. Новый мёртвый модуль в поставке — красное.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше

PKG = "ai_ops_kit"

# Известный мёртвый остров — заморожен фактом (аудит 24.08.2026). Каждая строка вправе только УЙТИ:
# либо модуль подключают точкой входа, либо переносят в installer.UNWIRED_MODULES (перестаёт ехать).
# Пока имя здесь — это признанный долг «едет, но недостижимо», а не разрешение плодить такие модули.
KNOWN_UNREACHABLE = frozenset({
    # Продуктовые операции Фазы 4: агрегаторы здоровья/рисков/синка. Импортируют только друг друга;
    # ни CLI-интента, ни процессного шима, ни вызова из рантайма. Подключение — работа проводки
    # (реестр интентов уже готов: добавить обработчик дёшево).
    # 2026-08-25 (Product Contract, живой health): `health_common` и `health_product` СНЯТЫ с острова —
    # интент `contract`/`products` считает product-health и впрыскивает его в контракт, поэтому оба
    # теперь достижимы из CLI. Список сократился фактом проводки, а не решением (ратчет только вниз).
    # 2026-08-25 (Product Contract, полное здоровье): `health_tech` и `health_delivery` СНЯТЫ с
    # острова — контракт впрыскивает здоровье product+tech+delivery (три измерения одним rollup'ом),
    # поэтому оба достижимы из CLI. Остаются risk_register/team_sync/drift и governance.
    "ai_ops_kit/intelligence/risk_register.py",
    "ai_ops_kit/intelligence/team_sync.py",
    "ai_ops_kit/intelligence/drift_artifacts.py",
    # Governance Фазы 4: политика/журнал/override. policy_engine.enforce() ничего не принуждает,
    # decision_log никогда не пишет — потому что их никто не зовёт. Лист-пакет, импортируют друг друга.
    "ai_ops_kit/governance/policy_engine.py",
    "ai_ops_kit/governance/decision_log.py",
    "ai_ops_kit/governance/human_override.py",
})

# Каталоги РАНТАЙМ-диспетча (не проза-доки и не footprint-леджер quality/delivery-budget.yaml):
# упоминание basename модуля здесь означает «дочка позовёт его по этому имени».
RUNTIME_WIRING_DIRS = ("commands", "runtime", "workflows")


def _dotted(p: Path) -> str:
    return ".".join(p.relative_to(PKG_ROOT).with_suffix("").parts)


def _pkg_modules() -> dict[str, Path]:
    return {_dotted(p): p for p in (PKG_ROOT / PKG).rglob("*.py")
            if "__pycache__" not in p.parts and p.name != "__init__.py"}


def _imports_in(path: Path, known: set[str]) -> set[str]:
    """ai_ops_kit-модули, импортируемые файлом (включая функционально-локальные импорты)."""
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(PKG):
            if n.module in known:
                out.add(n.module)
            for alias in n.names:
                cand = f"{n.module}.{alias.name}"
                if cand in known:
                    out.add(cand)
        elif isinstance(n, ast.Import):
            for alias in n.names:
                if alias.name in known:
                    out.add(alias.name)
    return out


def _reachable(modules: dict[str, Path]) -> set[str]:
    known = set(modules)
    by_basename: dict[str, list[str]] = {}
    for m in known:
        by_basename.setdefault(m.rsplit(".", 1)[-1], []).append(m)
    edges = {m: _imports_in(p, known) for m, p in modules.items()}

    roots: set[str] = set()
    for hard in (f"{PKG}.cli.ai_ops_cli", f"{PKG}.engine.ai_ops_run"):
        if hard in known:
            roots.add(hard)
    roots |= {m for m in known if m.startswith(f"{PKG}.validation.")}
    roots |= _imports_in(PKG_ROOT / "installer" / "ai_ops.py", known)
    # процессные шимы tools/<name>.py — модуль вызывается как инструмент
    for shim in (PKG_ROOT / "tools").glob("*.py"):
        roots |= set(by_basename.get(shim.stem, []))
    # упоминания basename в поверхностях рантайм-диспетча
    blob_parts: list[str] = []
    for d in RUNTIME_WIRING_DIRS:
        base = PKG_ROOT / d
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".yaml", ".yml") and "__pycache__" not in p.parts:
                    try:
                        blob_parts.append(p.read_text(encoding="utf-8", errors="ignore"))
                    except OSError:
                        pass
    blob = "\n".join(blob_parts)
    for bn, mods in by_basename.items():
        if re.search(rf"\b{re.escape(bn)}\b", blob):
            roots |= set(mods)

    live: set[str] = set()
    stack = list(roots & known)
    while stack:
        m = stack.pop()
        if m in live:
            continue
        live.add(m)
        stack.extend(edges.get(m, ()))
    return live


def _dead_shipped(modules: dict[str, Path], live: set[str]) -> set[str]:
    """Поставляемые модули пакета, недостижимые из точек входа, не dev-only и не в UNWIRED_MODULES."""
    unwired = {_dotted(PKG_ROOT / r) for r in installer.UNWIRED_MODULES}
    dead = set()
    for m, p in modules.items():
        rel = str(p.relative_to(PKG_ROOT))
        if m in live:
            continue
        if m.rsplit(".", 1)[-1] in installer.DEV_ONLY_TOOLS:
            continue
        if m in unwired:
            continue
        if not installer.is_runtime_asset(rel):
            continue
        dead.add(rel)
    return dead


@pytest.mark.contract
def test_no_new_unreachable_shipped_module():
    """Поставляемый модуль вне замыкания достижимости обязан быть признан (KNOWN_UNREACHABLE)."""
    modules = _pkg_modules()
    dead = _dead_shipped(modules, _reachable(modules))
    new_dead = dead - KNOWN_UNREACHABLE
    assert not new_dead, (
        "поставляемые модули недостижимы ни из одной точки входа (CLI/движок/установщик/валидатор/"
        "команда рантайма/tools-шим) — они поедут в дочку мёртвым грузом:\n  "
        + "\n  ".join(sorted(new_dead))
        + "\nПодключите (обработчик команды дёшев — есть реестр _INTENT_HANDLERS), либо перенесите "
          "в installer.UNWIRED_MODULES (перестанет ехать), либо, если это признанный долг, "
          "добавьте в KNOWN_UNREACHABLE с причиной.")


@pytest.mark.contract
def test_known_unreachable_list_only_shrinks():
    """Ратчет: имя в KNOWN_UNREACHABLE обязано (а) существовать и (б) всё ещё быть недостижимым."""
    modules = _pkg_modules()
    dead = _dead_shipped(modules, _reachable(modules))
    missing = [r for r in sorted(KNOWN_UNREACHABLE) if not (PKG_ROOT / r).is_file()]
    assert not missing, (
        "в KNOWN_UNREACHABLE перечислены файлы, которых нет — список стал кладбищем:\n  "
        + "\n  ".join(missing))
    resurrected = [r for r in sorted(KNOWN_UNREACHABLE) if r not in dead]
    assert not resurrected, (
        "эти модули БОЛЬШЕ не мертвы — их подключили или убрали из поставки. Уберите их из "
        "KNOWN_UNREACHABLE, иначе список перестаёт что-либо значить:\n  " + "\n  ".join(resurrected))


@pytest.mark.contract
def test_the_guard_detects_the_island_it_was_written_for():
    """Охрана обязана ВИДЕТЬ мёртвый остров: без списка-исключения он попал бы в мёртвые."""
    modules = _pkg_modules()
    dead = _dead_shipped(modules, _reachable(modules))
    # каждый объявленный член острова действительно вычисляется как недостижимый
    not_detected = KNOWN_UNREACHABLE - dead
    assert not not_detected, (
        f"детектор ослеп на признанном острове (значит и новый мёртвый модуль пропустит): "
        f"{sorted(not_detected)}")
