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
    for aud in PR.audiences():
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
    for aud in PR.audiences():
        out = PR.render(msg, audience=aud)
        assert "проверено не всё" in out


def test_status_and_health_speak_to_a_human(tmp_path):
    """РЕВЬЮ UX + АРХИТЕКТУРНОЕ + ПРОДУКТОВОЕ (независимо, все три): presenter звали только два
    интента из пятнадцати. `status` и `health` печатали внутреннее состояние ОДИНАКОВО на всех трёх
    аудиториях, то есть настройка «с кем ты говоришь» на них не влияла вовсе:

        STATUS: активной работы нет (нет .ai/runtime/active-work.yaml)
        HEALTH: нет входных метрик (ожидается product/product-health.yaml) — честно: без данных
                score не считается

    Второе предложение честное и его надо сохранить — но путь к файлу и слово «score» продакту не
    нужны, а «что делать дальше» не сказано.
    """
    empty = PR.from_active_work({"active": []})
    out = PR.render(empty, audience="product")
    # Ярлык не должен противоречить тексту: «Работа продвинулась. Ничего не идёт» — самоотрицание.
    assert "продвинулась" not in out, out
    assert "active-work.yaml" not in out and ".ai/" not in out
    assert "ничего" in out.lower() or "не иду" in out.lower() or "не идёт" in out.lower()

    busy = PR.from_active_work({"active": [
        {"id": "w1", "affected_areas": ["src/api/"], "branch": "wave6/api-refactor",
         "status": "in-progress", "owner_session": "s1"}]})
    busy_product = PR.render(busy, audience="product")
    assert "w1" not in busy_product, "id работы продакту не нужен"
    # но рабочая копия (ветка/лента) — называется: ответ говорит, ГДЕ идёт работа, а не только «здесь».
    assert "wave6/api-refactor" in busy_product, "рабочая копия должна быть названа человеку"
    assert "w1" in PR.render(busy, audience="debug")

    # HEALTH без данных: честность сохранена, жаргон убран, следующий шаг назван.
    no_data = PR.from_product_health(None)
    out2 = PR.render(no_data, audience="product")
    assert "score" not in out2.lower() and "product-health.yaml" not in out2
    low = out2.lower()
    assert "не" in low and ("данн" in low or "измер" in low)
    assert no_data["status"] != "ok", "отсутствие данных — не «всё хорошо»"


def test_contract_comes_from_the_registry_not_from_code(tmp_path, monkeypatch):
    """ТИР 3: presenter держал свою копию словарей статусов и аудиторий.

    Реестр — источник истины, и для собственной политики коммуникации тоже: иначе переименование
    ярлыка требует правки двух мест, а расхождение обнаруживается глазами.
    """
    assert PR._contract()["source"] == "registry", "контракт читается не из реестра"
    assert set(PR.statuses()) == {"ok", "needs_input", "blocked", "done", "degraded"}
    assert PR.statuses()["degraded"], "у статуса нет ярлыка — реестр неполон"

    # Ярлык из реестра действительно доезжает до текста.
    pol = tmp_path / "policy.yaml"
    pol.write_text("statuses:\n  ok: {label: 'ЯРЛЫК-ИЗ-РЕЕСТРА'}\n"
                   "audiences:\n  product: {default: true}\n", encoding="utf-8")
    monkeypatch.setattr(PR, "POLICY", pol)
    PR._CONTRACT.clear()
    try:
        m = PR.message(status="ok", summary="проверка.")
        assert "ЯРЛЫК-ИЗ-РЕЕСТРА" in PR.render(m, audience="product")
    finally:
        PR._CONTRACT.clear()

    # Реестр недоступен -> работаем на аварийных значениях и НЕ выдаём их за источник истины.
    monkeypatch.setattr(PR, "POLICY", tmp_path / "нет.yaml")
    PR._CONTRACT.clear()
    try:
        assert PR._contract()["source"] == "fallback"
        assert PR.render(PR.message(status="ok", summary="x."), audience="product")
    finally:
        PR._CONTRACT.clear()


def test_doctor_verdict_follows_the_worst_line():
    """РЕВЬЮ UX: итог `doctor: OK` не зависел от строк с `✗` в том же выводе — человек либо
    перестанет читать строки, либо перестанет верить вердикту."""
    ok = PR.from_doctor([{"id": "a", "state": "ok", "text": "всё на месте"}])
    assert ok["status"] == "ok"

    mixed = PR.from_doctor([{"id": "a", "state": "ok", "text": "всё на месте"},
                            {"id": "b", "state": "gap", "text": "нет ROADMAP.md"}])
    assert mixed["status"] != "ok", "вердикт обязан следовать за худшей строкой"
    assert "1" in PR.render(mixed, audience="product"), "сколько именно замечаний — часть ответа"

    broken = PR.from_doctor([{"id": "a", "state": "fail", "text": "окружение врёт"}])
    assert broken["status"] == "blocked"


