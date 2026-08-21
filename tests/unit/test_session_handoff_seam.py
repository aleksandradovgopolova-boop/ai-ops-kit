"""ШОВ: путь человека доходит до записи сессионного handoff, а не только до совета о ней.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Модульные тесты `session_handoff` остаются зелёными, даже если механизм не
зовёт НИКТО — в этом репозитории такое уже было дважды и оба раза записано: `from_doctor` был
написан, покрыт тестами и не вызывался ниоткуда; вся политика экономии сессии (v3.16.0+v3.22) была
«ОБЪЯВЛЕНА И МЕРТВА» до 13.08.2026, потому что транскрипт искался по несуществующему пути.

Замер 17.08.2026, из-за которого шов и появился: совет «уйди в новую сессию» был исправен и верен
(контекст 427k measured, прочитано 85.2M из 20.0M), но уходить было НЕ С ЧЕМ — сессионный handoff не
писался нигде ни одной командой. Поэтому предмет проверки здесь — не форма handoff, а ФАКТ записи
на том пути, которым ходит человек: `ai-ops do` / `ai-ops run --execute`.

Проверка ПОВЕДЕНЧЕСКАЯ, а не по тексту исходника: тест на `ast` остался бы зелёным при вызове,
который бросает и глотается (страж обёрнут в `except`), — то есть проверял бы наличие строки, а не
работу шва.

Мутации (прогнаны):
  * заменить вызов `session_handoff.write` на пустышку -> test_guard_writes_the_handoff_it_advises
    падает (файла нет);
  * писать handoff безусловно, на любом исходе -> test_it_does_not_litter_when_no_transition_is_advised
    падает (файл появился там, где никто никуда не уходит).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engops import session_handoff as sh
from ai_ops_kit.engops import session_telemetry


def _snap(ctx, session_id="seam-1"):
    return {"kind": "SessionTelemetry", "session_id": session_id, "workitem_id": "WI-1",
            "context_current": ctx, "context_status": "measured",
            "context_source": "session-transcript",
            "session_total_tokens": 85_200_000 if ctx >= 400_000 else 1_000,
            "session_tokens_status": "measured",
            "turns": 42, "tasks_in_session": ["WI-1"], "input_tokens": 1, "output_tokens": 1,
            "estimated_cost": 0.0, "cost_complete": True}


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """Репозиторий без git и без плана: страж обязан работать в том, что есть у человека."""
    (tmp_path / ".ai-ops.yaml").write_text("session_economy: {}\n", encoding="utf-8")
    return tmp_path


def test_guard_writes_the_handoff_it_advises(repo, monkeypatch, capsys):
    """Исход `new_session` -> handoff РЕАЛЬНО на диске, и путь назван человеку."""
    monkeypatch.setattr(session_telemetry, "snapshot", lambda *a, **k: _snap(430_000))
    assert sh.latest(repo) is None, "предусловие: handoff'а ещё нет"

    ai_ops_cli._session_guard_before_start(Path(repo), "новая независимая задача", {}, None)

    p = sh.latest(repo)
    assert p is not None and p.is_file(), \
        "страж посоветовал уйти в новую сессию и не записал состояние — уходить не с чем"
    out = capsys.readouterr().out
    assert "handoff сессии записан" in out, "запись произошла молча — человек о ней не знает"


def test_the_written_handoff_is_valid_and_carries_the_numbers(repo, monkeypatch):
    """Записанное — это handoff, а не заглушка: валиден и несёт измеренное основание перехода."""
    monkeypatch.setattr(session_telemetry, "snapshot", lambda *a, **k: _snap(430_000))
    ai_ops_cli._session_guard_before_start(Path(repo), "новая независимая задача", {}, None)

    import yaml
    h = yaml.safe_load(sh.latest(repo).read_text(encoding="utf-8"))
    assert sh.check(h) == []
    assert h["why_handed_off"]["session_total_tokens"] == 85_200_000
    assert h["why_handed_off"]["outcome"] in ("new_session", "clear")
    assert h["goal"] == "новая независимая задача", "цель сессии потеряна по дороге"


def test_it_does_not_litter_when_no_transition_is_advised(repo, monkeypatch):
    """Дешёвая сессия -> никакого файла: handoff там, где никто не уходит, — мусор и ложный сигнал."""
    monkeypatch.setattr(session_telemetry, "snapshot", lambda *a, **k: _snap(1_000))
    ai_ops_cli._session_guard_before_start(Path(repo), "продолжаю ту же работу", {}, None)
    assert sh.latest(repo) is None, "handoff записан на исходе, где сессию менять не советуют"


def test_handoff_lives_where_runtime_state_lives(repo, monkeypatch):
    """`.ai/runtime/` — то же место, что у остального состояния прогона.

    Это не вкусовщина: `.ai/` входит в `process_spend._KIT_PREFIXES`, поэтому запись handoff НЕ
    читается как «код тронут» и не закрывает процессную фазу чужой работе. Переезд в другой каталог
    сломал бы потолок процессной фазы молча.
    """
    monkeypatch.setattr(session_telemetry, "snapshot", lambda *a, **k: _snap(430_000))
    ai_ops_cli._session_guard_before_start(Path(repo), "задача", {}, None)
    rel = sh.latest(repo).relative_to(repo).as_posix()
    assert rel.startswith(".ai/runtime/sessions/"), f"handoff уехал в {rel}"

    from ai_ops_kit.engops import process_spend
    assert process_spend._is_kit_path(rel), \
        "запись handoff читается как правка кода — потолок процессной фазы сломан"
