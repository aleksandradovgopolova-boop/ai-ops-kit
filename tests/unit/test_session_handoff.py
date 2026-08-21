"""Сессионный handoff: состояние сессии записано, а не объявлено записанным.

ЧТО НАШЁЛ ЗАМЕР 17.08.2026 (живая сессия кита `88c802ae`, 329 ходов). `ai-ops session` печатал
измеренные числа верно — контекст 427k, прочитано 85.2M из 20.0M, `over_budget` — и вместе с ними
две неправды об одном и том же:

  Что сохранено: result_achieved, state_saved, handoff_created, decisions_recorded, …
  Рекомендация: NEW_SESSION — … Handoff/решения сохранены в репозитории.

Сессионного handoff в ките не существовало ни одного файла. `handoff_created` приходил параметром
`handoff_saved=True` по умолчанию, ни один из двух вызывающих его не передавал; фраза в тексте
рекомендации была строковой константой. То есть совет «уходи в новую сессию» успокаивал ровно там,
где обязан предупредить.

ПОЧЕМУ ЭТО ПРОВЕРЯЕТСЯ ЗДЕСЬ, А НЕ ГЛАЗАМИ. Класс «объявлено — не исполняется» кит требует ловить у
других; здесь он жил в его собственном ритуале завершения, и ни один из 1800+ тестов его не видел —
потому что все они проверяли, что функция возвращает то, что в неё написано.

Мутации (прогнаны, каждая валит свой тест, база без мутаций зелёная):
  * `handoff_created` снова константа True -> test_claim_is_derived_from_the_artifact падает;
  * ветка «не найден» снова утверждает «сохранён» -> test_missing_handoff_is_called_missing падает;
  * убрать запись из стража CLI -> test_guard_writes_the_handoff_it_advises (шов) падает.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops import session_guardrails as sg
from ai_ops_kit.engops import session_handoff as sh


def _snap(session_id="s-1", ctx=420_000, total=None, **kw):
    """Снимок сессии за порогом новой сессии — то состояние, в котором handoff и нужен."""
    d = {"kind": "SessionTelemetry", "session_id": session_id, "workitem_id": "WI-1",
         "context_current": ctx, "context_status": "measured", "context_source": "session-transcript",
         "session_total_tokens": total, "session_tokens_status": "measured" if total else "unavailable",
         "turns": 42, "tasks_in_session": ["WI-1"], "input_tokens": 1, "output_tokens": 1,
         "estimated_cost": 0.0, "cost_complete": True}
    d.update(kw)
    return d


# ─── что handoff обязан нести ──────────────────────────────────────────────────────────────────

def test_it_carries_every_section_the_owner_asked_for():
    """Goal / Done / Decisions / Changed / Tests / Open / Next / Risks — в именах кита."""
    h = sh.build(".", _snap(), goal="цель")
    for section in sh.SECTIONS:
        assert section in h, f"нет раздела {section}"
    assert sh.check(h) == []


def test_goal_is_never_invented(tmp_path):
    """Цель не выводится из диффа: пересказ сделанного — не замысел, и подменять одно другим нельзя."""
    h = sh.build(tmp_path, _snap())
    assert h["goal"] == sh.GOAL_NOT_NAMED
    assert "не названа" in h["goal"]


def test_a_handoff_that_hands_nothing_over_is_rejected(tmp_path):
    """Пустой `next_action` -> невалидно: handoff без следующего шага ничего не передаёт."""
    h = sh.build(tmp_path, _snap())
    h["next_action"] = ""
    assert any("next_action" in e for e in sh.check(h))
    with pytest.raises(ValueError):
        sh.write(tmp_path, h)


def test_unmeasured_spend_is_not_written_as_a_number(tmp_path):
    """`unknown` не превращается в число: следующая сессия прочла бы 0 как «сессия была дешёвой»."""
    h = sh.build(tmp_path, _snap(total=None))
    assert h["why_handed_off"]["session_total_tokens"] is None
    assert h["why_handed_off"]["session_tokens_status"] == "unavailable"
    h["why_handed_off"]["session_total_tokens"] = 0
    assert any("unknown" in e for e in sh.check(h)), "число при unavailable прошло проверку"


def test_broken_handoff_is_not_written_at_all(tmp_path):
    """Файл, которому нельзя верить, хуже отсутствующего: следующая сессия примет его за состояние."""
    with pytest.raises(ValueError):
        sh.write(tmp_path, {"kind": "SessionHandoff"})
    assert sh.latest(tmp_path) is None


def test_written_handoff_is_found_back(tmp_path):
    h = sh.build(tmp_path, _snap(session_id="s-42"), goal="цель")
    p = sh.write(tmp_path, h)
    assert p.is_file()
    assert sh.latest(tmp_path, session_id="s-42") == p
    assert sh.latest(tmp_path) == p
    assert sh.latest(tmp_path, session_id="другая-сессия") is None, \
        "handoff чужой сессии выдан за свой"


def test_render_is_the_session_complete_block(tmp_path):
    out = sh.render(sh.build(tmp_path, _snap(total=85_200_000), goal="цель сессии"))
    assert "SESSION COMPLETE" in out
    assert "цель сессии" in out
    for human in ("Сделано", "Решения", "Изменено", "Открыто", "Риски", "Следующий шаг"):
        assert human in out, f"в блоке нет раздела «{human}»"
    assert "85.2M" in out, "почему передаём — без чисел, то есть без основания"


# ─── ОХРАНА: заявление заменено на вывод ───────────────────────────────────────────────────────

def test_missing_handoff_is_called_missing(tmp_path):
    """Нет файла -> «НЕ сохранён» и путь None. Это и была та самая ложная константа."""
    txt, path = sg._handoff_note(str(tmp_path), "s-1")
    assert path is None
    assert "НЕ сохранён" in txt

    rec = sg.recommend(_snap(), repo_path=str(tmp_path))
    assert rec["outcome"] == "new_session"
    assert rec["handoff_path"] is None
    assert "НЕ сохранён" in rec["reason"], \
        "рекомендация уйти в новую сессию всё ещё утверждает, что состояние сохранено"


def test_present_handoff_is_named_with_its_path(tmp_path):
    sh.write(tmp_path, sh.build(tmp_path, _snap(session_id="s-1"), goal="цель"))
    rec = sg.recommend(_snap(session_id="s-1"), repo_path=str(tmp_path))
    assert rec["handoff_path"] is not None
    assert "сохранён" in rec["handoff"] and "НЕ сохранён" not in rec["handoff"]


def test_unprovable_is_not_reported_as_saved():
    """Без пути репозитория проверить нечем — и это ОТДЕЛЬНЫЙ ответ, не «сохранён»."""
    txt, path = sg._handoff_note(None, "s-1")
    assert path is None
    assert "проверить нечем" in txt
    assert "НЕ сохранён" not in txt, "«не смог посмотреть» подано как «не сохранён»"


def test_claim_is_derived_from_the_artifact(tmp_path):
    """ГЛАВНАЯ ОХРАНА: `handoff_created` в ритуале — вывод из файла, а не константа.

    Проверяются ОБА состояния: без файла пункт закрыт быть не может, с файлом — обязан закрыться.
    Проверка одного состояния пропустила бы и `True`, и `False` как константу.
    """
    rit_no = sg.completion_ritual(_snap(), workitem_id="WI-1", repo_path=str(tmp_path))
    assert rit_no["completion_checklist"]["handoff_created"] is False, \
        "ритуал объявил handoff созданным, когда его нет — вернулась ложная галочка"
    assert rit_no["complete"] is False

    sh.write(tmp_path, sh.build(tmp_path, _snap(), goal="цель"))
    rit_yes = sg.completion_ritual(_snap(), workitem_id="WI-1", repo_path=str(tmp_path))
    assert rit_yes["completion_checklist"]["handoff_created"] is True, \
        "handoff записан, а ритуал его не видит — вывод не работает"


def test_the_lie_cannot_be_passed_back_in():
    """Параметра, которым можно объявить handoff сохранённым, у ритуала больше нет."""
    import inspect
    params = inspect.signature(sg.completion_ritual).parameters
    assert "handoff_saved" not in params, \
        "вернулся параметр, которым вызывающий снова может объявить handoff созданным"


def test_the_block_names_handoff_state_out_loud(tmp_path):
    """Состояние handoff — отдельная строка в блоке: галочку читают как формальность."""
    rit = sg.completion_ritual(_snap(), workitem_id="WI-1", repo_path=str(tmp_path))
    block = sg.render_block(rit)
    assert "Handoff сессии" in block
    assert "НЕ сохранён" in block
