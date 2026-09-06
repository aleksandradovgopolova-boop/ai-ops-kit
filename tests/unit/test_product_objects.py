"""Четыре управляющих объекта продукта: проверяется СУЩЕСТВО, а не наличие разделов (2026-08-14).

ПОВОД. Кит умел потребовать Problem Statement, JTBD и гипотезы — то есть проверял, что раздел
ЗАПОЛНЕН. Из этой же разницы вырос B2-14: `spec-coverage` сообщал `acceptance_criteria: complete`,
а критерий выполнен не был, потому что `complete` там означает «раздел заполнен». Продуктовый слой
рискует повторить это в большем масштабе — хорошо оформленным, но слабым продуктовым пакетом.

Что защищается:
  * positive     — полные объекты проходят, и сверка readout с контрактом сходится;
  * fail-closed  — утверждение без основания, решение с одним вариантом, решение без условия
                   пересмотра, baseline без даты, контракт без guardrails и правил решения, readout
                   без контракта и с подменой метрики: каждый случай называется ошибкой;
  * side-effect  — умолчание о заранее объявленном guardrail ловится сверкой, а не читается как
                   «всё в порядке».
"""
from __future__ import annotations

import pytest

from ai_ops_kit.validation import validate_product_objects as vpo

BRIEF = {
    "schema_version": 1, "kind": "OpportunityBrief",
    "user": "владелец продукта без опыта в AI",
    "situation": "первый запуск после установки кита",
    "problem": "не понимает, с чего начать",
    "desired_outcome": "первая полезная работа взята за 10 минут",
    "why_now": "выросло число установок без первой задачи",
    "evidence": [{"claim": "40% сессий обрываются на выборе провайдера",
                  "source": "аналитика, provider_selected, 01–14.08"}],
    "unknowns": [], "assumptions": [],
}
DECISION = {
    "schema_version": 1, "kind": "ProductDecisionRecord",
    "question": "как устроить выбор провайдера",
    "opportunity": "features/x/opportunity-brief.yaml",
    "options": [{"id": "wizard", "summary": "мастер", "pros": ["меньше нагрузки"], "cons": ["дольше"]},
                {"id": "form", "summary": "одна форма", "pros": ["быстро"], "cons": ["страшно"]}],
    "recommendation": "wizard", "owner_decision": "wizard", "confidence": "medium",
    "not_doing": "не трогаем импорт из внешних систем",
    "revisit_when": "если отказы не упадут ниже 25% за две недели",
}
CONTRACT = {
    "schema_version": 1, "kind": "OutcomeContract",
    "decision": "features/x/product-decision.yaml",
    "primary_metric": {"name": "completion_rate", "source": "аналитика"},
    "baseline": {"value": 0.58, "measured_at": "2026-08-14", "source": "дашборд onboarding"},
    "target": {"value": 0.75, "by": "2026-09-15"},
    "guardrails": [{"name": "время до первого агента", "must_not_exceed": "90 сек"}],
    "events": ["provider_selected"], "evaluation_period": "4 недели",
    "decision_rules": {"continue": "раскатываем", "change": "продлеваем", "stop": "откатываем"},
}
READOUT = {
    "schema_version": 1, "kind": "OutcomeReadout",
    "contract": "features/x/outcome-contract.yaml",
    "measured": {"metric": "completion_rate", "value": 0.71, "measured_at": "2026-09-16"},
    "target_met": "no", "hypothesis": "inconclusive",
    "guardrails_observed": [{"name": "время до первого агента", "value": "86 сек", "within": True}],
    "unexpected_effects": [],
    "next_decision": "продлить окно по правилу change",
    "back_to_discovery": "отказы сместились на третий шаг — это новая возможность",
}


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("obj", [BRIEF, DECISION, CONTRACT, READOUT],
                         ids=["brief", "decision", "contract", "readout"])
def test_a_complete_object_passes(obj):
    assert vpo.check(obj) == [], vpo.check(obj)


def test_readout_matching_its_contract_cross_checks_clean():
    assert vpo.cross_check(CONTRACT, READOUT) == []


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_a_claim_without_a_source_is_rejected():
    """Утверждение о продукте обязано называть основание — иначе это мнение в форме факта."""
    bad = {**BRIEF, "evidence": [{"claim": "пользователям неудобно"}]}

    assert any("без source" in e for e in vpo.check(bad)), vpo.check(bad)


