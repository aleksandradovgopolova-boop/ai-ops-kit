#!/usr/bin/env python3
"""Карта продукта кита: ЕДИНАЯ первоклассная мера себя из 5 метрик, а не числа возможностей.

ЗАЧЕМ. Внешнее продуктовое ревью (17.09): кит перестаёт мерить развитие ЧИСЛОМ возможностей (34
команды, 36 гейтов, 89 валидаторов) и начинает мерить себя как ПРОДУКТ — пятью метриками. Замер
(`qualification/KIT-AS-PRODUCT-METRICS-MEASUREMENT-2026-09-17.md`): единой карты нет, сырьё для
метрик 2/3/4 разрознено (`validate_claims`, `knowledge_graph.gaps`), 1 и 5 не считаются вовсе.

ЧТО СЧИТАЕТСЯ И ЧТО ЧЕСТНО «НЕ ИЗМЕРЕНО».
  1. feature_completion_rate  — доля фич, дошедших от идеи до релиза (из графа знаний). СЧИТАЕТСЯ.
  2. evidence_coverage        — доля утверждений кита с реальным evidence, ДОЛЕЙ, не pass/fail. Долю
     считает этот слой; сырые результаты проверок реестра честности даёт `validate_claims` (из
     `validation`, entrypoints), поэтому передаются СНАРУЖИ — intelligence её не импортирует (это была
     бы зависимость вверх, тот же инвариант, что у `outcome_insight`). Нет результатов -> «не измерено».
  3. product_memory_coverage  — доля выпущенных фич с ПОЛНОЙ life story (рёбра decision/work/review/
     outcome в графе). СЧИТАЕТСЯ.
  4. outcome_coverage         — доля фич с РЕАЛЬНЫМ результатом после релиза. Каркас: у самого кита
     живой аналитики нет -> честное «не измерено», а не выдуманное число.
  5. learning_to_decision_rate — доля решений, опирающихся на прошлые результаты. Каркас: замкнутой
     петли обучения пока нет -> честное «не измерено».

ИНВАРИАНТ (ядро работы, не деталь). ЧЕСТНОСТЬ ПРЕВЫШЕ ПОЛНОТЫ: нет данных -> метрика в состоянии
`measured=False` с причиной по-русски, НИКОГДА выдуманное число. «Не знаю» и «в порядке» — разные
состояния (тот же принцип, что в `knowledge_graph.gaps` и `health_common`).

Слой: `intelligence` (читает данные ядра через `knowledge_graph`; наверх — `validation` — НЕ
импортирует). Read-only: ничего не пишет.
"""
from __future__ import annotations

# Паспорта-демо из `examples/feature-blueprint-demo/` — учебные, не реальные фичи кита: в карте
# продукта КИТА они бы искажали доли, поэтому исключаются по маркеру в пути blueprint'а.
_DEMO_MARKER = "feature-blueprint-demo"

# Четыре ребра ПОЛНОЙ нити истории фичи: зачем(decision) -> построено(work) -> проверено(review) ->
# результат(outcome). Метрика product-memory меряет долю фич, у которых замкнуты ВСЕ четыре.
_FULL_STORY_EDGES = ("decision", "work", "review", "outcome")


def _metric(mid: str, title: str, *, measured: bool, value=None, numerator=None,
            denominator=None, detail: str = "", reason: str = "", caveat: str = "") -> dict:
    """Одна запись карты. Измеренная несёт долю и числитель/знаменатель; неизмеренная — ПРИЧИНУ.

    `reason` (по-русски, человеку) обязателен у `measured=False` — «не измерено» без причины было бы
    таким же немым, как выдуманное число. `caveat` — честная оговорка о границе прокси там, где доля
    считается, но покрывает не буквально весь вопрос."""
    m = {"id": mid, "title": title, "measured": bool(measured)}
    if measured:
        m["unit"] = "ratio"
        m["value"] = value
        m["numerator"] = numerator
        m["denominator"] = denominator
    else:
        m["value"] = None
        if not (reason or "").strip():
            raise ValueError(f"метрика {mid!r} не измерена, но причина не названа")
        m["reason"] = reason.strip()
    if detail:
        m["detail"] = detail.strip()
    if caveat:
        m["caveat"] = caveat.strip()
    return m


