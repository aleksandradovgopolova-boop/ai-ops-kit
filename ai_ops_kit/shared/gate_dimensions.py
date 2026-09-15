#!/usr/bin/env python3
"""Карта gate_id -> короткая ПРОДУКТОВАЯ фраза «что проверено» + честный свод для readout.

Живёт в foundation (`shared`), а НЕ в `ui` или `gates`, потому что её читают ДВА пакета выше по
дереву импортов: `ui` (presenter_formatters.from_review — путь `review`) и `engine`
(pipeline_stages — путь ПРОГОНА). Оба импортируют её ВНИЗ (ui -> shared, engine -> shared), и ни
один инвариант слоёв не нарушен. Положить карту в `ui` означало бы восходящий импорт для engine
(запрещён: engine НЕ импортирует ui), в `gates` — восходящий для ui (ui в слое ниже gates). shared
не импортирует из кита НИЧЕГО: это чистая таблица + чистый форматтер над обычным dict.

#958 (verified_is_shown_as_trust_not_gate_list): в момент «Проверено» человек видит ОСНОВАНИЕ
доверять — какие продуктовые измерения приняты и КЕМ (детерминированная машина vs независимый
ревьюер), — а не число «гейты 3/3» и не внутренний id гейта. Ядро кита — «no false green»:
называем ТОЛЬКО реально пройденные измерения и НЕ выдаём мнение независимого ревьюера за машинную
проверку.
"""
from __future__ import annotations

# id гейта -> короткая ПРОДУКТОВАЯ фраза (винительный падеж: «...проверила/принял: X»). Ключи —
# РЕАЛЬНЫЕ гейты quality/gates.yaml. Гейта нет в карте -> смысл НЕ выдумываем: пропуск, свод падает
# на нейтральную формулировку. Две группы соответствуют двум источникам доверия:
#   машинные (validator: детерминированный CLI/чек)  и  ai-review (заключение независимого судьи).
GATE_PRODUCT_DIMENSION = {
    # ── машинные (детерминированный валидатор: тесты / сборка / схема / CI) ──
    "intake_completeness": "полноту заявки",
    "requirements": "требования",
    "specification": "спецификацию",
    "plan_readiness": "готовность плана",
    "implementation_verification": "реализацию: тесты и сборку",
    "regression_test_evidence": "регрессионные тесты",
    "concurrency_preflight": "конфликты параллельной работы",
    "contour_consistency": "согласованность продуктовой модели",
    "own_medicine": "самопроверку кита",
    "event_contract_consistency": "контракт событий",
    "surface_wiring_consistency": "проводку поверхностей",
    "feature_coverage": "охват функций",
    "deploy_readiness": "готовность к развёртыванию",
    "spec_synchronization": "синхронность спецификации",
    "archive_readiness": "готовность к архивации",
    "documentation_updated": "обновление документации",
    "feature_decision_quality": "качество решений по функциям",
    "knowledge_integrity": "целостность знаний",
    "knowledge_freshness": "свежесть знаний",
    # ── ai-review (заключение независимого ревьюера; writer ≠ judge) ──
    "code_review": "код",
    "security": "безопасность",
    "architecture_review": "архитектуру",
    "analytics_design_readiness": "контракт аналитики",
    "analytics_runtime_verification": "поступление аналитики",
    "ux_review": "пользовательский опыт",
    "accessibility_review": "доступность",
    "visual_regression": "визуальную регрессию",
    "design_system_usage": "следование дизайн-системе",
    "ai_eval": "качество AI-функции",
    "ai_red_team": "устойчивость AI-функции к атакам",
    "decision_quality": "качество продуктового решения",
    "release_safety": "безопасность выпуска",
    "observability_readiness": "наблюдаемость",
    "evidence": "доказательную базу",
    "stakeholder_readiness": "готовность для заинтересованных сторон",
    "discovery_completeness": "полноту discovery",
}


def dimensions(gate_ids) -> list:
    """Продуктовые фразы для набора id — пропуская незнакомые (смысл не выдумываем)."""
    return [d for gid in (gate_ids or []) for d in (GATE_PRODUCT_DIMENSION.get(gid),) if d]


def run_verified_lines(evidence_verdict: dict) -> list:
    """Свод «что проверено» ПРОДУКТОВЫМИ словами для readout ПРОГОНА -> список строк (может быть пуст).

    Источник различаем ЧЕСТНО по `evidence_verdict` (веха 4.2, #588): `deterministic` — пройденные
    машинные гейты (валидатор: тест/сборка/схема), `ai_judgment` — пройденные по заключению
    НЕЗАВИСИМОГО ревьюера, `human` — одобренные человеком. Каждый список — ТОЛЬКО пройденные
    (status=pass) гейты, поэтому инвариант «no false green» держится: непройденное сюда не попадает,
    а мнение независимого ревьюера машинной проверкой не зовётся.

    Возвращает пусто, если пройденных гейтов нет: тогда вызывающий НЕ пишет «Проверено» — верифи-
    цировать нечего. Незнакомый пройденный гейт не выдумывает смысл: группа остаётся, но называется
    нейтрально («... проверки пройдены»), а не приписывает измерение, которого в карте нет.
    """
    ev = evidence_verdict or {}
    det = ev.get("deterministic") or []
    aij = ev.get("ai_judgment") or []
    hum = ev.get("human") or []
    lines = []
    if det:
        d = dimensions(det)
        lines.append("машина проверила (тесты, сборка, схемы): "
                     + (", ".join(d) if d else "детерминированные проверки пройдены"))
    if aij:
        d = dimensions(aij)
        lines.append("независимый ревьюер (не тот, кто делал работу) принял: "
                     + (", ".join(d) if d else "замечаний нет"))
    if hum:
        d = dimensions(hum)
        lines.append("человек одобрил: " + (", ".join(d) if d else "получено ручное одобрение"))
    return lines