def test_no_evidence_requires_a_named_gap():
    """Пустой список доказательств законен — молчание о том, чего не хватает, нет.

    «Не знаю» и «не сказал» — разные состояния: первое полезно и позволяет спланировать проверку,
    второе выглядит как знание.
    """
    silent = {**BRIEF, "evidence": []}
    named = {**BRIEF, "evidence": [], "evidence_gap": "нет данных по мобильным сессиям"}

    assert any("evidence_gap" in e for e in vpo.check(silent)), vpo.check(silent)
    assert vpo.check(named) == [], vpo.check(named)


def test_a_single_option_is_not_a_decision():
    """Один вариант — оформление уже принятого, а не выбор."""
    bad = {**DECISION, "options": DECISION["options"][:1]}

    assert any("не решение" in e for e in vpo.check(bad)), vpo.check(bad)


def test_an_option_without_cons_was_not_considered():
    """Вариант без минусов не рассматривали, а описывали."""
    bad = {**DECISION, "options": [{**DECISION["options"][0], "cons": []},
                                   DECISION["options"][1]]}

    assert any("без cons" in e for e in vpo.check(bad)), vpo.check(bad)


def test_a_decision_without_a_revisit_condition_is_rejected():
    """Решение без условия пересмотра нельзя ни подтвердить, ни отменить."""
    bad = {k: v for k, v in DECISION.items() if k != "revisit_when"}

    assert any("revisit_when" in e for e in vpo.check(bad)), vpo.check(bad)


def test_a_deferred_decision_still_needs_a_reason():
    """Отложенное решение — тоже решение, и оно обязано назвать основание."""
    bad = {**DECISION, "owner_decision": "deferred"}

    assert any("отложено без причины" in e for e in vpo.check(bad)), vpo.check(bad)


def test_a_baseline_without_a_date_is_a_number_from_thin_air():
    bad = {**CONTRACT, "baseline": {"value": 0.58}}
    errors = vpo.check(bad)

    assert any("measured_at" in e for e in errors) and any("source" in e for e in errors), errors


def test_a_contract_without_guardrails_or_rules_is_rejected():
    """Без guardrails «цель достигнута» может означать «сломали соседнее»; без правил решения
    результат всегда толкуется в пользу сделанного."""
    no_gr = {k: v for k, v in CONTRACT.items() if k != "guardrails"}
    no_rules = {**CONTRACT, "decision_rules": {"continue": "да"}}

    assert any("guardrails" in e for e in vpo.check(no_gr)), vpo.check(no_gr)
    assert any("decision_rules" in e for e in vpo.check(no_rules)), vpo.check(no_rules)


def test_a_readout_without_a_contract_is_a_story():
    bad = {k: v for k, v in READOUT.items() if k != "contract"}

    assert any("contract" in e for e in vpo.check(bad)), vpo.check(bad)


def test_unknown_target_requires_a_reason():
    """Неизмеренное обязано называть, ПОЧЕМУ оно неизмеренное — тот же инвариант, что `unavailable != 0`."""
    bad = {**READOUT, "target_met": "unknown"}

    assert any("unknown_reason" in e or "почему" in e for e in vpo.check(bad)), vpo.check(bad)


def test_an_alien_artifact_is_refused():
    """Чужой артефакт не «наверное brief», а отказ: тихое приведение приняло бы что угодно."""
    assert any("kind" in e for e in vpo.check({"kind": "совсем-другое", "schema_version": 1}))


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_a_silently_dropped_guardrail_is_caught_by_the_cross_check():
    """Умолчание о заранее объявленном guardrail читается как «всё в порядке» — и это ловится.

    Это и есть главный смысл сверки: readout честно заполняется по удобным метрикам, а просевший
    guardrail просто не упоминается. Проверяется ПРЕЖДЕ вердикта о самом readout: сам по себе он
    остаётся валидным, и потому дыра была бы невидимой.
    """
    quiet = {**READOUT, "guardrails_observed": []}

    assert vpo.check(quiet) == [], "readout валиден сам по себе — дыра именно в сверке"
    errors = vpo.cross_check(CONTRACT, quiet)
    assert any("не отчитаны" in e and "время до первого агента" in e for e in errors), errors


def test_a_swapped_metric_is_caught():
    """Подмена метрики: отчитались по удобной, а обещали другую."""
    swapped = {**READOUT, "measured": {**READOUT["measured"], "metric": "clicks"}}

    assert any("подмена метрики" in e for e in vpo.cross_check(CONTRACT, swapped))