def test_every_review_verdict_says_what_actually_happened():
    """ШЕСТЬ ВЕРДИКТОВ РЕВЬЮ, И ТРИ ИЗ НИХ НЕ «ГОТОВО».

    Опаснее всех `no-ai-review-gates`: `ready_for_merge=True` при том, что не проверялось НИЧЕГО.
    Первая версия перевода печатала на нём «Независимая проверка прошла: замечаний нет» — ровно та
    подмена, из-за которой слой человеческого языка мог бы стать способом скрыть недоказанное.
    """
    def _msg(verdict, ready, **extra):
        return PR.from_review(dict({"verdict": verdict, "changed_files": ["a.py"], "reviews": [],
                                    "readiness": {"ready_for_merge": ready,
                                                  "reason": "тестовое основание"}}, **extra))

    passed = _msg("pass", True, reviews=[{"gate": "code_quality", "status": "pass"}])
    assert passed["status"] == "ok" and "Проверено" in PR.render(passed, audience="product")

    # Готово вливать — но никто ничего не смотрел, и это обязано быть сказано.
    ungated = _msg("no-ai-review-gates", True)
    out = PR.render(ungated, audience="product").lower()
    assert "замечаний нет" not in out.split("«")[0], out
    assert "не проводилась" in out or "никто не искал" in out, out

    nobody = _msg("needs-reviewer", False)
    assert nobody["status"] == "degraded"
    assert "не проверено" in PR.render(nobody, audience="product").lower()

    nothing = _msg("no-branch", False)
    assert nothing["status"] != "ok"
    assert "нечего" in PR.render(nothing, audience="product").lower()

    broken = _msg("error", False)
    assert broken["status"] == "blocked"

    changes = _msg("needs-changes", False, reviews=[{"gate": "security", "status": "fail"}])
    assert changes["status"] == "blocked"

    # Незнакомый вердикт — не «всё хорошо» и не «всё плохо»: перевода нет, и это признаётся.
    weird = _msg("нечто-новое", False)
    assert weird["status"] == "degraded"
    assert "не понимаю" in PR.render(weird, audience="product").lower()


def test_unknown_contours_are_not_translated_into_agreement():
    """МУТАЦИОННОЕ РЕВЮ: главный инвариант релиза (`unknown` != зелёное утверждение) защищён в
    `contours.py` пятью тестами и НЕ защищён в presenter ни одним. При отсутствии major-находок
    перевод печатал «Изменение согласовано с описанием продукта», выбрасывая все `unknown_contour`:
    кит проверил ОДИН контур из восьми и сообщил владельцу, что всё согласовано.
    """
    rep = {"comparable": True, "derived": {},
           "findings": [{"id": "unknown_contour", "contour": f"c{i}", "severity": "info",
                         "detail": "нет сигнальных путей"} for i in range(7)]}
    msg = PR.from_contour_consistency(rep)
    assert msg["status"] != "ok", "семь непроверенных контуров — это не «согласовано»"
    for aud in PR.audiences():
        out = PR.render(msg, audience=aud)
        assert "7" in out or "семь" in out, out
        assert "согласовано" not in out.lower() or "не" in out.lower()


def test_nothing_to_compare_is_not_progress():
    """`comparable: False` давал `status: ok`, и ярлык печатал «Работа продвинулась. Сверять пока
    нечего» — бодрость на месте отсутствия проверки."""
    msg = PR.from_contour_consistency({"comparable": False, "derived": {}, "findings": []})
    assert msg["status"] != "ok"
    assert "продвинулась" not in PR.render(msg, audience="product")


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


