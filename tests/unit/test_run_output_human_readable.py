"""Человеко-читаемый вывод прогона проверяется по ФАКТИЧЕСКОМУ тексту, а не по факту запуска (#437).

Крупнейший поведенческий пробел ревью: тесты кита проверяли структуру собственных файлов, а не
поведение вывода. Этот класс дважды кусал в поле:
  * `KeyError('base_workflow')` в `print_human` на минимальном отказном отчёте (замер 01.09.2026);
  * ложные строки «доставлено» вместо «сверено» (B2-14 / B2-18).

Здесь мы ассертим РЕАЛЬНЫЙ печатаемый/возвращаемый текст для представительных форм отчёта:

  * `_print_pipeline` / `print_human` / `_print_contour_consistency` печатают в stdout —
    ловим `capsys` и проверяем захваченные строки;
  * `presenter.from_*` ВОЗВРАЩАЮТ dict `UserMessage` — проверяем структуру и текст.

Каждый тест ассертит конкретную строку/ключ, поэтому он КРАСНЕЕТ, если логика вывода ломается:
убери строку или ключ — падает ассерт. Отдельно (см. регресс-тест на минимальный отчёт) описано,
какая именно поломка кода роняет какой тест — доказательство «краснеет на дефекте» без мутационных
проб (`quality/mutation-probes.yaml` не трогаем: там идёт свой рефакторинг).
"""
from __future__ import annotations

from ai_ops_kit.engine.ai_ops_run_print import (
    _print_contour_consistency,
    _print_pipeline,
    print_human,
)
from ai_ops_kit.ui import presenter as PR


# ── Помощник: минимальный «скелет» pipeline-отчёта ────────────────────────────────────────────
# Форма отчёта движка (kind=execution-pipeline): loop/commit/gates/ready_for_pr. Каждый тест
# доопределяет только то, что проверяет, — остальное берётся из базового скелета.

def _pipeline_report(**overrides):
    r = {
        "kind": "execution-pipeline",
        "workitem_id": "WI-437",
        "base_workflow": "QUICK",
        "provider": "claude-cli",
        "runtime": "claude-code",
        "ready_for_pr": True,
        "loop": {"stopped": "done", "steps": 3, "applied_writes": 2, "denied": 0},
        "commit": {"sha": "abc123def456789", "branch": "ai-ops/WI-437",
                   "changed_files": ["a.py"], "produced_by": "broker",
                   "evidence_on_exact_sha": True, "tree_clean_before_checks": True},
        "gates": {"evaluated": ["fast_tests", "lint"], "unmet": [], "blocked": False},
    }
    r.update(overrides)
    return r


# ── _print_pipeline: ready_for_pr True / False / error ────────────────────────────────────────

def test_pipeline_ready_prints_ready_for_pr(capsys):
    """ready_for_pr=True → в заголовке стоит READY_FOR_PR, а не NOT_READY."""
    _print_pipeline(_pipeline_report(ready_for_pr=True))
    out = capsys.readouterr().out
    assert "READY_FOR_PR" in out
    assert "NOT_READY" not in out
    assert "WorkItem WI-437" in out


def test_pipeline_not_ready_prints_not_ready(capsys):
    """ready_for_pr=False → в заголовке стоит NOT_READY (и не READY_FOR_PR)."""
    _print_pipeline(_pipeline_report(ready_for_pr=False))
    out = capsys.readouterr().out
    assert "NOT_READY" in out
    assert "READY_FOR_PR" not in out


def test_pipeline_error_prints_error_line_without_crash(capsys):
    """status=error → печатается пометка ОШИБКА и текст ошибки, без падения."""
    _print_pipeline({"kind": "execution-pipeline", "workitem_id": "WI-437",
                     "status": "error", "error": "провайдер недоступен"})
    out = capsys.readouterr().out
    assert "ОШИБКА" in out
    assert "провайдер недоступен" in out
    # Ветка error — короткая: без гейтов/коммита. Так KeyError по отсутствующим ключам исключён.
    assert "гейты:" not in out


# ── print_human: минимальный отказной отчёт БЕЗ base_workflow (регресс KeyError) ───────────────