# ─── outcome как узел графа: проекция + трассировка (#544) ────────────────────────────────────────

from validate_knowledge_graph import load_dictionary, validate_graph  # noqa: E402


def _feature_to_outcome_graph(outcome_fragment):
    """Полный путь goal → initiative → epic → feature + фрагмент проекции outcome."""
    return {
        "schema_version": 1, "kind": "knowledge-graph",
        "nodes": [
            {"id": "grow-repeat", "type": "goal", "title": "Рост повторных покупок"},
            {"id": "onboarding-init", "type": "initiative", "title": "Ускорить первый запуск"},
            {"id": "provider-epic", "type": "epic", "title": "Выбор провайдера"},
            {"id": "express-checkout", "type": "feature", "title": "Экспресс-чекаут"},
            *outcome_fragment["nodes"],
        ],
        "edges": [
            {"from": "grow-repeat", "type": "contains", "to": "onboarding-init"},
            {"from": "onboarding-init", "type": "contains", "to": "provider-epic"},
            {"from": "provider-epic", "type": "contains", "to": "express-checkout"},
            *outcome_fragment["edges"],
        ],
    }


def test_outcome_is_a_declared_entity_type_with_allowed_relations():
    """`outcome` — тип первого класса в словаре, и ребро feature→outcome разрешено."""
    types, rels = load_dictionary()

    assert "outcome" in types
    assert ("feature", "targets", "outcome") in rels


def test_projection_yields_an_outcome_node_mirroring_the_contract():
    """Проекция контракта+отчёта даёт ОДИН узел outcome с baseline/target/measured/verdict."""
    frag = vpo.project_outcome(CONTRACT, READOUT, feature="express-checkout")
    (node,) = frag["nodes"]

    assert node["type"] == "outcome"
    assert node["baseline"] == 0.58 and node["target"] == 0.75
    assert node["measured"] == 0.71 and node["verdict"] == "no"
    assert node["guardrails"] == ["время до первого агента"]
    assert {"from": "express-checkout", "type": "targets", "to": node["id"]} in frag["edges"]


def test_projection_without_a_readout_is_pending_not_met():
    """Без отчёта вердикт — `pending` (состояние), а не выдуманный «met»/«unknown»."""
    node = vpo.project_outcome(CONTRACT)["nodes"][0]

    assert node["verdict"] == "pending"
    assert "measured" not in node  # неизмеренное не подставляется нулём


def test_projected_outcome_fragment_is_a_valid_graph(tmp_path):
    """Спроецированный outcome встраивается в knowledge-graph и проходит валидатор связей."""
    import yaml

    frag = vpo.project_outcome(CONTRACT, READOUT, feature="express-checkout")
    graph = _feature_to_outcome_graph(frag)
    p = tmp_path / "graph.yaml"
    p.write_text(yaml.safe_dump(graph, allow_unicode=True), encoding="utf-8")
    types, rels = load_dictionary()

    assert validate_graph(p, types, rels) == []


def test_trace_returns_the_full_goal_to_outcome_chain():
    """«Зачем существует функция»: цепочка goal → … → feature и привязанный outcome, без пробелов."""
    frag = vpo.project_outcome(CONTRACT, READOUT, feature="express-checkout")
    trace = vpo.trace_feature_rationale(_feature_to_outcome_graph(frag), "express-checkout")

    assert [n["type"] for n in trace["chain"]] == ["goal", "initiative", "epic", "feature"]
    assert trace["outcome"] is not None and trace["outcome"]["verdict"] == "no"
    assert trace["gaps"] == []


def test_trace_reports_honest_gaps_instead_of_fabricating_links():
    """Неполный граф (нет цели сверху, нет outcome) отдаёт частичную цепочку с НАЗВАННЫМИ пробелами."""
    lonely = {
        "schema_version": 1, "kind": "knowledge-graph",
        "nodes": [{"id": "express-checkout", "type": "feature", "title": "Экспресс-чекаут"}],
        "edges": [],
    }
    trace = vpo.trace_feature_rationale(lonely, "express-checkout")

    assert [n["id"] for n in trace["chain"]] == ["express-checkout"]
    assert trace["outcome"] is None
    assert any("до цели" in g for g in trace["gaps"])
    assert any("outcome" in g for g in trace["gaps"])