def _real_features(graph: dict) -> list[str]:
    """id РЕАЛЬНЫХ фич кита из графа (без учебных demo-паспортов из examples/)."""
    out: list[str] = []
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict) or n.get("type") != "feature" or not n.get("id"):
            continue
        if _DEMO_MARKER in str(n.get("blueprint") or ""):
            continue
        out.append(n["id"])
    return out


def _story_edges(graph: dict) -> dict[str, set]:
    """Для каждого звена нити — множество id фич, у которых это ребро ЕСТЬ.

    decision: `motivates` (зачем появилась); work: `builds` (что построило); review: `reviewed`
    (кто проверил); outcome: `targets` (нацелена на измеримый результат)."""
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    return {
        "decision": {e.get("to") for e in edges if e.get("type") == "motivates"},
        "work": {e.get("to") for e in edges if e.get("type") == "builds"},
        "review": {e.get("to") for e in edges if e.get("type") == "reviewed"},
        "outcome": {e.get("from") for e in edges if e.get("type") == "targets"},
    }


def feature_completion_rate(graph: dict) -> dict:
    """Метрика 1: доля фич, дошедших ОТ ИДЕИ ДО РЕЛИЗА (из графа знаний).

    Прокси на существующих данных: фича «дошла idea->release», если у неё В ГРАФЕ есть И решение,
    из которого она появилась (`motivates` — «идея»), И построившая её работа/PR (`builds` —
    «релиз»). Знаменатель — реальные фичи с паспортом; нет ни одной -> честное «не измерено».

    ОГОВОРКА (caveat): «без ручного проектирования конвейера / автономно» кит per-feature НЕ
    записывает, поэтому это доля фич, ДОШЕДШИХ до релиза с записанным провенансом идея+постройка, а
    не доля именно автономных прогонов. Названо прямо, чтобы доля не читалась шире, чем измерено."""
    feats = _real_features(graph)
    if not feats:
        return _metric(
            "feature_completion_rate", "Доля фич, дошедших от идеи до релиза",
            measured=False,
            reason="в проекте нет паспортов фич (features/<id>/blueprint.yaml) — долю считать не от чего")
    es = _story_edges(graph)
    reached = [f for f in feats if f in es["decision"] and f in es["work"]]
    return _metric(
        "feature_completion_rate", "Доля фич, дошедших от идеи до релиза",
        measured=True, value=len(reached) / len(feats),
        numerator=len(reached), denominator=len(feats),
        detail="фича засчитана, если в графе есть и решение-«зачем» (motivates), и построившая её "
               "работа/PR (builds)",
        caveat="«без ручного проектирования конвейера» per-feature не фиксируется — это доля "
               "дошедших до релиза с записанным провенансом идея+постройка, не доля автономных прогонов")


def evidence_coverage(claim_results) -> dict:
    """Метрика 2: доля утверждений кита с реальным evidence — ДОЛЕЙ, а не pass/fail.

    `claim_results` — список записей из `validate_claims.build()` (`{status: ok|drift|error, ...}`).
    Доля покрытия = утверждения со статусом `ok` (evidence реально сошлось с кодом) к общему числу.
    `None` -> «не измерено» (реестр не прочитан на этом слое); пустой реестр -> «не измерено» (доли
    нет). ОГОВОРКА: покрывает объявленный реестр честности `knowledge/claims.yaml`, а не каждое
    прозаическое утверждение кита."""
    if claim_results is None:
        return _metric(
            "evidence_coverage", "Доля утверждений кита с реальным evidence",
            measured=False,
            reason="реестр утверждений (knowledge/claims.yaml) не прочитан на этом слое — "
                   "долю покрытия не вывести")
    total = len(claim_results)
    if total == 0:
        return _metric(
            "evidence_coverage", "Доля утверждений кита с реальным evidence",
            measured=False,
            reason="в реестре утверждений нет ни одной записи — долю покрытия считать не от чего")
    ok = sum(1 for r in claim_results if isinstance(r, dict) and r.get("status") == "ok")
    return _metric(
        "evidence_coverage", "Доля утверждений кита с реальным evidence",
        measured=True, value=ok / total, numerator=ok, denominator=total,
        detail="доля утверждений реестра честности, чьё evidence сошлось с кодом (status=ok)",
        caveat="покрывает объявленный реестр knowledge/claims.yaml, а не каждое прозаическое "
               "утверждение кита")


