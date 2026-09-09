#!/usr/bin/env python3
"""Advisory-гейт объёма ДОСТАВЛЯЕМОГО итога слияния — merge-preview ∩ managed_set (фордж-нейтрально).

Follow-up к фордж-нейтральному пивоту. `ai_ops_kit/gates/merge_preview.py` меряет ВЕСЬ итог слияния
(base+head без коммита, через `git merge-tree --write-tree`) против потолка volume_bytes — это надёжный
СИГНАЛ дрейфа, но надмножество доставляемого: он считает любой файл дерева-итога, включая dev-ассеты
кита. Дочку же волнует не любой файл итога, а тот, что к ней РЕАЛЬНО поедет.

ЧТО ЗДЕСЬ. ОБЪЁМ и ЧИСЛО ФАЙЛОВ именно ДОСТАВЛЯЕМОЙ части итога слияния: пересечение (файлы
дерева-итога слияния) ∩ (installer.managed_set — управляемая поверхность дочки). Так измеряется то,
что уедет в дочку из РЕЗУЛЬТАТА слияния, а не из ветки PR в одиночку и не из всего дерева-итога.

ДВЕ ОСИ. `volume_bytes` судит объём; `substantive_files` — ЧИСЛО файлов. Вторая ось закрывает ровно
тот дрейф, ради которого заведена работа (разбор 20.08: main тихо ушёл 490->498 ФАЙЛОВ между
слияниями): набор мелких файлов пробивает потолок файлов, не тронув потолок объёма, и объёмная ось
его не ловит. Обе оси меряются против ИТОГА СЛИЯНИЯ, а не ветки PR.

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
                              managed_rels, ceiling: int, fraction: float,
                              files_ceiling: int | None = None) -> dict:
    """Объём И ЧИСЛО файлов доставляемой части итога слияния base_ref+head_ref против потолков.

    Переиспользует примитив `merge_preview.merge_preview_tree` (итог слияния без коммита) и
    `merge_preview.merge_preview_entries` (файлы итога с размерами), ограничивает файлы до
    пересечения с `managed_rels` (доставляемая поверхность) и зовёт чистые вердикты из `validation`.

    ДВЕ ОСИ. `ceiling` (volume_bytes) судит ОБЪЁМ; `files_ceiling` (substantive_files) — ЧИСЛО файлов.
    Вторая ось закрывает ровно тот дрейф, ради которого заведена работа: main тихо ушёл 490->498
    ФАЙЛОВ между слияниями — набор мелких файлов пробивает потолок файлов, не тронув потолок объёма.
    Если `files_ceiling` не передан (None), файловая ось не считается (обратная совместимость).

    -> {"ok": bool, "reason": str, "delivered_bytes": int|None, "delivered_files": int|None,
        "paths": [...], "ceiling": int, "fraction": float, "breached": bool, "thin": bool,
        "reserve": int|None,  # объёмная ось
        "files_ceiling": int|None, "files_breached": bool, "files_thin": bool,
        "files_reserve": int|None}.  # файловая ось

    FAIL-CLOSED: превью итога не удалось (конфликт/ошибка git/старый git) -> ok=False, обе оси
    breached=False (пробой доставляемого НЕ утверждается, раз итог посчитать не смогли), reason назван.
    """
    preview = merge_preview.merge_preview_tree(root, base_ref, head_ref)
    if not preview.get("ok"):
        return {"ok": False, "reason": preview.get("reason", "merge-preview не удалось"),
                "delivered_bytes": None, "delivered_files": None, "paths": [],
                "ceiling": ceiling, "fraction": fraction,
                "breached": False, "thin": False, "reserve": None,
                "files_ceiling": files_ceiling, "files_breached": False,
                "files_thin": False, "files_reserve": None}
    entries = merge_preview.merge_preview_entries(root, preview["tree"])
    fp = dfw.delivered_merge_footprint(entries, managed_rels)
    verdict = dfw.delivered_footprint_verdict(fp["delivered_bytes"], ceiling, fraction)
    if isinstance(files_ceiling, int) and files_ceiling > 0:
        fv = dfw.delivered_filecount_verdict(fp["delivered_files"], files_ceiling, fraction)
        files_axis = {"files_ceiling": files_ceiling, "files_breached": fv["breached"],
                      "files_thin": fv["thin"], "files_reserve": fv["reserve"]}
    else:
        files_axis = {"files_ceiling": files_ceiling, "files_breached": False,
                      "files_thin": False, "files_reserve": None}
    return {"ok": True, "reason": "",
            "delivered_bytes": fp["delivered_bytes"], "delivered_files": fp["delivered_files"],
            "paths": fp["paths"], "ceiling": ceiling, "fraction": fraction,
            **verdict, **files_axis}


def _load_managed_rels():
    """Доставляемая поверхность дочки как множество относительных путей (installer.managed_set)."""
    import ai_ops as installer     # noqa: E402 — installer/ добавлен в sys.path выше
    return {rel for _src, rel in installer.managed_set()}


def _load_budget():
    """(volume_bytes, порог предупреждения, substantive_files) из quality/delivery-budget.yaml.

    Оба потолка — ДАННЫЕ реестра, не хардкод. substantive_files может отсутствовать (None) — тогда
    файловая ось просто не считается."""
    import ai_ops as installer     # noqa: E402 — installer/ добавлен в sys.path выше
    doc = installer.delivery_budget() or {}
    ceilings = doc.get("ceilings") or {}
    ceiling = ceilings.get("volume_bytes")
    files_ceiling = ceilings.get("substantive_files")
    fraction = (doc.get("warnings") or {}).get("volume_reserve_fraction")
    return ceiling, fraction, files_ceiling


def _format_line(res: dict, base_ref: str, head_ref: str) -> str:
    """Человекочитаемый вывод: число доставляемого объёма итога, вердикт и (при тонком запасе) разбор."""
    if not res["ok"]:
        return (f"DELIVERED-MERGE-FOOTPRINT: посчитать доставляемый итог слияния {base_ref}+{head_ref} "
                f"НЕ УДАЛОСЬ — {res['reason']}. Advisory: PR не блокируется, но зелёным это не считается.")
    dbytes, ceiling = res["delivered_bytes"], res["ceiling"]
    dfiles, files_ceiling = res["delivered_files"], res.get("files_ceiling")
    files_note = (f" ЧИСЛО файлов: {dfiles} из потолка {files_ceiling} (запас {res.get('files_reserve')})."
                  if isinstance(files_ceiling, int) and files_ceiling > 0 else "")
    head = (f"DELIVERED-MERGE-FOOTPRINT ({base_ref}+{head_ref}): доставляемая часть итога слияния "
            f"{dbytes} Б в {dfiles} файлах, потолок {ceiling} Б, запас {res['reserve']} Б.{files_note} "
            f"Меряется ПЕРЕСЕЧЕНИЕ дерева-итога с managed_set дочки — не вся ветка PR и не всё дерево.")
    if res["breached"]:
        return head + " ПРОБОЙ доставляемого объёма (advisory — промоутит владелец)."
    if res.get("files_breached"):
        return head + " ПРОБОЙ ЧИСЛА доставляемых файлов (advisory — промоутит владелец)."
    if res["thin"] or res.get("files_thin"):
        breakdown = ["Доставляемые файлы в итоге слияния (пути):"] + [f"    {p}" for p in res["paths"][:10]]
        base_line = dfw.thinning_reserve_warning(dbytes, ceiling, res["fraction"], breakdown)
        return head + "\n" + base_line
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

    ceiling, fraction, files_ceiling = _load_budget()
    if not isinstance(ceiling, int) or ceiling <= 0:
        print("DELIVERED-MERGE-FOOTPRINT: не прочитан потолок volume_bytes из "
              "quality/delivery-budget.yaml — advisory, пропуск.")
        return 1 if args.strict else 0
    fraction = fraction if isinstance(fraction, (int, float)) and 0.0 < fraction < 1.0 else DEFAULT_FRACTION

    res = delivered_merge_footprint(args.root, args.base, args.head,
                                    _load_managed_rels(), ceiling, fraction, files_ceiling)
    print(_format_line(res, args.base, args.head))
    # strict: краснеет пробой ЛЮБОЙ оси (объём ИЛИ число файлов) или непосчитанный итог; тонкий — нет.
    if args.strict and (not res["ok"] or res["breached"] or res.get("files_breached")):
        return 1
    return 0         # advisory по умолчанию — PR никогда не блокируется


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
