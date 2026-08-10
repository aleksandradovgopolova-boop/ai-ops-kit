"""Human Communication Layer: перевод меняет язык, а не факты (v3.35).

  * positive     — UserMessage собирается и рендерится под три аудитории;
  * fail-closed  — сообщение без «что произошло» и вопрос без формулировки не собираются;
                   отсутствие политики — исключение, а не «отрендерим как-нибудь»;
  * side-effect  — `degraded` остаётся `degraded` на всех уровнях, внутренние термины не
                   просачиваются на `product`, а технические детали не ТЕРЯЮТСЯ.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.ui import presenter as PR

# Внутренние имена, которых человек на уровне `product` видеть не должен.
JARGON = ("write_scope", "tested_revision", "GateResult", "preflight_block", "ApprovalRecord",
          "gate:", "SHA")


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_message_contract_shape():
    m = PR.message(status="ok", summary="Готово продвинулись",
                   next_steps=["продолжаю"], technical={"gate": "spec"})
    assert m["kind"] == "user-message"
    assert m["status"] == "ok"
    assert m["technical_details"]["available"] is True


def test_render_answers_four_questions_in_order():
    m = PR.message(status="needs_input", summary="Пока не начинаю.",
                   why_it_matters="Нужно подтверждение.",
                   decision={"question": "разрешить правку auth", "recommendation": "разрешить чтение"},
                   next_steps=["после подтверждения — реализация"])
    out = PR.render(m, audience="product")
    # Решение стоит ПЕРЕД «дальше»: человек видит вопрос раньше плана.
    assert out.index("Нужно от тебя") < out.index("Дальше:")
    assert "Рекомендую:" in out


def test_three_audiences_render():
    for aud in PR.AUDIENCES:
        assert PR.demo(aud)


def test_audience_default_is_product(tmp_path):
    assert PR.audience_from_config(tmp_path) == "product"


def test_audience_from_config(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("communication:\n  audience: technical\n",
                                           encoding="utf-8")
    assert PR.audience_from_config(tmp_path) == "technical"


def test_unknown_audience_falls_back_to_product(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("communication:\n  audience: wizard\n", encoding="utf-8")
    assert PR.audience_from_config(tmp_path) == "product"


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_message_without_summary_is_rejected():
    with pytest.raises(ValueError):
        PR.message(status="ok", summary="   ")


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        PR.message(status="почти готово", summary="что-то")


def test_decision_without_question_is_rejected():
    with pytest.raises(ValueError):
        PR.message(status="needs_input", summary="нужно решение",
                   decision={"recommendation": "разрешить"})


def test_missing_policy_raises(tmp_path):
    with pytest.raises(PR.PolicyMissing):
        PR.load_policy(tmp_path / "нет-политики.yaml")


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_product_level_hides_jargon_but_keeps_details_available():
    out = PR.demo("product")
    for j in JARGON:
        assert j not in out, f"внутренний термин просочился на уровень product: {j}"
    assert "по запросу" in out          # детали не удалены, а отложены


def test_debug_level_shows_technical_details():
    out = PR.demo("debug")
    assert "Технические детали:" in out
    assert "protected_paths" in out


def test_explicit_request_shows_details_on_product_level():
    m = PR.message(status="ok", summary="готово", next_steps=["дальше"],
                   technical={"gate": "spec"})
    assert "gate: spec" in PR.render(m, audience="product", show_technical=True)


def test_degraded_stays_degraded_on_every_level():
    """Простой язык — не мягкий: недоказанное называется недоказанным на всех трёх уровнях."""
    rep = {"comparable": True, "derived": {},
           "findings": [{"id": "declared_not_updated", "contour": "data_contracts",
                         "severity": "major", "detail": "источник истины не обновлён"}]}
    msg = PR.from_contour_consistency(rep)
    assert msg["status"] == "degraded"
    for aud in PR.AUDIENCES:
        out = PR.render(msg, audience=aud)
        assert "проверено не всё" in out


def test_next_work_translation_says_why_not_score():
    rep = {"plan_present": True, "plan_errors": [], "plan_warnings": [],
           "roadmap": {"errors": [], "warnings": []},
           "in_progress": [], "blocked": [], "not_ready": [], "parallel_skipped": [],
           "ready": [], "parallel_with": [],
           "next_best": {"id": "ARCH-01", "title": "Спроектировать pipeline",
                         "owner_role": "architect", "score": 42, "unblocks": 3,
                         "why": ["разблокирует 3 задачи"]}}
    out = PR.render(PR.from_next_work(rep), audience="product")
    assert "Спроектировать pipeline" in out
    assert "разблокирует 3 задачи" in out
    assert "42" not in out              # счёт остаётся в технических деталях, а не в объяснении


def test_plan_errors_are_not_swallowed_by_translation():
    """Слой простого языка не имеет права скрыть недостоверность плана: он объясняет, не сглаживает.

    Дефект был настоящий: перевод сообщал «покажу, что блокирует», а про цикл зависимостей и
    запрещённое поле исполнителя пользователь не узнавал вообще.
    """
    rep = {"plan_present": True,
           "plan_errors": ["циклическая зависимость работ: ['A', 'B']"],
           "plan_warnings": [], "roadmap": {"errors": ["нет ROADMAP.md"], "warnings": []},
           "in_progress": [], "blocked": [], "not_ready": [], "ready": [],
           "parallel_with": [], "parallel_skipped": [],
           "next_best": {"id": "A", "title": "работа", "owner_role": "engineer", "score": 1,
                         "unblocks": 0, "why": ["готова"]}}
    msg = PR.from_next_work(rep)
    assert msg["status"] == "blocked"          # несмотря на наличие next_best
    out = PR.render(msg, audience="product")
    assert "2 ошибки" in out
    assert msg["technical_details"]["available"] is True


def test_no_ready_work_is_not_reported_as_done():
    rep = {"plan_present": True, "plan_errors": [], "plan_warnings": [],
           "roadmap": {"errors": [], "warnings": []},
           "in_progress": [], "blocked": [{"id": "A"}], "not_ready": [], "ready": [],
           "parallel_with": [], "parallel_skipped": [], "next_best": None}
    msg = PR.from_next_work(rep)
    assert msg["status"] == "blocked"
    assert "не значит, что всё сделано" in PR.render(msg, audience="product")


def test_not_admitted_work_is_not_reported_as_unannounced():
    """Находка ревью: `from_next_work` знал только ведро `blocked` и терял `not_ready` (готово по
    графу, не прошло допуск). Продакту сообщался ЛОЖНЫЙ факт «работа не объявлена», хотя работа
    объявлена и всего лишь не уложилась в бюджет — перевод менял не язык, а факты."""
    rep = {"plan_present": True, "plan_errors": [], "plan_warnings": [],
           "roadmap": {"errors": [], "warnings": []},
           "in_progress": [], "blocked": [], "ready": [], "parallel_with": [],
           "parallel_skipped": [], "next_best": None,
           "not_ready": [{"id": "W1", "title": "работа", "owner_role": "engineer",
                          "blocked_by_admission": ["within_budget"],
                          "admission": [{"id": "within_budget", "ok": False,
                                         "detail": "оценка 50000 против остатка 1000"}]}]}
    msg = PR.from_next_work(rep)
    out = PR.render(msg, audience="product")
    assert "работа не объявлена" not in out
    assert "бюджет" in out.lower() or "within_budget" in str(msg["technical_details"]["payload"])


def test_unreadable_repo_is_not_described_as_understood():
    """Класс UNKNOWN не имеет права звучать как «я разобрался»."""
    rep = {"classification": {"class": "UNKNOWN", "confidence": "none", "reasons": []},
           "reconstructed": {}, "audit": {"contours": [], "ready": [], "ai_can_build": [],
                                          "needs_human": [], "blocking_gaps": []},
           "ask": {"questions": [], "summary": ""}}
    out = PR.render(PR.from_repository_understanding(rep), audience="product")
    assert "не смог" in out.lower()
    assert "разобрался" not in out.lower()
