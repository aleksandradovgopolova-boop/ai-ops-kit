#!/usr/bin/env python3
"""Advisory-гейт объёма ДОСТАВЛЯЕМОГО итога слияния — merge-preview ∩ managed_set (фордж-нейтрально).

Follow-up к фордж-нейтральному пивоту. `ai_ops_kit/gates/merge_preview.py` меряет ВЕСЬ итог слияния
(base+head без коммита, через `git merge-tree --write-tree`) против потолка volume_bytes — это надёжный
СИГНАЛ дрейфа, но надмножество доставляемого: он считает любой файл дерева-итога, включая dev-ассеты
кита. Дочку же волнует не любой файл итога, а тот, что к ней РЕАЛЬНО поедет.

ЧТО ЗДЕСЬ. Объём именно ДОСТАВЛЯЕМОЙ части итога слияния: пересечение (файлы дерева-итога слияния) ∩
(installer.managed_set — управляемая поверхность дочки). Так измеряется то, что уедет в дочку из
РЕЗУЛЬТАТА слияния, а не из ветки PR в одиночку и не из всего дерева-итога.

ГДЕ ЖИВЁТ И ПОЧЕМУ. Оркестрация здесь, в installer/-слое, а НЕ в `ai_ops_kit/gates/`: gates не вправе
тянуть installer вверх (merge_preview.py об этом сказано прямо). installer — точка входа, которая
видит и git-примитив итога слияния (`gates.merge_preview`), и доставляемую поверхность
(`installer.managed_set`), и чистую логику пересечения/вердикта (`validation.delivery_footprint_warning`,
чистая — принимает и итог, и managed_set аргументами, поэтому не тянет никого вверх). validate_layering
сканирует только ai_ops_kit/, и ни одного нового ребра внутри пакета этот модуль не создаёт.

СТРОГОСТЬ. По умолчанию ADVISORY: всегда exit 0, PR не блокируется — механизм настоящий, но
промоутит его владелец отдельным решением (тот же принцип, что у merge_preview на пути PR). `--strict`
даёт ненулевой код при пробое доставляемого объёма ИЛИ если итог посчитать не удалось (fail-closed);
тонкий запас — мягкое предупреждение и в strict остаётся зелёным.

CLI:  python3 installer/delivered_merge_footprint.py --base origin/main --head HEAD [--root .] [--strict]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PKG = HERE.parents[1]                        # корень репозитория (kit root)
# PKG нужен для `ai_ops_kit.*`, HERE.parent (installer/) — для `import ai_ops` (сам инсталлятор).
for _p in (str(PKG), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai_ops_kit.gates import merge_preview                              # noqa: E402 — путь выше
from ai_ops_kit.validation import delivery_footprint_warning as dfw     # noqa: E402 — путь выше

DEFAULT_FRACTION = 0.10   # запасной порог предупреждения, если реестр его не назвал


def delivered_merge_footprint(root, base_ref: str, head_ref: str,
                              managed_rels, ceiling: int, fraction: float) -> dict:
    """Объём доставляемой части итога слияния base_ref+head_ref против потолка volume_bytes.

    Переиспользует примитив `merge_preview.merge_preview_tree` (итог слияния без коммита) и
    `merge_preview.merge_preview_entries` (файлы итога с размерами), ограничивает файлы до
    пересечения с `managed_rels` (доставляемая поверхность) и зовёт чистый вердикт из `validation`.

    -> {"ok": bool, "reason": str, "delivered_bytes": int|None, "delivered_files": int|None,
        "paths": [...], "ceiling": int, "fraction": float, "breached": bool, "thin": bool,
        "reserve": int|None}.

    FAIL-CLOSED: превью итога не удалось (конфликт/ошибка git/старый git) -> ok=False, breached=False
    (пробой доставляемого объёма НЕ утверждается, раз итог посчитать не смогли), reason назван.
    """
    preview = merge_preview.merge_preview_tree(root, base_ref, head_ref)
    if not preview.get("ok"):
        return {"ok": False, "reason": preview.get("reason", "merge-preview не удалось"),
                "delivered_bytes": None, "delivered_files": None, "paths": [],
                "ceiling": ceiling, "fraction": fraction,
                "breached": False, "thin": False, "reserve": None}
    entries = merge_preview.merge_preview_entries(root, preview["tree"])
    fp = dfw.delivered_merge_footprint(entries, managed_rels)
    verdict = dfw.delivered_footprint_verdict(fp["delivered_bytes"], ceiling, fraction)
    return {"ok": True, "reason": "",
            "delivered_bytes": fp["delivered_bytes"], "delivered_files": fp["delivered_files"],
            "paths": fp["paths"], "ceiling": ceiling, "fraction": fraction, **verdict}


def _load_managed_rels():
    """Доставляемая поверхность дочки как множество относительных путей (installer.managed_set)."""
    import ai_ops as installer     # noqa: E402 — installer/ добавлен в sys.path выше
    return {rel for _src, rel in installer.managed_set()}


def _load_budget():
    """(потолок volume_bytes, порог предупреждения) из quality/delivery-budget.yaml через installer."""
    import ai_ops as installer     # noqa: E402 — installer/ добавлен в sys.path выше
    doc = installer.delivery_budget() or {}
    ceiling = (doc.get("ceilings") or {}).get("volume_bytes")
    fraction = (doc.get("warnings") or {}).get("volume_reserve_fraction")
    return ceiling, fraction


def _format_line(res: dict, base_ref: str, head_ref: str) -> str:
    """Человекочитаемый вывод: число доставляемого объёма итога, вердикт и (при тонком запасе) разбор."""
    if not res["ok"]:
        return (f"DELIVERED-MERGE-FOOTPRINT: посчитать доставляемый итог слияния {base_ref}+{head_ref} "
                f"НЕ УДАЛОСЬ — {res['reason']}. Advisory: PR не блокируется, но зелёным это не считается.")
    dbytes, ceiling = res["delivered_bytes"], res["ceiling"]
    head = (f"DELIVERED-MERGE-FOOTPRINT ({base_ref}+{head_ref}): доставляемая часть итога слияния "
            f"{dbytes} Б в {res['delivered_files']} файлах, потолок {ceiling} Б, запас {res['reserve']} Б. "
            f"Меряется ПЕРЕСЕЧЕНИЕ дерева-итога с managed_set дочки — не вся ветка PR и не всё дерево.")
    if res["breached"]:
        return head + " ПРОБОЙ доставляемого объёма (advisory — промоутит владелец)."
    if res["thin"]:
        breakdown = ["Доставляемые файлы в итоге слияния (пути):"] + [f"    {p}" for p in res["paths"][:10]]
        return head + "\n" + dfw.thinning_reserve_warning(dbytes, ceiling, res["fraction"], breakdown)
    return head + " В пределах."


def main(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="delivered_merge_footprint.py",
        description="Advisory-гейт объёма доставляемого итога слияния (merge-preview ∩ managed_set).")
    ap.add_argument("--base", required=True, help="базовая ветка (например origin/main)")
    ap.add_argument("--head", default="HEAD", help="ветка PR (по умолчанию HEAD)")
    ap.add_argument("--root", default=".", help="корень репозитория (по умолчанию .)")
    ap.add_argument("--strict", action="store_true",
                    help="ненулевой код при пробое/непосчитанном итоге (по умолчанию advisory, exit 0)")
    args = ap.parse_args(argv)

    ceiling, fraction = _load_budget()
    if not isinstance(ceiling, int) or ceiling <= 0:
        print("DELIVERED-MERGE-FOOTPRINT: не прочитан потолок volume_bytes из "
              "quality/delivery-budget.yaml — advisory, пропуск.")
        return 1 if args.strict else 0
    fraction = fraction if isinstance(fraction, (int, float)) and 0.0 < fraction < 1.0 else DEFAULT_FRACTION

    res = delivered_merge_footprint(args.root, args.base, args.head,
                                    _load_managed_rels(), ceiling, fraction)
    print(_format_line(res, args.base, args.head))
    if args.strict and (not res["ok"] or res["breached"]):
        return 1     # strict: пробой доставляемого объёма или непосчитанный итог краснеют; тонкий — нет
    return 0         # advisory по умолчанию — PR никогда не блокируется


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