def test_print_human_minimal_report_without_base_workflow_does_not_raise(capsys):
    """Регресс 01.09.2026: минимальный отчёт БЕЗ `base_workflow` ронял `KeyError('base_workflow')`.

    Отказ на этапе active-work/preflight (ДО классификации) не несёт ни `base_workflow`, ни треков.
    `print_human` обязан напечатать короткую строку id/статус/причина и НЕ падать.

    КРАСНЕЕТ НА ДЕФЕКТЕ: если убрать страж `if "base_workflow" not in r:` в `print_human`, код
    свалится на `r['base_workflow']` (KeyError) — этот тест упадёт первым. Проверено revert-пробой
    (см. отчёт к #437): удаление стража → тест падает с KeyError.
    """
    r = {"workitem_id": "WI-999", "status": "blocked",
         "blocked_by": "active-work: та же ветка уже занята",
         "error": "preflight: конфликт записи"}
    print_human(r)  # не должно бросать
    out = capsys.readouterr().out
    assert "WI-999" in out
    assert "blocked" in out
    # Причина отказа доходит до человека, а не теряется.
    assert "active-work" in out or "preflight" in out


def test_print_human_minimal_report_empty_uses_placeholders(capsys):
    """Совсем пустой минимальный отчёт (даже без id/статуса) не падает — печатает заглушки '?'."""
    print_human({})
    out = capsys.readouterr().out
    assert "WorkItem ?" in out
    assert "[?]" in out


# ── print_human: полноценный controller-отчёт (ветка с base_workflow) ─────────────────────────

def test_print_human_controller_report_prints_workflow_and_tracks(capsys):
    """Отчёт контроллера (с base_workflow) печатает workflow, треки и гейты."""
    r = {"workitem_id": "WI-100", "status": "planned", "base_workflow": "STANDARD",
         "execution": "planned", "runtime": "claude-code",
         "required_tracks": ["impl", "tests"], "conditional_tracks": ["security"],
         "gates": ["fast_tests", "lint"], "skipped_tracks": []}
    print_human(r)
    out = capsys.readouterr().out
    assert "base_workflow: STANDARD" in out
    assert "треки (required): impl, tests" in out
    assert "план и каркас готовы" in out


# ── Критерии приёмки: НЕ сверялись / НЕ ВЫПОЛНЕНО / не объявлялись (B2-14, B2-18) ──────────────

def test_pipeline_acceptance_declared_but_not_verified_warns(capsys):
    """Критерии объявлены, но сверка не проводилась → строка «критерии приёмки НЕ сверялись»."""
    r = _pipeline_report(acceptance_criteria={
        "declared": True, "verified": False, "reason": "судья не запускался"})
    _print_pipeline(r)
    out = capsys.readouterr().out
    assert "критерии приёмки НЕ сверялись с результатом" in out
    assert "судья не запускался" in out


def test_pipeline_acceptance_unmet_prints_not_done(capsys):
    """Критерии сверены и НЕ выполнены → строка «НЕ ВЫПОЛНЕНО» с перечнем невыполненного."""
    r = _pipeline_report(acceptance_criteria={
        "declared": True, "verified": True, "met_all": False,
        "count": 2, "unmet": ["AC-2"],
        "criteria": [{"id": "AC-2", "text": "экспорт в CSV", "status": "unmet",
                      "reason": "функция не найдена"}]})
    _print_pipeline(r)
    out = capsys.readouterr().out
    assert "НЕ ВЫПОЛНЕНО" in out
    assert "AC-2" in out
    # Само невыполненное названо, а не только факт сверки.
    assert "экспорт в CSV" in out


def test_pipeline_no_acceptance_declared_but_ready_caveats(capsys):
    """Критериев не объявляли, но готово → оговорка «критериев приёмки не было объявлено»."""
    r = _pipeline_report(ready_for_pr=True,
                         acceptance_criteria={"declared": False})
    _print_pipeline(r)
    out = capsys.readouterr().out
    assert "критериев приёмки не было объявлено" in out
    # «Готово» здесь явно не равно «сверено с ожиданием».
    assert "не «результат сверен с ожиданием»" in out


def test_pipeline_acceptance_met_all_prints_verified(capsys):
    """Все критерии выполнены и подтверждены цитатой → строка «выполнены все … подтверждено цитатой»."""
    r = _pipeline_report(acceptance_criteria={
        "declared": True, "verified": True, "met_all": True,
        "count": 3, "quote_verified": True, "verifier": "acceptance-judge",
        "reads": ["src/export.py"]})
    _print_pipeline(r)
    out = capsys.readouterr().out
    assert "выполнены все 3" in out
    assert "подтверждено цитатой True" in out


