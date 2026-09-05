# -*- coding: utf-8 -*-
"""Предупреждение о ТАЮЩЕМ запасе ОБЪЁМА поставки — до пробоя, в том же прогоне.

Работа `delivery-footprint-warns-before-breach`, цель `checks-that-run`.

ЗАМЕР 2026-08-20/21: потолок объёма (`quality/delivery-budget.yaml` -> volume_bytes) узнавал об
исчерпании ПАДЕНИЕМ на СЛЕДУЮЩЕЙ работе, а не на той, что запас исчерпала. Дважды за одну сессию:
лента положила +55 КБ, оставив 3 290 Б запаса без подъёма, и следующая работа заплатила подъёмом за
чужой дрейф — «мерим очередь, а не размер».

ЧТО ЗДЕСЬ. Предупреждение добавляется К блокирующему потолку, а НЕ вместо него: пробой
(actual >= ceiling) по-прежнему красный (assert в `tests/unit/test_installer.py`), а тонкий запас —
ЗЕЛЁНОЕ предупреждение с АВТО-РАЗБОРОМ (что съедает бюджет, сколько до пробоя, что кандидат урезать)
в ТОМ прогоне, где запас исчерпан. Потолок НЕ становится advisory — прямой запрет из описания работы.

Модуль чистый: разбор поставки (`breakdown_lines`) передаётся аргументом, а не тянется отсюда вверх —
`validation` не импортирует ядро/installer как библиотеку (packages/layering.yaml).
"""
from __future__ import annotations


def reserve_is_thin(actual: int, ceiling: int, fraction: float) -> bool:
    """Запас тонкий: поставка ещё ПОД потолком, но осталось меньше `fraction` от потолка. -> bool.

    Пробой (actual >= ceiling) сюда НЕ относится — его ловит блокирующий assert поставки, красным.
    Мусорные входы (потолок <= 0, доля вне (0;1)) дают False: предупреждать не о чем и порога нет."""
    if ceiling <= 0 or not (0.0 < fraction < 1.0):
        return False
    return actual < ceiling and (ceiling - actual) < ceiling * fraction


def thinning_reserve_warning(actual: int, ceiling: int, fraction: float,
                             breakdown_lines, unit: str = "Б") -> str:
    """Человеческое предупреждение с авто-разбором: сколько осталось до пробоя и что занимает бюджет.

    `breakdown_lines` — уже собранный состав поставки (строки), например
    `installer.ai_ops.delivery_breakdown_lines(top=8)`. Передаётся, а не считается здесь, чтобы
    модуль остался чистым и не тянул installer вверх по слоям."""
    reserve = ceiling - actual
    pct = reserve / ceiling * 100 if ceiling else 0.0
    head = (f"ЗАПАС ОБЪЁМА ПОСТАВКИ ТАЕТ: {actual} {unit} из {ceiling} {unit}, осталось {reserve} "
            f"{unit} ({pct:.1f}%; порог предупреждения {fraction * 100:.0f}%). Это ещё НЕ пробой — "
            f"потолок держит, — но исчерпание названо в ТОМ прогоне, где оно происходит, а не "
            f"падением на следующей работе.")
    guidance = ("Что урезать — решает человек: кит показывает состав, но молча НЕ удаляет. Кандидат — "
                "то, что в дочке кодом не читается (крупнейшие каталоги/файлы ниже). Поднять потолок "
                "можно только записью в quality/delivery-budget.yaml с названными файлами и причиной.")
    return "\n".join([head, guidance, "Что занимает поставку сейчас:"] + list(breakdown_lines))


# ─── footprint ДОСТАВЛЯЕМОГО итога слияния (merge-preview ∩ managed_set) ───────────────────────────
# Follow-up к фордж-нейтральному пивоту: гейт объёма меряет ИТОГ СЛИЯНИЯ, а не ветку PR
# (ai_ops_kit/gates/merge_preview.py считает ВЕСЬ итог). Пробел: дочку волнует НЕ любой файл итога, а
# тот, что к ней реально поедет. Здесь — ПЕРЕСЕЧЕНИЕ дерева-итога слияния с доставляемой поверхностью
# (installer.managed_set): объём именно доставляемой части итога. Функции ЧИСТЫЕ — и файлы итога, и
# managed_set ПЕРЕДАЮТСЯ аргументами, поэтому `validation` (entrypoints) не тянет ни `installer`, ни
# `gates` вверх по слоям; оркестрацию над git-примитивами делает installer/-хелпер (см. layering.yaml).


def delivered_merge_footprint(merge_entries, managed_rels):
    """Доставляемая часть ИТОГА слияния: пересечение файлов дерева-итога с managed_set дочки.

    `merge_entries` — итерируемое (относительный путь, размер) из дерева-итога слияния
    (`ai_ops_kit.gates.merge_preview.merge_preview_entries`); `managed_rels` — множество относительных
    путей доставляемой поверхности (`installer.managed_set`). Считается объём ПЕРЕСЕЧЕНИЯ, а не всего
    дерева: дочку волнует только то, что к ней доставляется.

    -> {"delivered_bytes": int, "delivered_files": int, "paths": [отсортированные пути]}."""
    managed = set(managed_rels)
    hits = [(path, int(size)) for path, size in merge_entries if path in managed]
    return {"delivered_bytes": sum(size for _, size in hits),
            "delivered_files": len(hits),
            "paths": sorted(path for path, _ in hits)}


def delivered_footprint_verdict(delivered_bytes, ceiling, fraction):
    """Вердикт по доставляемому footprint итога слияния против потолка volume_bytes. -> dict.

    Строгость СОГЛАСОВАНА с поставкой и `reserve_is_thin`: пробой — `delivered_bytes >= ceiling` (его
    ловил бы блокирующий assert поставки), тонкий запас — мягкое предупреждение ДО пробоя. Механизм
    настоящий (реально считает и сравнивает), но на пути PR — advisory: промоутит владелец отдельно.

    -> {"breached": bool, "thin": bool, "reserve": int}."""
    breached = ceiling > 0 and delivered_bytes >= ceiling
    thin = reserve_is_thin(delivered_bytes, ceiling, fraction)
    return {"breached": breached, "thin": thin, "reserve": ceiling - delivered_bytes}
