"""У SessionRecommendation есть СВОЙ валидатор, а не заимствованный у ритуала.

ПОВОД — ЖИВОЙ ПРОГОН (найдено параллельной сессией 19.08.2026 на чистой установке). Команда
`session` печатала «kind должен быть CompletionRitual» при КАЖДОМ запуске: на рекомендации звался
`check()`, проверяющий ДРУГОЙ артефакт — результат другой функции, — а `recommend()` возвращал
рекомендацию вообще без поля `kind`.

Это остаток работы `session-ritual-validators-are-dead`. Она объявила «check() зовётся на каждом
produced-артефакте» и для одного из двух артефактов позвала чужой: проверка была, и она не
проверяла ничего, кроме собственного несовпадения. Хуже, что вывод был постоянным — а постоянная
ошибка перестаёт читаться уже на третий раз.

Три обязательных теста на capability (AGENTS.md):
  * positive     — рекомендация объявляет свой вид, и своя проверка её принимает на всех исходах;
  * fail-closed  — рекомендация без причины, без команды на исходе «уйди» и чужой артефакт ловятся;
  * side-effect  — единый шов `check()` разводит два вида по kind и не путает их снова.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops import session_guardrails as sg

pytestmark = pytest.mark.unit

# Снимки, дающие все исходы: дёшево и без телеметрии рантайма.
SNAPSHOTS = {
    "continue": {"context_current": 10_000, "session_total_tokens": 1_000},
    "clear": {"context_current": 10_000, "session_total_tokens": 1_000},
    "new_session": {"context_current": 900_000, "session_total_tokens": 1_000},
}


def _rec(snapshot, **kw):
    return sg.recommend(dict(snapshot), **kw)


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_the_recommendation_declares_its_own_kind():
    """Артефакт без вида нельзя ни проверить, ни отличить от соседнего — с этого дефект и начался."""
    rec = _rec(SNAPSHOTS["clear"])
    assert rec["kind"] == sg.RECOMMENDATION_KIND
    assert rec["schema_version"] == 1


@pytest.mark.parametrize("name", sorted(SNAPSHOTS))
def test_every_real_recommendation_passes_its_own_validator(name):
    """То, что кит ПРОИЗВОДИТ, обязано проходить собственную проверку — иначе она врёт о продукте."""
    assert sg.check_recommendation(_rec(SNAPSHOTS[name])) == []


def test_deferred_recommendation_is_valid_too():
    """`defer` — тоже исход, а не отсутствие ответа: он обязан проходить проверку без команды."""
    rec = _rec(SNAPSHOTS["continue"], at_safe_boundary=False)
    assert rec["outcome"] == "defer"
    assert sg.check_recommendation(rec) == []


def test_the_command_is_there_where_the_outcome_sends_you_away():
    """Совет «уйди отсюда» без точной команды заставляет вспоминать синтаксис ровно тогда,
    когда у человека кончился контекст."""
    rec = _rec(SNAPSHOTS["new_session"])
    assert rec["outcome"] in sg.COMMANDED_OUTCOMES
    assert rec["command"], rec


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_a_recommendation_without_kind_is_refused():
    """Ровно тот случай, что печатался на каждом запуске: артефакт без вида."""
    rec = _rec(SNAPSHOTS["clear"])
    rec.pop("kind")
    errs = sg.check_recommendation(rec)
    assert errs and sg.RECOMMENDATION_KIND in errs[0]


def test_an_unknown_outcome_is_refused():
    rec = dict(_rec(SNAPSHOTS["clear"]), outcome="как-нибудь")
    assert any("недопустимый outcome" in e for e in sg.check_recommendation(rec))


def test_an_outcome_that_sends_you_away_without_a_command_is_refused():
    rec = dict(_rec(SNAPSHOTS["new_session"]), command=None)
    assert any("точную команду" in e for e in sg.check_recommendation(rec))


def test_a_recommendation_without_a_reason_is_refused():
    """Совет без причины нельзя ни принять, ни отвергнуть — это не совет, а команда."""
    rec = dict(_rec(SNAPSHOTS["clear"]), reason="   ")
    assert any("без причины" in e for e in sg.check_recommendation(rec))


def test_a_recommendation_naming_only_one_of_the_two_numbers_is_refused():
    """Рекомендация, показывающая только контекст, скрывала бы случай, ради которого появился
    потолок расхода сессии: контекст после компакции нормальный, а сессия уже всё потратила."""
    rec = dict(_rec(SNAPSHOTS["clear"]))
    rec["spend_state"] = ""
    assert any("spend_state" in e for e in sg.check_recommendation(rec))


def test_an_alien_artifact_is_refused_by_the_shared_seam():
    """Валидатор, который не умеет сказать «нет», бесполезен как гейт."""
    assert sg.check({"kind": "совершенно-не-тот-артефакт"})
    assert sg.check(None)


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_the_shared_seam_routes_each_artifact_to_its_own_rules():
    """Разводка по виду — то, чего не хватало: ритуал проверяется как ритуал, совет как совет."""
    rec = _rec(SNAPSHOTS["clear"])
    ritual = sg.completion_ritual(dict(SNAPSHOTS["clear"]), workitem_id="wi-1")

    assert sg.check(rec) == [], sg.check(rec)
    assert sg.check(ritual) == [], sg.check(ritual)
    assert ritual["kind"] == sg.RITUAL_KIND and rec["kind"] == sg.RECOMMENDATION_KIND


def test_the_ritual_still_carries_a_valid_recommendation_inside():
    """Ритуал встраивает рекомендацию: она обязана оставаться валидной и внутри него."""
    ritual = sg.completion_ritual(dict(SNAPSHOTS["clear"]), workitem_id="wi-1")
    assert sg.check_recommendation(ritual["session_recommendation"]) == []


def test_a_ritual_checked_as_a_recommendation_is_named_a_mismatch_not_silently_ok():
    """Обратная сторона разводки: подсунутый не тот вид обязан называться, а не проходить."""
    ritual = sg.completion_ritual(dict(SNAPSHOTS["clear"]), workitem_id="wi-1")
    errs = sg.check_recommendation(ritual)
    assert errs and sg.RECOMMENDATION_KIND in errs[0]


# ─── шов: проверка идёт на СОБСТВЕННОМ пути команды ───────────────────────────────────────────

def test_the_command_validates_what_it_prints(monkeypatch, capsys, tmp_path):
    """ШОВ: `./ai-ops session` идёт в `main()` этого модуля — и печатал ритуал НЕПРОВЕРЕННЫМ.

    Работа `session-ritual-validators-are-dead` объявила «check() зовётся на каждом produced-
    артефакте». Для тестов это было правдой, для команды — нет: снятие вызова не роняло ничего.
    """
    seen = []
    monkeypatch.setattr(sg, "check", lambda r: seen.append(r) or [])
    monkeypatch.setattr(sg, "check_recommendation", lambda r: [])

    sg.main([str(tmp_path)])

    assert seen, "команда напечатала артефакт, не проверив его"
    assert seen[0].get("kind") == sg.RITUAL_KIND, seen[0]


def test_a_broken_artifact_is_named_to_the_human_not_swallowed(monkeypatch, capsys, tmp_path):
    """И обратная половина: найденное обязано ДОЙТИ до человека, а не остаться в списке."""
    monkeypatch.setattr(sg, "check", lambda r: ["проба: артефакт испорчен"])

    rc = sg.main([str(tmp_path)])

    err = capsys.readouterr().err
    assert "session-check: проба: артефакт испорчен" in err, err
    assert rc == 0, "команда read-only не должна отказывать из-за находки валидатора"