def test_work_in_progress_is_not_reported_as_unannounced():
    """Идущая работа не имеет права звучать как «работа пока не объявлена».

    Замер на самом ките (13.08.2026): `next .` печатал человеку «Готовой к работе задачи сейчас
    нет. Это не значит, что всё сделано: работа пока не объявлена», а `next . --json` в ту же
    секунду показывал `in_progress: [second-brownfield-run]`. Ведро `in_progress` не имело своей
    ветки и сливалось с «плана нет» — перевод менял не язык, а ФАКТЫ, то есть ровно запрещённый
    класс: вывод статуса вместо объявленного и заявление шире полученного.
    """
    rep = {"plan_present": True, "plan_errors": [], "plan_warnings": [],
           "roadmap": {"errors": [], "warnings": []},
           "blocked": [], "not_ready": [], "ready": [], "parallel_with": [],
           "parallel_skipped": [], "next_best": None,
           "in_progress": [{"id": "second-brownfield-run",
                            "title": "Провести установку до verified PR"}]}
    msg = PR.from_next_work(rep)
    out = PR.render(msg, audience="product")
    assert "работа не объявлена" not in out
    assert "не объявлена" not in out
    # Факт назван: и что работа идёт, и КАКАЯ именно.
    assert "Провести установку до verified PR" in out
    # `blocked` означает «продолжать нельзя» — про идущую работу это неправда.
    assert msg["status"] != "blocked"
    assert "Пока не могу продолжить" not in out
    assert msg["technical_details"]["payload"]["in_progress"] == "second-brownfield-run"


def test_unannounced_work_still_says_so_when_nothing_is_declared():
    """Обратная половина: когда работы ДЕЙСТВИТЕЛЬНО нет, честный текст остаётся прежним.

    Без этого теста исправление выше могло бы «починить» сообщение, выключив правдивую ветку.
    """
    rep = {"plan_present": True, "plan_errors": [], "plan_warnings": [],
           "roadmap": {"errors": [], "warnings": []},
           "in_progress": [], "blocked": [], "not_ready": [], "ready": [],
           "parallel_with": [], "parallel_skipped": [], "next_best": None}
    out = PR.render(PR.from_next_work(rep), audience="product")
    assert "работа пока не объявлена" in out


def test_unreadable_repo_is_not_described_as_understood():
    """Класс UNKNOWN не имеет права звучать как «я разобрался»."""
    rep = {"classification": {"class": "UNKNOWN", "confidence": "none", "reasons": []},
           "reconstructed": {}, "audit": {"contours": [], "ready": [], "ai_can_build": [],
                                          "needs_human": [], "blocking_gaps": []},
           "ask": {"questions": [], "summary": ""}}
    out = PR.render(PR.from_repository_understanding(rep), audience="product")
    assert "не смог" in out.lower()
    assert "разобрался" not in out.lower()


def _spend_check(intent="plan", state="over_ceiling"):
    return {"kind": "ProcessSpendCheck", "intent": intent, "state": state,
            "blocks": state == "over_ceiling", "spent_on_process": 60000, "ceiling": 50000,
            "session_total_tokens": 60000, "process_steps": ["specify", "plan"],
            "decision_ref": "потолок владельца 2026-08-17: 50 000 токенов"}


def test_ceiling_recommendation_does_not_advise_skipping_the_declared_step():
    """Полевой дефект 487d952b (вторая половина): потолок разбора рекомендовал «идти делать» —
    то есть ПЕРЕПРЫГНУТЬ объявленный шаг specify→plan→run. Рекомендация обязана вести по объявленному
    пути, а не в обход него: иначе кит сам сталкивает человека с процесса, который же и предписал."""
    msg = PR.from_process_spend(_spend_check("plan"),
                                continue_command="./ai-ops plan \"t\" --feature w --spend-ok",
                                run_command="./ai-ops run \"t\" --feature w --execute")
    reco = msg["decision"]["recommendation"]
    # Явно ведёт по объявленному пути и прямо запрещает перепрыгивать шаг.
    assert "не пропускать" in reco.lower(), reco
    assert "довести" in reco.lower(), reco
    # Прежняя рекомендация «идти делать по тому, что уже есть» больше не звучит.
    assert "идти делать" not in reco.lower(), reco
    assert "по тому, что уже есть" not in reco.lower(), reco


def test_ceiling_still_asks_and_names_the_spend():
    """Контроль: это по-прежнему ВОПРОС с названной тратой и обоими исходами — механизм не выключен,
    только рекомендация перестала толкать в обход шага."""
    msg = PR.from_process_spend(_spend_check("plan"),
                                continue_command="cont", run_command="run")
    assert msg["status"] == "needs_input"
    assert msg["decision"]["question"]
    # оба исхода доступны: и довести шаг, и (если описание готово) взять в исполнение
    assert "cont" in " ".join(msg["next"]) and "run" in " ".join(msg["next"])


def test_ceiling_unknown_stays_honest():
    """Контроль: неизмеримый расход остаётся degraded «не вижу», а не выдаётся за норму."""
    msg = PR.from_process_spend(_spend_check(state="unknown"))
    assert msg["status"] == "degraded"
