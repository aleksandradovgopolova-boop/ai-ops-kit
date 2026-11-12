#!/usr/bin/env python3
"""Карта продукта кита: ЕДИНАЯ первоклассная мера себя из 5 метрик, а не числа возможностей.

ЗАЧЕМ. Внешнее продуктовое ревью (17.09): кит перестаёт мерить развитие ЧИСЛОМ возможностей (34
команды, 36 гейтов, 89 валидаторов) и начинает мерить себя как ПРОДУКТ — пятью метриками. Замер
(`qualification/KIT-AS-PRODUCT-METRICS-MEASUREMENT-2026-09-17.md`): единой карты нет, сырьё для
метрик 2/3/4 разрознено (`validate_claims`, `knowledge_graph.gaps`), 1 и 5 не считаются вовсе.

ЧТО СЧИТАЕТСЯ И ЧТО ЧЕСТНО «НЕ ИЗМЕРЕНО».
  1. evidence_backed_outcome_rate — ГЛАВНАЯ МЕРА продукт-здоровья (с 2026-10-28): доля ФИЧ (единица
     учёта — фича с паспортом), дошедших до ИЗМЕРЕННОГО результата с непрерывной цепочкой
     идея→постройка→замер. СЧИТАЕТСЯ. Строже прежней
     feature_completion_rate (идея→релиз, ~100%): та осталась вспомогательной функцией, но из карты
     ушла — лёгкая мера мерой быть перестала (решение владельца ep-2026-10-28-evidence-backed-north-star).
  2. evidence_coverage        — доля утверждений кита с реальным evidence, ДОЛЕЙ, не pass/fail. Долю
     считает этот слой; сырые результаты проверок реестра честности даёт `validate_claims` (из
     `validation`, entrypoints), поэтому передаются СНАРУЖИ — intelligence её не импортирует (это была
     бы зависимость вверх, тот же инвариант, что у `outcome_insight`). Нет результатов -> «не измерено».
  3. product_memory_coverage  — доля выпущенных фич с ПОЛНОЙ life story (рёбра decision/work/review/
     outcome в графе). СЧИТАЕТСЯ.
  4. outcome_coverage         — доля фич с РЕАЛЬНЫМ результатом после релиза. СЧИТАЕТСЯ (с 23.09):
     из отчётов о результате (`features/<id>/outcome-readout.yaml`) подключённого репозитория.
  5. learning_to_decision_rate — доля решений, опирающихся на прошлые результаты. СЧИТАЕТСЯ (с 23.09):
     из узлов обучения графа (`product-learning/FL-*.yaml`), выведенных ИЗ измеренного результата.

РЯДОМ С ПЯТЁРКОЙ — ОТДЕЛЬНЫЙ ПОКАЗАТЕЛЬ (child_value, с 28.09, направление prove-the-loop #1141/#1116).
Доля РАБОТ КИТА, у которых есть доказательство улучшения хотя бы одной дочки — стрелка «работа кита ->
исход дочки», видимая числом. Он про другую единицу измерения, чем пять метрик (работы кита из
`planning/plan.yaml` + `history/plan-history.yaml`, а не фичи подключённого репозитория), поэтому стоит
рядом отдельной строкой, а не шестым пунктом карты. Инвариант направления: нет доказательства -> доля
честно низкая, а не приукрашенная. Показывается СТРОКОЙ, не блокирующей проверкой (гейт был бы ростом
вширь, ровно тем, что ревью запрещает).

ПОЧЕМУ 4 И 5 ПЕРЕСТАЛИ БЫТЬ КАРКАСОМ (23.09.2026). Они стояли «не измерено» с причиной «у самого
кита нет живой аналитики» — и эта причина ездила в КАЖДЫЙ подключённый репозиторий. На ии-среде, где
петля замкнута на реальных числах (фича `analytics-visit-tracking`: было 0 -> стало 19 при цели 20,
вердикт из чисел, урок выведен и подшит к следующему шагу), карта продукта всё равно печатала «у
самого кита нет аналитики» — то есть говорила о ките там, где спрашивали о продукте. Обе функции не
принимали аргументов и ни во что не смотрели. Теперь смотрят.

ИНВАРИАНТ (ядро работы, не деталь). ЧЕСТНОСТЬ ПРЕВЫШЕ ПОЛНОТЫ: нет данных -> метрика в состоянии
`measured=False` с причиной по-русски, НИКОГДА выдуманное число. «Не знаю» и «в порядке» — разные
состояния (тот же принцип, что в `knowledge_graph.gaps` и `health_common`).

Слой: `intelligence` (читает данные ядра через `knowledge_graph`; наверх — `validation` — НЕ
импортирует). Read-only: ничего не пишет.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import yaml

from ai_ops_kit.shared.gitio import git


def _text(v) -> str:
    return str(v or "").strip()


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


def evidence_backed_outcome_rate(graph: dict, child_root) -> dict:
    """Метрика 1 (единственная ГЛАВНАЯ МЕРА продукта с 2026-10-28, решение владельца
    ep-2026-10-28-evidence-backed-north-star): доля ФИЧ (единица учёта — фича с паспортом), дошедших до
    ИЗМЕРЕННОГО результата с НЕПРЕРЫВНОЙ цепочкой доказательств. TTVO (время идея→проверенный PR) и
    «доля фич идея→релиз» (feature_completion_rate) — вспомогательные показатели. Контракт метрик —
    context/product/MetricCatalog.md; скорость доставки не заменяет измеренный результат.

    Строже прежней метрики 1 (`feature_completion_rate`, идея→релиз, бралась на ~100% и потому мерой
    быть перестала): здесь должна быть замкнута ВСЯ цепочка идея (`motivates`) → постройка (`builds`) →
    ИЗМЕРЕННЫЙ результат (`features/<id>/outcome-readout.yaml` со снятым числом и названным
    `target_met`, см. `_measured_readouts`). Разрыв на любом звене — не засчитано.

    Знаменатель — реальные фичи с паспортом; нет ни одной -> «не измерено». Фичи есть, ни у одной
    цепочка не замкнута -> ЧЕСТНЫЙ НОЛЬ, а не «не измерено»: «ни одна фича не дошла до измеренного
    результата» — это знание (тот же разбор, что у `outcome_coverage`). Ровно к этому смена меры и
    ведёт: заглавное число честно низкое, пока петля не замкнута на измеренном результате.

    ОГОВОРКА: «результат измерен» не равно «цель взята» (`target_met: no` входит наравне с `yes` —
    мера про НАЛИЧИЕ непрерывной цепочки до замера, не про знак итога). Идея→релиз без замера сюда НЕ
    попадает — это и есть разница с прежней «долей фич идея→релиз».
    """
    feats = _real_features(graph)
    if not feats:
        return _metric(
            "evidence_backed_outcome_rate",
            "Доля фич с непрерывной цепочкой до измеренного результата",
            measured=False,
            reason="в проекте нет паспортов фич (features/<id>/blueprint.yaml) — долю считать не от чего")
    es = _story_edges(graph)
    measured = _measured_readouts(child_root)
    chained = [f for f in feats if f in es["decision"] and f in es["work"] and f in measured]
    return _metric(
        "evidence_backed_outcome_rate",
        "Доля фич с непрерывной цепочкой до измеренного результата",
        measured=True, value=len(chained) / len(feats),
        numerator=len(chained), denominator=len(feats),
        detail="единица учёта — ФИЧА с паспортом (features/<id>/blueprint.yaml); знаменатель — все "
               "такие фичи, числитель — те, у кого замкнута ВСЯ цепочка идея (motivates) -> постройка "
               "(builds) -> измеренный результат (outcome-readout со снятым числом и target_met ∈ "
               "{yes,no}); окно — на момент сборки карты; исключения — учебные demo-паспорта examples/",
        caveat="«результат измерен» не равно «цель взята» (target_met: no входит наравне с yes); "
               "идея→релиз без замера сюда не входит — мера строже прежней «доли фич идея→релиз» "
               "(feature_completion_rate остаётся вспомогательным сигналом, заглавной мерой быть перестал)")


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


# Засчитываемый вердикт замера. `unknown` — честное «мерили, но не узнали» — сюда НЕ входит.
# Зеркалит `validation.validate_product_objects.TARGET_MET` минус unknown; импортировать оттуда
# нельзя — это зависимость вверх на слой `validation` (инвариант слоёв, см. docstring модуля).
_COUNTED_TARGET_MET = ("yes", "no")


def _is_number(v) -> bool:
    """Конечный замер: bool/NaN/∞ не числа результата, большие int сохраняют точность."""
    return (isinstance(v, int) and not isinstance(v, bool)
            or isinstance(v, float) and math.isfinite(v))


def _measured_readouts(child_root) -> dict:
    """{id фичи: отчёт} для фич, у которых результат ДЕЙСТВИТЕЛЬНО замерен и evidence ГОДНОЕ.

    Замерен = есть `features/<id>/outcome-readout.yaml` (kind OutcomeReadout), и его evidence проходит
    проверку ДОПУСТИМОСТИ, а не только наличия (#1399):
      * `measured.value` — конечное число (строка, bool, NaN/∞, пусто — НЕ замер);
      * `target_met` ∈ {yes, no} — объявленный исход; `unknown` не считается (честное «не узнали»),
        выдуманное значение («made-up») отвергается;
      * отчёт ПРИНАДЛЕЖИТ своей фиче: если объявлено поле `feature`, оно обязано совпасть с именем
        каталога — чужой feature id не засчитывается за эту фичу.
    Проверка наличия без проверки годности раньше завышала долю (отчёт с чужим id, нечисловым
    значением и выдуманным target_met давал 1/1).

    Читается напрямую с диска, а не через `validation`: тот слой выше (инвариант модуля).
    """
    import yaml

    out: dict = {}
    root = Path(child_root)
    for path in sorted(root.glob("features/*/outcome-readout.yaml")):
        # Нечитаемый или битый отчёт — НЕ замер: карта продукта не падает из-за одного файла, но и
        # не засчитывает его как результат. Ловим ровно две причины (файл и YAML), а не всё подряд.
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            doc = None
        if not isinstance(doc, dict) or doc.get("kind") != "OutcomeReadout":
            continue
        measured = doc.get("measured")
        if not isinstance(measured, dict) or not _is_number(measured.get("value")):
            continue
        if doc.get("target_met") not in _COUNTED_TARGET_MET:
            continue
        declared = _text(doc.get("feature"))
        if declared and declared != path.parent.name:
            continue  # чужой feature id — отчёт не принадлежит этой фиче, за неё не засчитываем
        out[path.parent.name] = doc
    return out


def outcome_coverage(graph: dict, child_root) -> dict:
    """Метрика 4: доля фич с РЕАЛЬНЫМ результатом после релиза.

    Числитель — фичи, у которых снят отчёт о результате с числом и названным `target_met`.
    Знаменатель — реальные фичи проекта. Нет ни одной фичи -> «не измерено» (доли не от чего
    считать). Фичи есть, замеров нет -> ЧЕСТНЫЙ НОЛЬ, а не «не измерено»: «ни у одной фичи результат
    не замерен» — это знание, а не его отсутствие (тот же разбор, что у метрики 3).

    ОГОВОРКА: «результат замерен» не равно «цель взята». Недобравшая цель (`target_met: no`) входит
    в долю наравне со взятой — метрика про НАЛИЧИЕ измеренного итога, не про его знак.
    """
    feats = _real_features(graph)
    if not feats:
        return _metric(
            "outcome_coverage", "Доля фич с реальным результатом после релиза",
            measured=False,
            reason="в проекте нет паспортов фич (features/<id>/blueprint.yaml) — долю считать не от чего")
    have = [f for f in feats if f in _measured_readouts(child_root)]
    return _metric(
        "outcome_coverage", "Доля фич с реальным результатом после релиза",
        measured=True, value=len(have) / len(feats),
        numerator=len(have), denominator=len(feats),
        detail="фича засчитана, если снят отчёт о результате (features/<id>/outcome-readout.yaml) "
               "со снятым числом и названным target_met; unknown замером не считается",
        caveat="«результат замерен» не равно «цель взята»: недобравшая цель входит в долю наравне "
               "со взятой — метрика про наличие измеренного итога, не про его знак")


def learning_to_decision_rate(graph: dict, child_root) -> dict:
    """Метрика 5: доля решений, опирающихся на прошлые результаты — замкнута ли петля обучения.

    Знаменатель — фичи с ИЗМЕРЕННЫМ результатом (метрика 4): пока результата нет, «решение на него
    опирается» не про что спрашивать. Числитель — те из них, у кого в графе есть узел обучения,
    выведенный ИЗ этого результата (`insight -derived-from-> outcome`) И подшитый к следующему шагу
    (`insight -feeds-> ...`). Замеров нет -> «не измерено» с ЭТОЙ причиной, а не с рассказом про кит.

    ОГОВОРКА: считается «результат -> следующий шаг», а не каждое решение проекта. Решение, принятое
    человеком по прочитанному результату и нигде не записанное, сюда не попадёт — кит меряет то, что
    записано, и не выдаёт молчание за отсутствие.
    """
    readouts = _measured_readouts(child_root)
    measured_feats = [f for f in _real_features(graph) if f in readouts]
    if not measured_feats:
        return _metric(
            "learning_to_decision_rate", "Доля решений, опирающихся на прошлые результаты",
            measured=False,
            reason="ни у одной фичи результат после релиза не замерен — пока нет результата, "
                   "«решение опирается на него» считать не от чего")
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    targets = {e.get("from"): e.get("to") for e in edges if e.get("type") == "targets"}
    derived = {e.get("from"): e.get("to") for e in edges if e.get("type") == "derived-from"}
    feeds_from = {e.get("from") for e in edges if e.get("type") == "feeds"}
    closed = []
    for f in measured_feats:
        outcome = targets.get(f)
        if outcome is None:
            continue                                   # результат снят, но к исходу не подшит
        if any(src in feeds_from and dst == outcome for src, dst in derived.items()):
            closed.append(f)
    return _metric(
        "learning_to_decision_rate", "Доля решений, опирающихся на прошлые результаты",
        measured=True, value=len(closed) / len(measured_feats),
        numerator=len(closed), denominator=len(measured_feats),
        detail="из фич с измеренным результатом засчитаны те, у кого урок выведен ИЗ этого "
               "результата (derived-from) и подшит к следующему шагу (feeds)",
        caveat="считается «результат -> следующий шаг» по записанному в product-learning/, а не "
               "каждое решение проекта: решение, принятое в голове, сюда не попадёт")


# ── Стрелка «работа кита -> исход дочки»: доказана ли ценность построенного для ДОЧЕК ──────────────
#
# ЗАЧЕМ ОТДЕЛЬНЫМ ПОКАЗАТЕЛЕМ, А НЕ ШЕСТОЙ МЕТРИКОЙ КАРТЫ (направление prove-the-loop, #1141/#1116).
# Пять метрик карты меряют ОДИН подключённый репозиторий (его фичи, его исходы). Этот показатель — про
# другую единицу: РАБОТЫ САМОГО КИТА и про то, доказали ли они улучшение ХОТЯ БЫ ОДНОЙ дочки. Единицы
# и знаменатели разные (работы кита, а не фичи репозитория; дочки, а не этот репозиторий), поэтому он
# стоит рядом с картой отдельной строкой, а не подмешивается пятёрке. Строкой, НЕ гейтом: блокирующая
# проверка была бы ростом вширь — ровно тем, что независимое ревью запрещает (#1116).


def _work_child_value(work: dict) -> list[dict]:
    """Валидные доказательства ценности для дочки, ОБЪЯВЛЕННЫЕ на работе кита. Пусто -> [].

    Доказательство засчитано, только если несёт И названный дочерний продукт (`child`/`repo`), И
    ссылку на evidence (`evidence`) — где улучшение зафиксировано. Голый `child_value: true` или запись
    без источника НЕ считается: это было бы самолюбованием без доказательства, ровно тот риск, против
    которого заведено направление. Форма — один блок или список блоков."""
    if not isinstance(work, dict):
        return []
    raw = work.get("child_value")
    entries = raw if isinstance(raw, list) else [raw]
    proven: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        child = _text(e.get("child") or e.get("repo"))
        evidence = _text(e.get("evidence"))
        if child and evidence:
            proven.append({"child": child, "evidence": evidence})
    return proven


def _kit_works(kit_root) -> list[dict]:
    """Все работы кита: активный план + закрытые в истории. По одной записи на работу (по id).

    Читаются ровно два источника, по которым кит строит нить истории (см. `knowledge_graph`):
    активные `planning/plan.yaml` (`work`) и закрытые `history/plan-history.yaml` (`work`). Работа без
    id пропускается; тёзки по id схлопываются в первое вхождение, чтобы знаменатель не задваивался.
    Битый/нечитаемый файл пропускается (карта не падает из-за одного файла), а не считается пустотой.
    """
    import yaml

    root = Path(kit_root)
    seen: set[str] = set()
    works: list[dict] = []
    for rel in ("planning/plan.yaml", "history/plan-history.yaml"):
        try:
            doc = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        for w in doc.get("work") or []:
            wid = _text(w.get("id")).lower() if isinstance(w, dict) else ""
            if not wid or wid in seen:
                continue
            seen.add(wid)
            works.append(w)
    return works


def child_value_share(kit_root) -> dict:
    """Показатель: доля РАБОТ КИТА, у которых есть доказательство улучшения хотя бы одной дочки.

    Знаменатель — все работы кита (активные + закрытые). Числитель — работы, несущие записанное
    доказательство `child_value` (названный дочерний продукт + ссылка на evidence). Нет ни одной работы
    -> «не измерено» (долю считать не от чего). Работы есть, доказательств нет -> ЧЕСТНЫЙ НОЛЬ, а не
    «не измерено»: «ни у одной работы ценность для дочки не доказана» — это знание, а не его отсутствие
    (тот же разбор, что у `outcome_coverage`), и ровно то, что мандат направления велит показать честно.

    ОГОВОРКА: это доля работ с записанной НА СТОРОНЕ КИТА стрелкой «работа -> исход дочки»; само число
    улучшения живёт в outcome-readout дочки. Работа, реально помогшая дочке, но не подшившая
    доказательство, сюда не попадёт — кит меряет записанное и не выдаёт молчание за доказательство.
    """
    works = _kit_works(kit_root)
    if not works:
        return _metric(
            "child_value_share", "Доля работ кита с доказательством улучшения дочки",
            measured=False,
            reason="в проекте нет работ кита (planning/plan.yaml, history/plan-history.yaml) — "
                   "долю считать не от чего")
    proven = [w for w in works if _work_child_value(w)]
    return _metric(
        "child_value_share", "Доля работ кита с доказательством улучшения дочки",
        measured=True, value=len(proven) / len(works),
        numerator=len(proven), denominator=len(works),
        detail="работа засчитана, если несёт записанное доказательство child_value: названный "
               "дочерний продукт (child/repo) и ссылку на evidence, где улучшение зафиксировано",
        caveat="это доля работ с записанной на стороне кита стрелкой «работа -> исход дочки»; само "
               "число улучшения живёт в outcome-readout дочки. Нет доказательства -> доля честно "
               "низкая, а не приукрашенная")


# ── #1514: успевает ли проверка за генерацией кода ─────────────────────────────────────────
# Успевает ли проверка за генерацией кода — строка карты продукта (#1514).
# 
# ЗАЧЕМ. Потолки размера ловят рост, но только поднимаются; построенное и не подключённое копится.
# Быстрая поставка выглядит успехом, пока разрыв «пишется больше, чем проверяется» не становится
# долгом. Показателя этого разрыва не было ни у кита, ни у проектов.
# 
# ЧТО СЧИТАЕТСЯ — только из того, что уже лежит в репозитории, без сети и новых сборщиков:
#   * прирост кода за окно (Git: добавлено/удалено строк в файлах кода, без тестов);
#   * доля прироста тестов к приросту кода (Git) — грубая мера, успевают ли тесты за кодом;
#   * подъёмы потолков за окно (ленты `raises` реестров потолков, если они есть в репозитории);
#   * построенное, но не подключённое (перепись из карты возможностей: её делает только сам кит);
#   * доля изменений с независимым ИИ-ревью — след такого ревью в репозитории не сохраняется,
#     поэтому честно «не измерено». Ревью человеком мерой не является (решение 11.11.2026).
# 
# ИНВАРИАНТ. Нет данных -> «не измерено» с причиной, никогда не ноль. Это строка карты, а не проверка,
# которая что-то блокирует. Слой `intelligence`, только чтение.

WINDOW_DAYS = 90
CODE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".java", ".kt", ".swift",
                           ".rs", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".scala", ".vue"})
# Не код проекта: копия кита в проекте (судится отдельно) и сторонние/собранные папки.
NOT_PROJECT_CODE = (".ai/managed/", "node_modules/", "vendor/", "dist/", "build/", ".venv/")
CEILING_LEDGERS = ("quality/delivery-budget.yaml", "packages/*-baseline.yaml")


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    return (any(part in ("test", "tests", "__tests__", "spec") for part in p.parts[:-1])
            or name.startswith("test_") or name.endswith(("_test.py", "_test.go"))
            or ".test." in name or ".spec." in name)


def code_churn(root, since: date) -> dict | None:
    """{code_added, code_removed, test_added, commits} за окно; None — Git недоступен."""
    rc, out, _ = git(root, "log", f"--since={since.isoformat()}", "--no-merges", "--numstat",
                     "--format=@%H", timeout=60)
    if rc != 0:
        return None
    totals = {"code_added": 0, "code_removed": 0, "test_added": 0, "commits": 0}
    for line in out.splitlines():
        if line.startswith("@"):
            totals["commits"] += 1
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue                                  # двоичный файл или пустая строка
        path = parts[2].split(" => ")[-1].rstrip("}")
        if (PurePosixPath(path).suffix not in CODE_SUFFIXES
                or any(path.startswith(d) or f"/{d}" in path for d in NOT_PROJECT_CODE)):
            continue
        if is_test_path(path):
            totals["test_added"] += int(parts[0])
        else:
            totals["code_added"] += int(parts[0])
            totals["code_removed"] += int(parts[1])
    return totals


def ceiling_raises(root, since: date) -> int | None:
    """Число записей о подъёме потолка с датой в окне; None — реестров потолков в репозитории нет."""
    root = Path(root)
    ledgers = [p for pattern in CEILING_LEDGERS for p in sorted(root.glob(pattern))]
    if not ledgers:
        return None
    count = 0
    for ledger in ledgers:
        try:
            data = yaml.safe_load(ledger.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return None                               # битый реестр — не ноль, а неизвестность
        entries = (data.get("raises") or []) if isinstance(data, dict) else []
        for entry in entries:
            stamp = (entry.get("at") or entry.get("date")) if isinstance(entry, dict) else None
            try:
                when = date.fromisoformat(str(stamp)[:10])
            except ValueError:
                continue
            count += when >= since
    return count


def unwired_modules(root) -> list[str] | None:
    """Построенное, но не подключённое — из сгенерированной карты возможностей кита.

    Перепись делает только сам кит (`docs/capability-map.md`, её свежесть держит тест); в проекте
    карты нет -> None, то есть «не измерено», а не ноль."""
    path = Path(root) / "docs" / "capability-map.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return re.findall(r"^\| `([^`]+)` \| built≠wired \|", text, flags=re.M)


def _count(mid, title, value, detail):
    return {"id": mid, "title": title, "measured": True, "unit": "count", "value": value, "detail": detail}


def verification_pace(root, *, now: datetime | None = None, days: int = WINDOW_DAYS) -> dict:
    """Строка «успевает ли проверка за генерацией» из частей; каждая честно измерена или нет."""
    since = (now or datetime.now(timezone.utc)).date() - timedelta(days=days)
    churn = code_churn(root, since)
    parts = []
    if churn is None:
        no_git = "история Git недоступна"
        parts += [_metric("code_growth", "Прирост кода", measured=False, reason=no_git),
                  _metric("tests_keep_pace", "Прирост тестов к приросту кода", measured=False, reason=no_git)]
    else:
        net = churn["code_added"] - churn["code_removed"]
        parts.append(_count("code_growth", "Прирост кода, строк", net,
                            f"добавлено {churn['code_added']}, удалено {churn['code_removed']}, "
                            f"коммитов {churn['commits']}"))
        if churn["code_added"]:
            parts.append(_metric("tests_keep_pace", "Прирост тестов к приросту кода", measured=True,
                                 value=churn["test_added"] / churn["code_added"],
                                 numerator=churn["test_added"], denominator=churn["code_added"],
                                 caveat="строки, а не покрытие: грубая мера, успевают ли тесты за кодом"))
        else:
            parts.append(_metric("tests_keep_pace", "Прирост тестов к приросту кода", measured=False,
                                 reason="за период код не прибавлялся — долю считать не от чего"))
    parts.append(_metric("independent_review_share", "Доля изменений с независимым ИИ-ревью",
                         measured=False,
                         reason="след независимого ревью слитых изменений в репозитории не сохраняется"))
    raises = ceiling_raises(root, since)
    parts.append(_metric("ceiling_raises", "Подъёмы потолков", measured=False,
                         reason="в репозитории нет реестров потолков с лентой подъёмов")
                 if raises is None else
                 _count("ceiling_raises", "Подъёмы потолков", raises, "записи о подъёме за период"))
    unwired = unwired_modules(root)
    parts.append(_metric("unwired", "Построено, но не подключено", measured=False,
                         reason="перепись неподключённого кода умеет только сам кит")
                 if unwired is None else
                 _count("unwired", "Построено, но не подключено", len(unwired), "модулей без входа"))
    return {"id": "verification_pace", "title": f"Успевает ли проверка за генерацией (за {days} дней)",
            "window_days": days, "since": since.isoformat(),
            "measured": any(p["measured"] for p in parts), "parts": parts}


def build_scorecard(child_root, *, claim_results=None) -> dict:
    """Собрать единую карту продукта кита из 5 метрик. Read-only: ничего не пишет.

    Метрики 1, 3, 4 и 5 считаются из данных подключённого репозитория (граф знаний
    `knowledge_graph.build_graph` плюс отчёты о результате `features/<id>/outcome-readout.yaml`),
    метрика 2 — из переданных снаружи результатов проверки реестра честности (`claim_results`;
    см. docstring модуля о слоях). Любая из пяти честно встаёт в «не измерено» с причиной, когда
    данных нет.

    Рядом с пятёркой — ОТДЕЛЬНЫМ показателем `child_value` — доля работ кита с доказательством
    улучшения дочки (стрелка «работа кита -> исход дочки»). Он про другую единицу (работы кита, а не
    фичи репозитория), поэтому стоит рядом, а не шестым в `metrics`; строкой, не гейтом (#1141/#1116).

    Ещё одна строка рядом — `verification_pace` (#1514): успевает ли проверка за генерацией кода.

    -> `{schema_version, kind, metrics: [...5...], measured_count, unmeasured_count, child_value,
    verification_pace}`.
    """
    from ai_ops_kit.intelligence import knowledge_graph as kg
    graph = kg.build_graph(child_root)
    metrics = [
        evidence_backed_outcome_rate(graph, child_root),
        evidence_coverage(claim_results),
        product_memory_coverage(graph),
        outcome_coverage(graph, child_root),
        learning_to_decision_rate(graph, child_root),
    ]
    measured = sum(1 for m in metrics if m["measured"])
    return {"schema_version": 1, "kind": "kit-product-scorecard",
            "metrics": metrics,
            "measured_count": measured,
            "unmeasured_count": len(metrics) - measured,
            "child_value": child_value_share(child_root),
            "verification_pace": verification_pace(child_root)}
