"""`ai-ops candidates` — задачи-кандидаты из двух источников + приёмка пачкой.

Кит НАРЕЗАЕТ кандидатов, владелец ПРИНИМАЕТ пачкой (предохранитель: кит сам не дописывает активную
работу). Два источника: непокрытые направления роадмапа (`intelligence.roadmap_candidates`) и
наблюдения дочек/находки (`intelligence.child_findings`). Приёмку в plan.yaml делает
`planning.candidate_intake` — единственное место, что пишет план.

ПОЧЕМУ UNION ЗДЕСЬ, А НЕ В `planning`. Слой `planning` (ниже) не вправе импортировать `intelligence`
(вверх по слоям). Слой `entrypoints` (CLI) вправе звать оба источника — поэтому объединение живёт
здесь, а `candidate_intake` принимает уже собранный список.

Команда:
  candidates            — показать всех кандидатов с источником и причиной (только чтение, dry);
  candidates list       — то же;
  candidates accept <id> [<id>...]  — принять выбранных (пишет plan.yaml);
  candidates accept --all           — принять всех.
Без глагола приёмки план НЕ меняется.
"""
from __future__ import annotations

import json
from pathlib import Path


def gather_candidates(child_root) -> list:
    """Union кандидатов из обоих источников: находки дочек + непокрытые направления роадмапа.

    Обратный канал обогащает очередь, а не является её предусловием: сбой одного источника не роняет
    другой (каждый под своим try). -> list[dict] кандидатов."""
    from ai_ops_kit.intelligence import child_findings, roadmap_candidates
    root = Path(child_root)
    out: list = []
    try:
        proj = child_findings.project_findings(root)
        out.extend(proj.get("candidates") or [])
    except Exception:  # noqa: BLE001 — канал находок опционален, не предусловие
        pass
    try:
        dproj = roadmap_candidates.project_uncovered_directions(root)
        out.extend(dproj.get("candidates") or [])
    except Exception:  # noqa: BLE001 — проекция направлений опциональна, не предусловие
        pass
    return out


def inbox_direction_candidates(child_root):
    """Непокрытые направления роадмапа как кандидаты (DRAFT) для входящих владельца. Плана нет/не
    читается или сбор упал -> None (честное «не знаю», не «покрыто всё»). READ-ONLY. -> list|None."""
    try:
        from ai_ops_kit.intelligence import roadmap_candidates
        proj = roadmap_candidates.project_uncovered_directions(Path(child_root))
    except Exception:  # noqa: BLE001 — обратный канал обогащает очередь, не является её предусловием
        return None
    return (proj.get("candidates") or []) if proj.get("readable") else None


def _positionals(a) -> list:
    """Позиционные аргументы БЕЗ каталога репозитория (`.`/абсолютный путь подставляет обёртка)."""
    def _is_dir(p):
        try:
            return Path(p).is_dir()
        except OSError:
            return False
    return [x for x in (getattr(a, "rest", None) or []) if not _is_dir(x)]


_SOURCE_LABEL = {
    "roadmap-direction": "направление роадмапа без работ",
    "child-finding": "наблюдение из прогона дочки",
}


def _source_label(cand: dict) -> str:
    return _SOURCE_LABEL.get(str(cand.get("source") or ""), "наблюдение из прогона")


def _list_candidates(child_root, cands, js: bool) -> int:
    """Показать кандидатов (только чтение)."""
    if js:
        print(json.dumps({"kind": "TaskCandidates", "count": len(cands), "candidates": cands},
                         ensure_ascii=False, indent=2))
        return 0
    if not cands:
        print("Кандидатов нет: непокрытых направлений роадмапа и открытых наблюдений не найдено.\n"
              "Это не «нечего делать» — это «резать пока нечего» по прочитанным источникам.")
        return 0
    print(f"Задачи-кандидаты ({len(cands)}) — черновики, активной работой станут только по приёмке:")
    for c in cands:
        print("")
        print(f"• {c.get('title')}")
        print(f"    откуда: {_source_label(c)}")
        if c.get("rationale"):
            print(f"    почему: {c['rationale']}")
        print(f"    принять: ./ai-ops candidates accept {c.get('id')}")
    print("\nПринять всех: ./ai-ops candidates accept --all")
    return 0


def _accept_candidates(child_root, cands, ids, take_all: bool, js: bool) -> int:
    """Принять выбранных/всех кандидатов пачкой (пишет plan.yaml)."""
    from ai_ops_kit.planning import candidate_intake
    if take_all:
        chosen = [c.get("id") for c in cands if c.get("id")]
        if not chosen:
            # --all при пустом списке — не ошибка ввода, а «принимать нечего» (в т.ч. после того,
            # как всё уже принято — идемпотентно). Честный ноль, а не окрик про синтаксис.
            if js:
                print(json.dumps({"ok": True, "to_add": [], "skipped_existing": [],
                                  "applied": False, "reason": "кандидатов нет"}, ensure_ascii=False))
            else:
                print("Кандидатов нет — принимать нечего.")
            return 0
    else:
        chosen = list(ids)
        if not chosen:
            msg = ("candidates accept: назовите id кандидата(ов) или --all.\n"
                   "Список: ./ai-ops candidates")
            if js:
                print(json.dumps({"ok": False, "reason": "нет id и нет --all"}, ensure_ascii=False))
            else:
                print(msg)
            return 2
    rep = candidate_intake.accept_candidates(child_root, chosen, cands, apply=True)
    if js:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1 if rep.get("error") else 0
    if rep.get("error"):
        print(f"Принять не удалось: {rep['error']}")
        return 1
    added = rep.get("to_add") or []
    skipped = rep.get("skipped_existing") or []
    if added:
        print(f"Добавлено в план работ ({len(added)}):")
        for it in added:
            print(f"  • {it['id']} — {it['title']}")
    if skipped:
        print(f"Пропущено (уже есть в плане) — {len(skipped)}: {', '.join(skipped)}")
    if not added and not skipped:
        print("Ничего не добавлено: названные кандидаты не найдены среди актуальных.")
    return 0


def run_candidates(child_root, a) -> int:
    """Точка входа команды `candidates`. Диспетч: list (dry) / accept (пишет)."""
    js = bool(getattr(a, "json", False))
    root = Path(child_root)
    args = _positionals(a)
    verb = (args[0].strip().lower() if args else "list")
    cands = gather_candidates(root)
    if verb in ("", "list"):
        return _list_candidates(root, cands, js)
    if verb == "accept":
        take_all = bool(getattr(a, "all", False))
        ids = args[1:]
        return _accept_candidates(root, cands, ids, take_all, js)
    # Неизвестный глагол — назвать, что умеет, а не молча вернуть успех.
    if js:
        print(json.dumps({"ok": False, "reason": f"неизвестная подкоманда: {verb}",
                          "subcommands": ["list", "accept"]}, ensure_ascii=False))
    else:
        print(f"candidates: неизвестная подкоманда «{verb}». Доступно: list, accept <id..>|--all.")
    return 2


def _intent_candidates(task, child_root, signals, a) -> int:
    """Обработчик интента `candidates` (регистрируется в ai_ops_cli)."""
    return run_candidates(Path(child_root), a)
