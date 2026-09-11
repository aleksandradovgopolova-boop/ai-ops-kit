#!/usr/bin/env python3
"""Витрина возможностей: «что кит умеет СЕГОДНЯ» — built / built≠wired / partial / planned.

ПОВОД (#569). Два независимых ревью подряд (внешнее ~06.09.2026 и независимое 07.09.2026)
переоценили ОТСУТСТВИЕ: помечали как «дыры» то, что уже построено (`ai-ops explain`, скоринг
`next`, проекция `work`, outcome-аналитика, git-носитель координации). Если два внешних читателя
подряд не видят актуального содержания продукта — это дефект ОБНАРУЖИМОСТИ, а не ревьюеров. Разрыв
между реальным состоянием кода и тем, что о продукте можно ПРОЧИТАТЬ, дорого стоит: чужие ревью,
онбординг дочек и собственное планирование стартуют с неверной карты.

ЧТО ЭТО. Единая карта возможностей, у каждой — состояние и способ проверки. Значения НЕ пишутся
руками: они ВЫВЕДЕНЫ из реестров и кода при каждом запуске, поэтому не могут молча разойтись с
реальностью. Ключевое различие, на котором ревью и ошибаются, — честный раздел built≠wired:
модуль НАПИСАН и протестирован, но ни один рабочий путь его не зовёт (0 не-тестовых импортёров).

ИСТОЧНИКИ ПРАВДЫ (ничего здесь не хранится своего — только чтение):
  * команды владельца     — `INTENTS`/`DIRECT_INTENTS` в `ai_ops_kit/cli/ai_ops_cli.py` (AST, без
                            импорта: cli никто не импортирует — layering);
  * quality gates         — `quality/gates.yaml` (blocking → enforced, advisory → partial);
  * роли                  — `registry/agents.yaml`;
  * built≠wired модули    — вычисляются ТЕМ ЖЕ сигналом, что `tests/contracts/test_dormant_inventory.py`
                            (0 не-тестовых импортёров, не легит-вход): их набор — честный раздел
                            «построено, но не проведено в контур»;
  * planned/unsupported   — `registry/capability-index.yaml` (status: unsupported + fallback).

СВЕЖЕСТЬ. `tests/contracts/test_capability_inventory.py` сверяет раздел built≠wired этой витрины с
живым сигналом dormant-inventory: появилась built-but-unwired возможность, не отражённая честно —
тест краснеет. Витрина read-only: генератор ЧИТАЕТ реестры и код, не пишет в них.

ЗАПУСК:
  python3 -m ai_ops_kit.devtools.capability_inventory            — markdown в stdout
  python3 -m ai_ops_kit.devtools.capability_inventory --json     — та же карта как JSON
  python3 -m ai_ops_kit.devtools.capability_inventory --write    — записать docs/capability-map.md
  python3 -m ai_ops_kit.devtools.capability_inventory --check    — код 1, если docs/capability-map.md устарел

Только stdlib + pyyaml. Инструмент разработки самого кита (devtools): в дочку не едет.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import date
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
PKG_NAME = "ai_ops_kit"
PAGE_REL = "docs/capability-map.md"

# Пять состояний витрины (единый словарь; каждое выводится из данных, не проставляется рукой).
STATE_BUILT = "built"                 # проведено в контур: команда/гейт/роль в рабочем пути
STATE_UNWIRED = "built-not-wired"     # написано и протестировано, но 0 не-тестовых импортёров
STATE_PARTIAL = "partial"             # механизм есть, но advisory/не в обязательном контуре
STATE_PLANNED = "planned"             # объявлено unsupported + fallback (честный план)

STATE_LABEL = {
    STATE_BUILT: "built (проведено в контур)",
    STATE_UNWIRED: "built≠wired (построено, но не проведено)",
    STATE_PARTIAL: "partial (advisory / вне обязательного контура)",
    STATE_PLANNED: "planned (unsupported + fallback)",
}

# ── built≠wired: тот же сигнал, что tests/contracts/test_dormant_inventory.py ────────────────────
# Константы держатся в согласии с тестом; расхождение краснеет в test_capability_inventory.py
# (сверка раздела built≠wired витрины с живым `_dormant_now()`). Легитимные 0-импортёрные входы
# (валидаторы, dev-харнессы, диспетчируемые CLI-main) НЕ дормантны — их запускают процессом.
ALLOWLIST_PREFIXES: tuple[str, ...] = (
    f"{PKG_NAME}.validation.",
    f"{PKG_NAME}.devtools.",
)
ALLOWLIST_MODULES: frozenset[str] = frozenset({
    f"{PKG_NAME}.intelligence.nightly_review",
    f"{PKG_NAME}.lifecycle.merge_memory",
    # Точка входа `ai-ops` (pyproject.toml -> [project.scripts]): console_scripts запускает
    # процессом (pip/pipx), а не импортом — нулевой импортер здесь норма по устройству.
    f"{PKG_NAME}.cli.entry",
    # git merge-driver для plan.yaml: git запускает его ПРОЦЕССОМ по `merge.ai-ops-plan.driver`
    # (как console_scripts), а не импортом — нулевой импортер норма по устройству.
    f"{PKG_NAME}.planning.plan_merge_driver",
    # Ре-экспорт-шим (K5, 2026-09-10): маршрутизатор переехал в shared/ai_route; старый путь оставлен
    # для кросс-версионного импорта `from ai_ops_kit.engine import ai_route` (smoke-валидатор прежнего
    # тега при апдейте дочки). 0 импортёров внутри кита — норма: рантайм зовёт shared напрямую.
    f"{PKG_NAME}.engine.ai_route",
})
SKIP_DIRS = frozenset({
    ".git", ".ai", ".claude", ".venv", "venv", "env", "node_modules",
    "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", "__pycache__", "site-packages",
})


def _dotted(p: Path) -> str:
    return ".".join(p.relative_to(PKG).with_suffix("").parts)


def _pkg_modules() -> dict[str, Path]:
    return {_dotted(p): p for p in (PKG / PKG_NAME).rglob("*.py")
            if "__pycache__" not in p.parts and p.name != "__init__.py"}


def _is_test_path(p: Path) -> bool:
    return "tests" in p.parts or p.name.startswith("test_") or p.name == "conftest.py"


def _is_skipped(p: Path, root: Path = PKG) -> bool:
    try:
        parts = set(p.relative_to(root).parts)
    except ValueError:
        parts = set(p.parts)
    return bool(SKIP_DIRS & parts)


def _imports_in(path: Path, known: set[str]) -> set[str]:
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(PKG_NAME):
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


def _nontest_importers(modules: dict[str, Path]) -> dict[str, set[str]]:
    known = set(modules)
    importers: dict[str, set[str]] = {m: set() for m in modules}
    pkg_dir = PKG / PKG_NAME
    for p in PKG.rglob("*.py"):
        if _is_skipped(p) or _is_test_path(p):
            continue
        src = _dotted(p) if p.is_relative_to(pkg_dir) else str(p.relative_to(PKG))
        for imp in _imports_in(p, known):
            if imp != src:
                importers[imp].add(src)
    return importers


def dormant_modules() -> list[str]:
    """Генуинно built≠wired модули на текущем дереве: 0 не-тестовых импортёров, не легит-вход."""
    modules = _pkg_modules()
    importers = _nontest_importers(modules)
    zero = {m for m in modules if not importers[m]}
    return sorted(m for m in zero
                  if not m.startswith(ALLOWLIST_PREFIXES) and m not in ALLOWLIST_MODULES)


# ── команды владельца: INTENTS/DIRECT_INTENTS из cli (AST, без импорта) ──────────────────────────
# Точка входа `cli` по layering не импортируется НИКЕМ; чтобы прочитать её объявления, разбираем
# исходник, а не импортируем модуль. Так значения остаются ВЫВЕДЕННЫМИ из кода.
_PIPELINE_INTENTS = ("specify", "run", "do", "resume")   # исполняются движком, не DIRECT-диспетчем


def _cli_source() -> str:
    return (PKG / PKG_NAME / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")


def _cli_assign(name: str):
    tree = ast.parse(_cli_source())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} не найдено в ai_ops_cli.py")


def commands() -> list[dict]:
    intents = _cli_assign("INTENTS")            # {id: (описание, workflow, needs_task)}
    direct = set(_cli_assign("DIRECT_INTENTS"))
    out = []
    for cid in sorted(intents):
        desc = intents[cid][0] if isinstance(intents[cid], (list, tuple)) else str(intents[cid])
        if cid in direct:
            dispatch = "direct"
        elif cid in _PIPELINE_INTENTS:
            dispatch = "engine"
        else:
            dispatch = "preview"
        out.append({
            "id": cid,
            "summary": " ".join(desc.split()),
            "dispatch": dispatch,
            "state": STATE_BUILT,
            "verify": f"./ai-ops {cid} · tests/contracts/test_direct_intents_match_handler.py",
        })
    return out


# ── quality gates: blocking → enforced, advisory → partial ───────────────────────────────────────
def gates() -> list[dict]:
    data = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")) or {}
    out = []
    for gid, g in sorted((data.get("gates") or {}).items()):
        blocking = bool(g.get("blocking"))
        out.append({
            "id": gid,
            "summary": " ".join(str(g.get("purpose") or "").split())[:200],
            "stage": g.get("stage"),
            "validator": g.get("validator"),
            "state": STATE_BUILT if blocking else STATE_PARTIAL,
            "verify": f"quality/gates.yaml → {gid} · {g.get('validator') or 'gate'}",
        })
    return out


# ── роли ─────────────────────────────────────────────────────────────────────────────────────────
def roles() -> list[dict]:
    data = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8")) or {}
    out = []
    for a in data.get("agents") or []:
        out.append({
            "id": a.get("id"),
            "domain": a.get("domain"),
            "review_mode": a.get("review_mode"),
            "state": STATE_BUILT,
        })
    return sorted(out, key=lambda r: (str(r["domain"]), str(r["id"])))


# ── planned / unsupported из capability-index ─────────────────────────────────────────────────────
def planned() -> list[dict]:
    p = PKG / "registry" / "capability-index.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for e in data.get("entries") or []:
        if e.get("status") == "unsupported":
            out.append({
                "entity": f"{e.get('entity_kind')}:{e.get('entity_id')}",
                "capability": e.get("capability"),
                "fallback": e.get("fallback"),
                "state": STATE_PLANNED,
                "verify": "registry/capability-index.yaml",
            })
    return sorted(out, key=lambda r: (str(r["entity"]), str(r["capability"])))


def build_inventory() -> dict:
    dm = dormant_modules()
    cmds = commands()
    gs = gates()
    rs = roles()
    pl = planned()
    counts = {
        "commands": len(cmds),
        "gates_total": len(gs),
        "gates_enforced": sum(1 for g in gs if g["state"] == STATE_BUILT),
        "gates_advisory": sum(1 for g in gs if g["state"] == STATE_PARTIAL),
        "roles": len(rs),
        "built_not_wired": len(dm),
        "planned_unsupported": len(pl),
    }
    return {
        "commands": cmds,
        "gates": gs,
        "roles": rs,
        "built_not_wired": dm,
        "planned": pl,
        "counts": counts,
    }


# ── рендер markdown (детерминированный порядок — чтобы diff краснел только по сути) ───────────────
_HEADER = f"""<!-- СГЕНЕРИРОВАНО: {PKG_NAME}.devtools.capability_inventory. РУКАМИ НЕ ПРАВИТЬ. -->
<!-- Перегенерировать: python3 -m {PKG_NAME}.devtools.capability_inventory --write -->

