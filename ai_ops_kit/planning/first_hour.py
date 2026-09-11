"""Оркестратор «первого часа» — model→answers→bootstrap→next ОДНИМ нарративом (issue #647).

Первый час с китом сегодня — четыре раздельные команды (`model` → `model --answer` →
`bootstrap --apply` → `next`), а склейку и повествование держит только проза скилла (два
расходящихся файла). Здесь склейка становится first-class В САМОМ ките: понял репозиторий →
вот что знаю/не знаю → (если ответы есть) первое направление и план → следующая работа и почему.

ЭТО НЕ НОВЫЙ ДВИЖОК. Все кирпичи готовы и проверены — `repo_audit.run` (понимание + provenance),
`product_bootstrap.plan/apply`, `next_work.compute`. Здесь только тонкая склейка с честными
состояниями: пока есть открытые БЛОКИРУЮЩИЕ вопросы (или источники противоречат — CONFLICTING,
#634), кит НЕ выдаёт направление за готовое, а честно останавливается на «нужны ответы». Ответы
есть — собирает направление и план и говорит, какую работу взять первой.

Дисциплина записи сохранена: без `apply=True` это сухой предпросмотр (что БУДЕТ создано), запись
делает только явный `apply` — ровно как отдельная команда `bootstrap --apply`.
"""
from __future__ import annotations

NEEDS_ANSWERS = "needs_answers"
READY = "ready"
BLOCKED_UNDERSTANDING = "blocked_understanding"


def run(child_root, *, apply=False, budget_left=None, understanding=None) -> dict:
    """Сшить первый час одним отчётом. -> dict со стадией и честными состояниями каждого шага.

    stage:
      blocked_understanding — дерево не прочиталось (класс UNKNOWN): любой вывод был бы выдумкой;
      needs_answers         — есть блокирующие вопросы или противоречия источников: направление
                              собирать рано, кит останавливается и НЕ выдаёт непроверенное за готовое;
      ready                 — ответов хватает: собрано направление/план (+ предложена работа).
    """
    from ai_ops_kit.planning import repo_audit as _ra
    from ai_ops_kit.planning import product_bootstrap as _boot
    from ai_ops_kit.planning import next_work as _nw

    und = understanding if understanding is not None else _ra.run(child_root)
    ask = und.get("ask") or {}
    questions = list(ask.get("questions") or [])
    blocking = [q for q in questions if q.get("blocks_work")]
    conflicts = list(und.get("conflicts") or [])
    cls = (und.get("classification") or {}).get("class")

    out = {"schema_version": 1, "kind": "first-hour", "classification": cls,
           "understanding": und, "questions": questions, "blocking_questions": blocking,
           "conflicts": conflicts, "bootstrap": None, "bootstrap_applied": False, "next": None}

    # Дерево не прочиталось — останавливаемся раньше всего: bootstrap на выдумке был бы вреден.
    if cls == "UNKNOWN":
        out["stage"] = BLOCKED_UNDERSTANDING
        return out

    # Блокирующие вопросы ИЛИ противоречие источников — направление собирать рано. Это честная
    # остановка, а не провал: кит называет, чего не хватает, и не выдаёт непроверенное за готовое.
    if blocking or conflicts:
        out["stage"] = NEEDS_ANSWERS
        return out

    # Ответов хватает: собираем направление и план. Без apply — предпросмотр (что БУДЕТ создано).
    boot_plan = _boot.plan(child_root, und)
    out["bootstrap"] = _boot.apply(child_root, boot_plan, und) if apply else boot_plan
    out["bootstrap_applied"] = bool(apply)

    # Следующую работу считаем только когда план РЕАЛЬНО есть (после apply): иначе next_work читал бы
    # пустой/заготовочный план и «рекомендация» была бы ни о чём. Сухой предпросмотр честно без next.
    if apply and not (out["bootstrap"] or {}).get("error"):
        out["next"] = _nw.compute(child_root, budget_left=budget_left)

    out["stage"] = READY
    return out
