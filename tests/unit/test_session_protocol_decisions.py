"""Протокол сессии: решения владельца записаны, и ритуал старта о них ЗНАЕТ.

Работа `session-protocol-owner-decisions`. Пакет из шести вопросов был про пороги, обязательность
записи состояния, право отказа, переезд между машинами, сущность Checkpoint и запись решений 13.08.

ГЛАВНАЯ НАХОДКА ЭТОЙ РАБОТЫ — РАСХОЖДЕНИЕ ПЛАНА С РЕЕСТРОМ: пять вопросов из шести были решены ещё
17.08 (`ep-2026-08-17-session-protocol`), шестой закрыт записью
`ep-2026-08-13-session-ceiling-and-context-thresholds`, а план держал их открытыми ещё двое суток. Тот
же класс, что «реестр зовёт готовое незакрытым», только в обратную сторону.

19.08 владелец сузила пункт (2) — запись состояния только при смене сессии — и ПОДТВЕРДИЛА пункт (3)
(кит советует, но не отказывает). Оба ответа записаны решением
`ep-2026-08-19-session-handoff-scope-narrowed`.

ЗАЧЕМ ЭТИ ТЕСТЫ, если работа продуктовая: решение, которое нельзя проверить, живёт ровно до
следующего чтения. Здесь проверяется НЕ вкус владельца, а что решение записано, что оно не спорит с
кодом и что ритуал старта сессии перестал молчать о пределах.
"""
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
NEW = "ep-2026-08-19-session-handoff-scope-narrowed"
PKG = "ep-2026-08-17-session-protocol"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def episodes():
    d = yaml.safe_load((KIT / "decisions" / "registry.yaml").read_text(encoding="utf-8"))
    return {e["id"]: e for e in d["episodes"] if isinstance(e, dict) and e.get("id")}


class TestDecisionsAreRecorded:
    def test_the_narrowing_is_recorded_and_points_at_what_it_narrows(self, episodes):
        e = episodes.get(NEW)
        assert e, f"решение 19.08 не записано: {NEW}"
        assert e.get("supersedes") == PKG, \
            "сужение не связано с тем, что оно сужает — читатель не найдёт прежнюю формулировку"
        assert e.get("reversibility") == "two-way"
        assert str(e.get("date")) == "2026-08-19"

    def test_the_price_of_the_narrowing_is_named(self, episodes):
        """Цена решения называется вслух: при внезапном обрыве сессии состояния может не быть."""
        text = episodes[NEW]["decision"] + episodes[NEW]["reason"]
        assert "обрыв" in text or "не быть" in text, text

    def test_the_reason_is_a_measurement_not_a_taste(self, episodes):
        """Сужение обосновано ЗАМЕРОМ: правило «обязателен при завершении работы» не исполнилось ни
        разу за двое суток. Решение без основания стареет молча."""
        reason = episodes[NEW]["reason"]
        assert "ни одна" in reason or "ни разу" in reason, reason

    def test_the_stale_plan_finding_is_written_down(self, episodes):
        """Расхождение плана с реестром названо там, где его прочтут, а не только в отчёте сессии."""
        ctx = episodes[NEW].get("context") or ""
        assert "пять" in ctx and "17.08" in ctx, ctx

    def test_the_thirteenth_decision_is_not_missing(self, episodes):
        """Пункт 6 пакета — записать решения 13.08 — закрыт отдельной записью, и она на месте."""
        e = episodes.get("ep-2026-08-13-session-ceiling-and-context-thresholds")
        assert e, "решение 13.08 о потолке сессии и порогах контекста не записано"
        assert "20 000 000" in e["decision"] or "20000000" in e["decision"], e["decision"]


class TestDecisionDoesNotContradictTheCode:
    def test_enforcement_is_still_advise(self):
        """Подтверждённый пункт (3): кит советует, но не отказывает. Если поведение начнёт отказывать,
        решение и код разойдутся — а расхождение решения с реальностью и есть то, что эта работа
        нашла в самой себе.

        Смотрим туда, где правило РЕАЛЬНО живёт (`engops/session_guardrails.py`), а не в файл, где
        его могло бы не быть: первая версия теста искала `config/session-economy.yaml` и молча
        пропускалась бы, если политика переехала, — то есть проверяла бы наличие файла, а не правило."""
        src = (KIT / "ai_ops_kit" / "engops" / "session_guardrails.py").read_text(encoding="utf-8")
        assert "enforcement=advise" in src, \
            "в страже сессии больше не написано enforcement=advise, а решение 19.08 говорит обратное"
        assert "не block" in src or "не прерывает" in src, \
            "исчезла явная граница «советует, а не прерывает» — её и подтвердил владелец"

    def test_the_writing_rule_matches_the_code(self):
        """Сужение 19.08 сказало: состояние пишется, когда кит советует смену сессии. Проверяем, что
        код пишет ровно на этих исходах, а не на каждом завершении работы."""
        src = (KIT / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")
        assert 'rec.get("outcome") in ("new_session", "clear")' in src, \
            "условие записи состояния изменилось — сверьте с решением 19.08, иначе они разойдутся"


class TestSessionStartRitualKnowsAboutLimits:
    """Ритуал старта сессии — единственная команда, которую среда исполняет на старте. До 19.08 он не
    упоминал ни порогов, ни исходов, ни состояния прошлой сессии: то есть протокол сессии существовал
    в решениях и молчал там, где его читают."""

    @pytest.fixture(scope="class")
    def text(self):
        return (KIT / "commands" / "task" / "ai-session-start.md").read_text(encoding="utf-8")

    def test_it_reads_the_previous_session_state(self, text):
        assert "handoff.yaml" in text, "старт сессии не читает состояние предыдущей"
        assert "отсутствие" in text, \
            "не сказано, что отсутствие файла — норма: иначе пустое место читается как пробел"

    def test_it_names_the_four_outcomes(self, text):
        for word in ("продолжать", "сжать", "очистить", "новая сессия"):
            assert word in text, f"исход '{word}' не назван в ритуале старта"

    def test_it_says_the_kit_advises_and_does_not_refuse(self, text):
        assert "не отказывает" in text and "advise" in text, text

    def test_it_names_the_decisions_it_follows(self, text):
        assert NEW in text and "ep-2026-08-13" in text, \
            "ритуал ссылается на правила без номеров решений — проверить их происхождение нечем"

    def test_steps_are_numbered_without_gaps(self, text):
        import re
        nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. \*\*", text, re.M)]
        assert nums == list(range(1, len(nums) + 1)), f"порядок шагов сбит: {nums}"
