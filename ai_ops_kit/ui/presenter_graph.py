#!/usr/bin/env python3
"""Проекции графа знаний и обратной связи: сырой внутренний отчёт -> `UserMessage`.

Сателлит фасада `presenter.py`. Здесь переводчики сборки/трассы/пробелов графа знаний и судьбы
замечаний дочки к киту. Импортирует только ядро `presenter_core` (`message`); ни фасад, ни
`presenter_formatters` отсюда не импортируются — цикла нет.
"""
from __future__ import annotations

from ai_ops_kit.ui.presenter_core import message


def from_graph_build(graph: dict, wrote=None) -> dict:
    """`knowledge_graph.build_graph()` -> UserMessage. Сборка из трёх источников в один граф."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_type: dict = {}
    for n in nodes:
        by_type[n.get("type")] = by_type.get(n.get("type"), 0) + 1
    where = f" Записал в {wrote}." if wrote else " Показал (для записи — --apply)."
    return message(
        status="ok",
        summary=(f"Собрал граф из плана, обучения и паспортов функций: {len(nodes)} узлов, "
                 f"{len(edges)} связей.{where}"),
        why_it_matters="Один граф вместо ручной сборки из трёх разных файлов.",
        technical={"by_type": by_type, "written_to": str(wrote) if wrote else None})


def from_graph_trace(result: dict) -> dict:
    """`knowledge_graph.trace()` -> UserMessage. «Зачем функция существует» человеческими словами."""
    feature = result.get("feature")
    if result.get("verdict") == "unknown":
        return message(
            status="blocked",
            summary=f"Функции «{feature}» в графе нет — собрать её историю не из чего.",
            why_it_matters="Граф строю только из объявленного в плане, обучении и паспортах функций; "
                           "выдумывать связь не буду.",
            next_steps=["проверь id функции", "или собери граф: ./ai-ops graph build"])
    chain = result.get("chain") or []
    titles = [c.get("title") or c.get("id") for c in chain]
    verdict = result.get("verdict")
    phrase = {
        "confirmed": "ценность подтверждена измеримым результатом",
        "refuted": "измеримый результат не достигнут",
        "pending": "результат объявлен, но ещё не измерен",
        "outcome-unmeasured": "результат объявлен, но измерить его нечем",
        "no-outcome": "к измеримому результату функция пока не привязана",
        "unmoored": "функция не привязана ни к одной цели",
    }.get(verdict, "результат ещё не подтверждён")
    chain_line = " → ".join(titles) if titles else feature
    if result.get("goal"):
        summary = (f"Функция «{titles[-1]}» служит цели «{titles[0]}»: {chain_line}. "
                   f"{phrase.capitalize()}.")
    else:
        summary = f"Функция «{feature}»: {chain_line}. {phrase.capitalize()}."
    # «Зачем функция появилась» — из РЕШЕНИЯ (истории), а не из пересказа кода. Если решение
    # объявлено в паспорте функции, история его называет прямо в ответе.
    decision = result.get("decision")
    if decision:
        summary += f" Появилась из решения: «{decision.get('title')}»."
    # «Что построило функцию» — из РАБОТЫ (истории), а не из пересказа кода. Если работа объявлена в
    # паспорте функции, история называет её (и PR) прямо в ответе.
    built_by = result.get("built_by") or []
    if built_by:
        first = built_by[0]
        pr = f" (PR #{first['pr']})" if first.get("pr") else ""
        more = f" и ещё {len(built_by) - 1}" if len(built_by) > 1 else ""
        summary += f" Построена работой: «{first.get('title')}»{pr}{more}."
    # «Кто/что проверил» — из ПЕРСИСТЕНТНОГО вердикта (путь ревью, не писатель). Заголовок узла уже
    # несёт, кем проверено («проверили: машина, независимый ревьюер»); verified отличает машинную опору
    # от одного лишь суждения. Нет записи -> строки нет (проверки могло не быть — это НЕ пробел).
    review = result.get("review")
    if review:
        title = review.get("title") or "проверено"
        title = title[:1].upper() + title[1:]
        note = "" if review.get("verified") else " (держится на суждении, без машинной опоры)"
        summary += f" {title}{note}."
    # «Что произошло с продуктом» — РЕАЛЬНЫЙ сдвиг целевой метрики после релиза (baseline→после против
    # цели), а не «shipped»/«pending». Проекция уже посчитанного evaluate_outcome (met/failed ИЗ ЧИСЕЛ),
    # которую слой CLI кладёт в `measured_outcome`. Нет замера -> честное «ещё не накоплен» + условие.
    mo = result.get("measured_outcome") or {}
    measured_verdict = None
    if mo.get("measured"):
        measured_verdict = mo.get("verdict")
        took = "цель взята" if measured_verdict == "met" else "цель пока не взята"
        summary += (f" Результат по релизу: было {mo.get('baseline')} → стало {mo.get('value')} "
                    f"при цели {mo.get('target')} — {took}.")
        hyp = mo.get("hypothesis")
        if hyp == "confirmed":
            summary += " Гипотеза подтвердилась."
        elif hyp == "refuted":
            summary += " Гипотеза не подтвердилась."
        for br in (mo.get("guardrail_breaches") or []):
            summary += f" Защитная метрика просела: {br}."
    elif mo:
        # Контракт есть, замера ещё нет: называем ПОЧЕМУ и ЧТО нужно, а не молчим «pending».
        reason = mo.get("not_accumulated_reason") or "итог по релизу ещё не измерен"
        need = mo.get("needed_to_measure")
        summary += f" Результат ещё не накоплен: {reason}."
        if need:
            summary += f" Чтобы измерить: {need}."
    # «Что делать дальше по этому уроку» — конкретное действие + «потому что <что произошло>», из петли
    # outcome→insight→next (writer≠judge: это предложение, активным без решения человека не станет).
    na = result.get("next_action") or {}
    if na.get("because"):
        summary += f" Дальше по этому уроку: {na.get('action')} — потому что {na.get('because')}."
    headline = ("Результат не достигнут" if verdict == "refuted" or measured_verdict == "failed"
                else None)
    ok = verdict == "confirmed" or measured_verdict == "met"
    return message(
        status=("ok" if ok else "degraded"),
        headline=headline,
        summary=summary,
        why_it_matters="Раньше этот ответ собирали вручную из плана, обучения, паспорта функции, "
                       "журнала решений и истории работ; теперь и «зачем» (решение), и «что построили» "
                       "(работа/PR), и «кто проверил» (вердикт), и «подтвердилось ли» (результат) "
                       "читаются по одному графу.",
        next_steps=(list(result.get("gaps") or []) or None),
        technical={"verdict": verdict, "measured_verdict": measured_verdict,
                   "chain": [c.get("id") for c in chain],
                   "outcome": result.get("outcome"), "measured_outcome": mo or None,
                   "next_action": na or None, "decision": decision,
                   "built_by": built_by, "review": review})


def from_scorecard(scorecard: dict) -> dict:
    """`product_scorecard.build_scorecard()` -> UserMessage. Карта продукта кита из 5 метрик.

    Мерит кит КАК ПРОДУКТ, а не числом возможностей. Измеренная метрика печатается долей в
    процентах, неизмеренная — честным «не измерено» с причиной (а не нулём и не выдуманным числом):
    инвариант карты «честность превыше полноты» обязан быть виден и человеку."""
    metrics = scorecard.get("metrics") or []
    measured = scorecard.get("measured_count") or 0
    total = len(metrics)
    lines = []
    for m in metrics:
        if m.get("measured"):
            pct = round((m.get("value") or 0) * 100)
            lines.append(f"• {m.get('title')}: {pct}% ({m.get('numerator')}/{m.get('denominator')})")
        else:
            lines.append(f"• {m.get('title')}: не измерено — {m.get('reason')}")
    summary = ("Мерю себя как продукт, а не числом возможностей — карта из 5 метрик:\n"
               + "\n".join(lines))
    if scorecard.get("unmeasured_count"):
        status = "degraded"
        headline = f"Карта продукта: измерено честно {measured} из {total} метрик"
        why = ("Результат после релиза и влияние уроков на решения честно стоят «не измерено»: "
               "у самого кита живой аналитики нет, а выдуманное число было бы враньём.")
    else:
        status = "ok"
        headline = "Карта продукта: все метрики измерены"
        why = "Кит меряет себя как продукт единой картой, а не числом возможностей."
    return message(status=status, headline=headline, summary=summary,
                   why_it_matters=why, technical=scorecard)


def from_graph_gaps(result: dict) -> dict:
    """`knowledge_graph.gaps()` -> UserMessage. Что не покрыто измеримым результатом."""
    oc = result.get("outcomes_without_metric") or []
    mt = result.get("metrics_without_release") or []
    ft = result.get("features_without_outcome") or []
    total = len(oc) + len(mt) + len(ft)
    if total == 0:
        return message(
            status="ok",
            summary="Каждый объявленный результат измеряется, каждая функция привязана к результату.",
            why_it_matters="Непокрытого измеримым результатом в графе не нашлось.")
    lines = []
    if ft:
        lines.append("функции без измеримого результата: " + ", ".join(f["id"] for f in ft))
    if oc:
        lines.append("результаты, которые нечем измерить: " + ", ".join(o["id"] for o in oc))
    if mt:
        lines.append("метрики, которых не наблюдает ни один релиз: " + ", ".join(m["id"] for m in mt))
    return message(
        status="degraded",
        headline="Есть пробелы в измеримости",
        summary=f"Нашёл {total} мест, где ценность не подтверждена измеримым результатом.",
        why_it_matters="Такую дыру иначе видно только при ручной сверке плана, метрик и релизов.",
        next_steps=lines,
        technical=result)


def from_kit_feedback_status(rep: dict) -> dict:
    """Судьба наблюдений этой дочки -> UserMessage. Ответ обязан быть виден, иначе канал умрёт."""
    total = rep.get("total") or 0
    waiting, decided = rep.get("waiting") or [], rep.get("decided") or []
    if not total:
        return message(
            status="ok", headline="Замечаний ко мне пока нет",
            summary="Ты ещё ничего мне не говорила о моей работе в этом проекте.",
            next_steps=['сказать так: ./ai-ops feedback "что было не так"'])
    if rep.get("errors"):
        # ДВЕ ПРАВКИ ПО ПРОБЕ КАНАЛА НА ЖИВОЙ ДОЧКЕ (18.08.2026), и обе про честность ответа.
        # ПЕРВАЯ — АРИФМЕТИКА: `total` считает только ЧИТАЕМЫЕ записи, поэтому «записано 1, но 1 из
        # них не разбираются» на одной хорошей и одной битой читалось как «единственная запись
        # сломана». Числа теперь названы раздельно, а сумма — сумма.
        # ВТОРАЯ — ОДНА БИТАЯ ЗАПИСЬ ГЛУШИЛА ВЕСЬ ОТВЕТ: судьба читаемых замечаний не показывалась
        # вовсе. Это ровно тот отказ, от которого канал и умирает: человек перестаёт видеть ответ и
        # перестаёт писать. Деградация остаётся деградацией — но она про непрочитанные записи, а не
        # про все.
        bad = len(rep["errors"])
        fates = [f"«{d.get('statement') or d['id']}» — {d.get('state_name') or d['state']}"
                 for d in decided[:2]]
        return message(
            status="degraded", headline="Часть замечаний я не читаю",
            summary=f"Записей {total + bad}: читаю {total}, не могу прочитать {bad}.",
            why_it_matters="Про непрочитанные я не могу обещать, что они до меня дойдут. "
                           "Остальные видны ниже — их судьба не потерялась.",
            next_steps=fates or None,
            technical={"ошибки": rep["errors"], "по состояниям": rep.get("by_state")})
    if waiting and not decided:
        return message(
            status="ok", headline="Сказанное ждёт ответа",
            summary=f"Замечаний {total}, ответа пока нет ни на одно.",
            why_it_matters="Ответ приходит, когда я разбираю их у себя: каждое станет работой или "
                           "будет отклонено с причиной. Молча они не исчезнут.",
            next_steps=[w["statement"] for w in waiting[:2]],
            technical=rep.get("by_state"))
    return message(
        status="ok", headline="Вот что стало с твоими замечаниями",
        summary=f"Замечаний {total}: с ответом {len(decided)}, ждут ответа {len(waiting)}.",
        next_steps=[f"«{d.get('statement') or d['id']}» — "
                    f"{d.get('state_name') or d['state']}"
                    + (f": {d['reason']}" if d.get("reason") else "")
                    for d in decided[:2]],
        technical=rep.get("by_state"))