# Карта возможностей — что кит умеет сегодня

Одна достоверная витрина «что продукт умеет прямо сейчас». Значения **выведены из реестров и
кода** при генерации, а не написаны руками, поэтому не расходятся с реальностью молча. Витрина
read-only: генератор только читает.

Состояния честно различают **built** и **built≠wired** — именно на этом шве ревью ошибается,
принимая построенное за отсутствующее (или наоборот — недоведённое за готовое):

- **built** — проведено в контур: команда/гейт/роль в рабочем пути;
- **built≠wired** — написано и протестировано, но ни один рабочий путь не зовёт (0 не-тестовых
  импортёров); тот же сигнал держит `tests/contracts/test_dormant_inventory.py`;
- **partial** — механизм есть, но advisory или вне обязательного контура;
- **planned** — объявлено `unsupported` + fallback (честный план, не дыра).

Как проверить каждое — в колонке «проверить». Источник «что умеем сегодня» — эта карта; ROADMAP и
README ссылаются на неё, а не дублируют список руками.
"""


def render_markdown(inv: dict | None = None) -> str:
    inv = inv or build_inventory()
    c = inv["counts"]
    lines = [_HEADER, "## Сводка", ""]
    lines += [
        f"| Категория | Сколько |",
        f"|---|---|",
        f"| Команды владельца (`./ai-ops …`) | {c['commands']} |",
        f"| Quality gates — всего | {c['gates_total']} |",
        f"| — из них enforced (blocking) | {c['gates_enforced']} |",
        f"| — из них advisory (partial) | {c['gates_advisory']} |",
        f"| Роли в реестре | {c['roles']} |",
        f"| **built≠wired модулей** | **{c['built_not_wired']}** |",
        f"| planned / unsupported | {c['planned_unsupported']} |",
        "",
    ]

    # Самое важное для ревьюера — раздел built≠wired первым.
    lines += ["## built≠wired — построено, но не проведено в контур", ""]
    if inv["built_not_wired"]:
        lines += [
            "Модули НАПИСАНЫ и протестированы, но их не зовёт ни один не-тестовый путь (0 импортёров).",
            "Это НЕ приговор: не хватает проводки — интента, гейта или записи в реестре. Набор",
            "заморожен потолком-ратчетом; провели в контур — модуль обязан уйти из списка.",
            "Проверить: `tests/contracts/test_dormant_inventory.py` (`KNOWN_DORMANT`).",
            "",
            "| Модуль | Состояние | Проверить |",
            "|---|---|---|",
        ]
        for m in inv["built_not_wired"]:
            rel = m.replace(".", "/") + ".py"
            lines.append(f"| `{rel}` | built≠wired | 0 не-тестовых импортёров; "
                         f"`tests/contracts/test_dormant_inventory.py` |")
        lines.append("")
    else:
        lines += ["Пусто: каждый модуль пакета проведён в контур или объявлен легит-входом.", ""]

    # Команды.
    lines += ["## Команды владельца", "",
              "Все интенты диспетчируются (`direct` — прямой обработчик, `engine` — движок задачи, "
              "`preview` — превью); соответствие «интент → обработчик» держит "
              "`tests/contracts/test_direct_intents_match_handler.py`.", "",
              "| Команда | Что делает | Диспетч | Состояние |", "|---|---|---|---|"]
    for cmd in inv["commands"]:
        lines.append(f"| `./ai-ops {cmd['id']}` | {cmd['summary']} | {cmd['dispatch']} | built |")
    lines.append("")

    # Гейты.
    lines += ["## Quality gates", "",
              "`blocking` гейт — enforced (built); `advisory` — partial (механизм есть, не блокирует). "
              "Каждый возвращает machine-readable результат; проверить — `quality/gates.yaml` и его "
              "`validator`.", "",
              "| Gate | Стадия | Состояние | Назначение |", "|---|---|---|---|"]
    for g in inv["gates"]:
        st = "built (enforced)" if g["state"] == STATE_BUILT else "partial (advisory)"
        lines.append(f"| `{g['id']}` | {g['stage']} | {st} | {g['summary']} |")
    lines.append("")

    # Роли (сводно по доменам, чтобы не раздувать).
    lines += ["## Роли", "",
              f"{inv['counts']['roles']} ролей объявлено в `registry/agents.yaml` (контракты владения "
              "и ревью). По домену:", ""]
    by_domain: dict[str, list[str]] = {}
    for r in inv["roles"]:
        by_domain.setdefault(str(r["domain"]), []).append(str(r["id"]))
    lines += ["| Домен | Роли |", "|---|---|"]
    for dom in sorted(by_domain):
        lines.append(f"| {dom} | {', '.join(sorted(by_domain[dom]))} |")
    lines.append("")

    # Planned.
    lines += ["## planned / unsupported", "",
              "Объявлено `unsupported` с fallback в `registry/capability-index.yaml` — честный план, "
              "не дыра.", ""]
    if inv["planned"]:
        lines += ["| Возможность | Сущность | Fallback |", "|---|---|---|"]
        for p in inv["planned"]:
            lines.append(f"| {p['capability']} | {p['entity']} | {p['fallback'] or '—'} |")
    else:
        lines.append("Пусто.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Витрина возможностей кита (built≠wired честно).")
    ap.add_argument("--json", action="store_true", help="вывести карту как JSON")
    ap.add_argument("--write", action="store_true", help=f"записать {PAGE_REL}")
    ap.add_argument("--check", action="store_true",
                    help=f"код 1, если {PAGE_REL} расходится со сгенерированным")
    a = ap.parse_args(argv)
    inv = build_inventory()
    if a.json:
        print(json.dumps(inv, ensure_ascii=False, indent=2))
        return 0
    md = render_markdown(inv)
    page = PKG / PAGE_REL
    if a.check:
        current = page.read_text(encoding="utf-8") if page.is_file() else ""
        if current != md:
            print(f"{PAGE_REL} устарел — перегенерировать: "
                  f"python3 -m {PKG_NAME}.devtools.capability_inventory --write", file=sys.stderr)
            return 1
        print(f"{PAGE_REL} свежий.")
        return 0
    if a.write:
        page.write_text(md, encoding="utf-8")
        print(f"записано: {PAGE_REL} ({len(md)} байт, {date.today().isoformat()})")
        return 0
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