def product_memory_coverage(graph: dict) -> dict:
    """Метрика 3: доля выпущенных фич с ПОЛНОЙ life story (агрегат поверх Knowledge Graph).

    Полная нить = у фичи замкнуты ВСЕ четыре звена: зачем(decision) -> построено(work) ->
    проверено(review) -> результат(outcome). Знаменатель — реальные фичи; нет ни одной -> «не
    измерено». Это АГРЕГАТ поверх `knowledge_graph`: `gaps()` даёт частичный негатив (списки дыр),
    здесь — доля покрытия."""
    feats = _real_features(graph)
    if not feats:
        return _metric(
            "product_memory_coverage", "Доля выпущенных фич с полной историей жизни",
            measured=False,
            reason="в проекте нет паспортов фич (features/<id>/blueprint.yaml) — долю считать не от чего")
    es = _story_edges(graph)
    full = [f for f in feats if all(f in es[edge] for edge in _FULL_STORY_EDGES)]
    return _metric(
        "product_memory_coverage", "Доля выпущенных фич с полной историей жизни",
        measured=True, value=len(full) / len(feats),
        numerator=len(full), denominator=len(feats),
        detail="фича засчитана, если в графе замкнуты все четыре звена: решение, работа, ревью, результат")


def outcome_coverage() -> dict:
    """Метрика 4 (КАРКАС): доля фич с РЕАЛЬНЫМ результатом после релиза — честно «не измерено».

    Упирается в живую продуктовую аналитику, которой у самого кита нет: без реальных событий/метрик
    исход честно «не накоплен», выдумывать его значило бы врать. Слот стоит каркасом и наполняется
    ВМЕСТЕ с петлёй outcome->learning (общий фронтир, не задваивать параллельную работу)."""
    return _metric(
        "outcome_coverage", "Доля фич с реальным результатом после релиза",
        measured=False,
        reason="у самого кита нет живой продуктовой аналитики — реальный результат после релиза "
               "не накоплен, а выдуманное число было бы враньём",
        detail="каркас-слот: наполняется вместе с петлёй outcome->learning, когда петля замкнётся "
               "на продукте с живой аналитикой")


def learning_to_decision_rate() -> dict:
    """Метрика 5 (КАРКАС): доля решений, опирающихся на прошлые результаты — честно «не измерено».

    Фронтир: требует замкнутой петли обучения (результат -> следующее решение). Без реальных исходов
    нельзя честно сказать, какое решение на них опирается, поэтому слот стоит каркасом."""
    return _metric(
        "learning_to_decision_rate", "Доля решений, опирающихся на прошлые результаты",
        measured=False,
        reason="замкнутой петли «результат -> следующее решение» пока нет — без реальных исходов "
               "нельзя честно сказать, какое решение на них опирается",
        detail="каркас-слот: наполняется вместе с петлёй outcome->learning")


def build_scorecard(child_root, *, claim_results=None) -> dict:
    """Собрать единую карту продукта кита из 5 метрик. Read-only: ничего не пишет.

    Метрики 1 и 3 считаются из графа знаний (`knowledge_graph.build_graph`), метрика 2 — из
    переданных снаружи результатов проверки реестра честности (`claim_results`; см. docstring
    модуля о слоях), метрики 4 и 5 стоят честным каркасом «не измерено».

    -> `{schema_version, kind, metrics: [...5...], measured_count, unmeasured_count}`.
    """
    from ai_ops_kit.intelligence import knowledge_graph as kg
    graph = kg.build_graph(child_root)
    metrics = [
        feature_completion_rate(graph),
        evidence_coverage(claim_results),
        product_memory_coverage(graph),
        outcome_coverage(),
        learning_to_decision_rate(),
    ]
    measured = sum(1 for m in metrics if m["measured"])
    return {"schema_version": 1, "kind": "kit-product-scorecard",
            "metrics": metrics,
            "measured_count": measured,
            "unmeasured_count": len(metrics) - measured}
