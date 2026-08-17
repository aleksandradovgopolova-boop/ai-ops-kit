#!/usr/bin/env python3
"""Миграция: закрытые работы активного плана дочки переезжают в `history/plan-history.yaml`.

ЗАЧЕМ ОНА ЕСТЬ (F-030, поле 15–17.08.2026). Правило «закрытая работа живёт в history» появилось у
кита в 3.36.x и применялось к ДОЧКАМ БЕЗ МИГРАЦИИ. Цена замерена дважды:
  * дочка «Окошко»: обновление 3.36.8 -> 3.36.10 сделало план невалидным (0 ошибок до, 28 после);
  * дочка ИИ-Среда, замер 17.08.2026 на копии обновления: `./ai-ops next` ОТКАЗЫВАЕТСЯ отвечать и
    печатает 32 ошибки — по одной на каждую закрытую работу в активном плане.
Обновление у дочек по умолчанию автоматическое, то есть это ждало каждую: правило меняется у нас, а
ломается у них. Ответ «что дальше» — главный вопрос владельца к киту, и он переставал работать после
обновления, которое владелец не заказывал.

РЕШЕНИЕ ВЛАДЕЛЬЦА 17.08.2026: переносить с пометкой «результат не записан», а не выдумывать
результаты и не блокировать проект. Причина: контракт истории требует у `done` НАЗВАННЫЙ результат
(`result`) и место перепроверки (`pr`/`commit`/`evidence`/`finding`), а у работ, закрытых до правила,
ни того ни другого нет — их закрывали статусом ровно потому, что так было можно.
Из этого следует и то, чего миграция НЕ делает: она не пишет за владельца, «что получилось». Запись
`migrated_without_result: true` — честное «неизвестно», и валидатор истории показывает такие записи
предупреждением, а не ошибкой. Требование к НОВЫМ закрытиям остаётся строгим.

ИДЕМПОТЕНТНА: повторный запуск не дублирует записи (сверка по id) и не трогает уже перенесённое.
БЕЗ ПОТЕРИ ДАННЫХ: запись переезжает ЦЕЛИКОМ, вместе со всеми полями и своим текстом; из активного
плана она удаляется только после того, как оказалась в истории.
КОММЕНТАРИИ ПЛАНА НЕ СОХРАНЯЮТСЯ — и это названо прямо: yaml переписывается разбором, а не текстом.
Поэтому переносится ТОЛЬКО закрытое, и только если оно есть; план без закрытых работ не
перезаписывается вовсе (см. ранний выход) — иначе миграция стирала бы разбор из планов, которым
она не нужна.

Аргумент — корень child-репозитория.
"""
import sys
from pathlib import Path

CLOSED = {"done", "dropped"}
NOTE = ("перенесено миграцией кита: работа была закрыта до правила «закрытая работа живёт в "
        "history», результат при закрытии не записан — восстановить его из плана нельзя")


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:                      # без pyyaml миграция не гадает, а честно отказывается
        print("миграция плана: нет pyyaml — перенос не выполнен", file=sys.stderr)
        return None


def main(root):
    yaml = _yaml()
    if yaml is None:
        return 1
    root = Path(root)
    plan_path = root / "planning" / "plan.yaml"
    if not plan_path.is_file():
        print("миграция плана: planning/plan.yaml нет — переносить нечего")
        return 0

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    if plan.get("template") is True:
        print("миграция плана: это ещё заготовка кита — не трогаем")
        return 0
    works = plan.get("work")
    if not isinstance(works, list):
        print("миграция плана: раздела work нет — переносить нечего")
        return 0

    closed = [w for w in works if isinstance(w, dict) and w.get("status") in CLOSED]
    if not closed:
        print("миграция плана: закрытых работ в активном плане нет — файл не переписан")
        return 0

    hist_path = root / "history" / "plan-history.yaml"
    hist = {}
    if hist_path.is_file():
        hist = yaml.safe_load(hist_path.read_text(encoding="utf-8")) or {}
    hist.setdefault("schema_version", 1)
    hist.setdefault("kind", "delivery-plan-history")
    already = hist.get("work")
    if not isinstance(already, list):
        already = []
    known = {w.get("id") for w in already if isinstance(w, dict)}

    moved = []
    for w in closed:
        wid = w.get("id")
        if wid in known:                     # уже в истории — из активного плана просто уйдёт
            continue
        entry = dict(w)
        entry.pop("branch", None)            # ветка закрытой работы управлением не является
        if not str(entry.get("result") or "").strip():
            entry["result"] = NOTE
            entry["migrated_without_result"] = True
        already.append(entry)
        known.add(wid)
        moved.append(wid)

    hist["work"] = already
    plan["work"] = [w for w in works
                    if not (isinstance(w, dict) and w.get("status") in CLOSED)]

    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(yaml.safe_dump(hist, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    print(f"миграция плана: в history перенесено работ {len(moved)}, "
          f"в активном плане осталось {len(plan['work'])}"
          + (f"; без записанного результата: {sum(1 for w in already if w.get('migrated_without_result'))}"
             if moved else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
