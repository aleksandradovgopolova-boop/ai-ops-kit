#!/usr/bin/env python3
"""Реконсиляция статей Архитектурной конституции с РЕАЛЬНЫМИ гейтами (#824).

ЗАЧЕМ. `standards/architecture/rules.yaml` объявляет у каждой статьи `gate` и `enforced_in`
(parent/child/both/none/meta). Это ОБЕЩАНИЕ. Здесь оно сверяется с реальностью: существует ли
backing-проверка и правда ли она доходит до дочки — по тому же источнику, что и доставка
(`installer.RUNTIME_VALIDATORS`/`is_runtime_asset`). Иначе «правило без гейта — пожелание»
(HON-001), а parent-only-гейт, выданный за защиту дочки, — ложная зрелость (HON-003).

Ничего своего не хранит — читает реестр конституции и код. Витрина read-only, как
`capability_inventory`. Генерирует `standards/architecture/gate-reconciliation.md`; свежесть держит
`tests/unit/test_architecture_gate_reconciliation.py` (поведенческий — импортирует и зовёт этот
модуль).

ЗАПУСК: python3 -m ai_ops_kit.devtools.arch_gate_reconciliation [--write]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]
RULES_YAML = KIT / "standards" / "architecture" / "rules.yaml"
OUT_MD = KIT / "standards" / "architecture" / "gate-reconciliation.md"

# Специальные backing'и, не разрешаемые как файл-одноимёнец гейта.
_SPECIAL_BACKING = {
    "required_repo_artifacts": "ai_ops_kit/planning/standard.py",
}

_ENF_LABEL = {
    "parent": "только CI кита",
    "child": "едет в дочку",
    "both": "и кит, и дочка",
    "none": "гейта нет (долг)",
    "meta": "само-правило",
}


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "installer_ai_ops_for_reconciliation", KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_rules():
    return yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))["rules"]


def resolve_backing(gate: str) -> tuple[str | None, str]:
    """gate id -> (relative-path-or-None, kind). kind ∈ validator|runtime|contract-test|special|none|meta."""
    if gate == "meta":
        return None, "meta"
    if gate == "none":
        return None, "none"
    if gate in _SPECIAL_BACKING:
        return _SPECIAL_BACKING[gate], "special"
    for rel, kind in (
        (f"ai_ops_kit/validation/{gate}.py", "validator"),
        (f"ai_ops_kit/engine/{gate}.py", "runtime"),
        (f"tests/contracts/{gate}.py", "contract-test"),
    ):
        if (KIT / rel).is_file():
            return rel, kind
    return None, "unresolved"


def ships_to_child(gate: str, rel: str | None, kind: str, installer) -> bool:
    """Доходит ли backing до дочки — по тому же критерию, что и доставка."""
    if kind in ("meta", "none", "unresolved"):
        return False
    if kind == "contract-test":
        return False  # tests/ не входят в managed_set
    if kind == "validator":
        # для валидаторов доставка ограничена белым списком RUNTIME_VALIDATORS
        return gate in installer.RUNTIME_VALIDATORS
    # runtime/special: обычный модуль пакета — доходит, если is_runtime_asset его пропускает
    return bool(rel and installer.is_runtime_asset(rel))


def reconcile() -> list[dict]:
    installer = _load_installer()
    rows = []
    for r in load_rules():
        gate = r["gate"]
        rel, kind = resolve_backing(gate)
        child = ships_to_child(gate, rel, kind, installer)
        declared = r["enforced_in"]
        # ОЖИДАНИЕ честности: объявленное Исполнение согласовано с реальной доставкой.
        if declared in ("child", "both"):
            honest = child                      # обещали дочке — обязано доходить
        elif declared == "parent":
            honest = (kind != "none") and not child  # есть гейт, но в дочку НЕ едет
        elif declared == "none":
            honest = (gate == "none")
        elif declared == "meta":
            honest = (gate == "meta")
        else:
            honest = False
        rows.append({
            "id": r["id"], "title": r["title"], "part": r["part"],
            "gate": gate, "enforced_in": declared,
            "backing": rel or "—", "kind": kind,
            "reaches_child": child, "honest": honest,
        })
    return rows


def dishonest_rows() -> list[dict]:
    return [row for row in reconcile() if not row["honest"]]


def render_markdown() -> str:
    rows = reconcile()
    out = [
        "# Реконсиляция гейтов Архитектурной конституции",
        "",
        "> Генерируется `ai_ops_kit/devtools/arch_gate_reconciliation.py`. Не редактировать вручную.",
        "> Сверяет обещание статьи (`gate`, `enforced_in` из `rules.yaml`) с реальностью: существует ли",
        "> backing-проверка и доходит ли она до дочки — по тому же источнику, что и доставка",
        "> (`installer.RUNTIME_VALIDATORS`/`is_runtime_asset`).",
        "",
        "Колонка **«в дочке?»** — ключевая честность: `validate_layering`/`validate_func_size` и",
        "контракты dormant/reachability гоняются **только в CI кита**; в дочку из структурного едут",
        "`validate_module_size` и `validate_test_taxonomy` + рантайм `reviewer_handoff`. Статьи с",
        "`gate: none` — честный долг (#827), а не защита.",
        "",
        "| ID | Статья | Гейт | Исполнение | Backing | В дочке? |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        child = "да" if r["reaches_child"] else ("—" if r["gate"] in ("none", "meta") else "нет")
        gate = "—" if r["gate"] == "none" else f"`{r['gate']}`"
        out.append(
            f"| {r['id']} | {r['title']} | {gate} | {r['enforced_in']} "
            f"({_ENF_LABEL[r['enforced_in']]}) | {r['backing']} | {child} |"
        )
    out.append("")
    gated = sum(1 for r in rows if r["gate"] not in ("none", "meta"))
    child_n = sum(1 for r in rows if r["reaches_child"])
    debt = sum(1 for r in rows if r["gate"] == "none")
    out.append(
        f"_Итог: {len(rows)} статей — {gated} с гейтом ({child_n} доходят до дочки), "
        f"{debt} честный долг (#827)._"
    )
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    md = render_markdown()
    bad = dishonest_rows()
    if "--write" in argv:
        OUT_MD.write_text(md, encoding="utf-8")
        print(f"OK: записан {OUT_MD.relative_to(KIT)} ({len(load_rules())} статей)")
    else:
        sys.stdout.write(md)
    if bad:
        sys.stderr.write("\nНЕЧЕСТНЫЕ строки (обещание ≠ реальность):\n")
        for r in bad:
            sys.stderr.write(f"  {r['id']}: gate={r['gate']} enforced_in={r['enforced_in']} "
                             f"kind={r['kind']} reaches_child={r['reaches_child']}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