# ── _print_contour_consistency: находки видны человеку, «ok» не печатается ─────────────────────

def test_contour_consistency_ok_prints_nothing(capsys):
    """Согласовано (все области проверены) → отдельного блока нет: вердикт прогона уже всё сказал."""
    r = {"contour_consistency": {"report": {"comparable": True, "findings": []}}}
    _print_contour_consistency(r)
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_contour_consistency_unknown_is_surfaced(capsys):
    """Есть непроверенные области (unknown_contour) → человек видит «Проверил не всё», не «ok»."""
    r = {"contour_consistency": {"report": {
        "comparable": True,
        "findings": [{"id": "unknown_contour", "contour": "data_model",
                      "detail": "нет сигнальных путей", "severity": "info"}]}}}
    _print_contour_consistency(r)
    out = capsys.readouterr().out
    assert "Проверил не всё" in out


def test_contour_consistency_no_report_is_silent(capsys):
    """Гейт не исполнялся (нет report) → печать молчит, а не выдумывает сообщение."""
    _print_contour_consistency({"contour_consistency": {}})
    out = capsys.readouterr().out
    assert out.strip() == ""


# ── presenter.from_contour_consistency: возвращаемый UserMessage (не печать) ───────────────────

def test_from_contour_consistency_unknown_returns_degraded_not_ok():
    """unknown-области → status=degraded, «не знаю», а не ложный «Согласовано»."""
    msg = PR.from_contour_consistency({
        "comparable": True,
        "findings": [{"id": "unknown_contour", "contour": "delivery",
                      "detail": "x", "severity": "info"}]})
    assert msg["status"] == "degraded"
    assert msg["headline"] == "Проверил не всё"


def test_from_contour_consistency_all_checked_returns_ok():
    """Расхождений нет и всё проверено → status=ok, «Согласовано»."""
    msg = PR.from_contour_consistency({"comparable": True, "findings": []})
    assert msg["status"] == "ok"
    assert msg["headline"] == "Согласовано"


def test_from_contour_consistency_not_comparable_is_degraded():
    """Сверять нечего (comparable=False) → degraded «Сверять нечего», а не «ok/продвинулись»."""
    msg = PR.from_contour_consistency({"comparable": False, "findings": []})
    assert msg["status"] == "degraded"
    assert msg["headline"] == "Сверять нечего"


# ── presenter.from_review: «доставлено» ≠ «проверено» (шесть вердиктов) ────────────────────────

def test_from_review_no_gates_says_not_checked_not_ok_silent():
    """Ревьюируемых гейтов нет → «Вливать можно, но проверка не проводилась», а не молчаливое «ок»."""
    msg = PR.from_review({"verdict": "no-ai-review-gates", "readiness": {"ready_for_merge": True},
                          "reviewable": [], "changed_files": ["a.py"]})
    assert msg["status"] == "ok"
    assert "проверка не проводилась" in msg["headline"]
    body = PR.render(msg, audience="product")
    assert "их никто не искал" in body


def test_from_review_needs_reviewer_is_degraded_not_done():
    """Судить было некому (writer≠judge) → degraded «Проверять было некому», не «Проверено»."""
    msg = PR.from_review({"verdict": "needs-reviewer", "readiness": {"ready_for_merge": False},
                          "reviews": [], "changed_files": ["a.py"]})
    assert msg["status"] == "degraded"
    assert msg["headline"] == "Проверять было некому"
    assert "не проверено" in msg["why_it_matters"]


def test_from_review_pass_says_checked():
    """Независимая проверка прошла → status=ok «Проверено»."""
    msg = PR.from_review({"verdict": "pass", "readiness": {"ready_for_merge": True},
                          "reviews": [{"gate": "code_review", "status": "pass"}],
                          "changed_files": ["a.py", "b.py"]})
    assert msg["status"] == "ok"
    assert msg["headline"] == "Проверено"


# ── from_review: внутренние термины не просачиваются на уровень product ────────────────────────

def test_from_review_product_text_has_no_internal_jargon():
    """Текст для продакта не содержит внутренних терминов (verdict/ready_for_merge как ключи)."""
    msg = PR.from_review({"verdict": "needs-changes", "readiness": {"ready_for_merge": False},
                          "reviews": [{"gate": "code_review", "status": "needs-changes"}],
                          "changed_files": ["a.py"]})
    body = PR.render(msg, audience="product")
    assert "ready_for_merge" not in body
    assert "verdict" not in body
