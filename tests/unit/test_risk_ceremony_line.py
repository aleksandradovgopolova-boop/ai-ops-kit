"""Видимая связь РИСК -> ЦЕРЕМОНИЯ (направление risk-based-ceremony, исход
`ceremony_scales_with_risk_not_completeness`).

Человек ВИДИТ продуктовым языком, что ОБЪЁМ процесса выбран РИСКОМ изменения, а не «заполни всё», и
ПОЧЕМУ (низкий риск -> мало процесса; высокий -> больше проверок). Связь считает детерминированно
gates.spec_levels.classify; ui.presenter_formatters.risk_ceremony_line переводит её на язык человека
БЕЗ жаргона (task_type=…, L0/L3, size/risk в лицо не летят — они остаются в техдеталях).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.gates import spec_levels
from ai_ops_kit.ui import presenter_formatters as pf

pytestmark = pytest.mark.unit


def _line_for(signals):
    cls = spec_levels.classify(signals)
    return cls, pf.risk_ceremony_line(cls["level_name"], cls["reason"])


class TestLowRiskMeansLittleCeremony:
    def test_quick_task_is_l0_with_few_sections(self):
        cls = spec_levels.classify({"task_type": "QUICK"})
        assert cls["level"] == 0
        assert len(spec_levels.required_sections(0)) == 6  # мало процесса

    def test_line_names_risk_not_completeness(self):
        _, line = _line_for({"task_type": "QUICK"})
        assert "под РИСК изменения, а не под полноту" in line
        assert "Меньше риск — меньше процесса" in line
        assert "риск низкий" in line

    def test_line_carries_no_jargon(self):
        _, line = _line_for({"task_type": "QUICK"})
        for jargon in ("task_type", "L0", "QUICK", "size", "эскалация"):
            assert jargon not in line, f"жаргон '{jargon}' протёк человеку: {line}"


class TestHighRiskMeansMoreCeremony:
    def test_critical_risk_is_l3_with_more_sections(self):
        cls = spec_levels.classify({"task_type": "QUICK", "risk": "critical"})
        assert cls["level"] == 3
        assert len(spec_levels.required_sections(3)) > len(spec_levels.required_sections(0))

    def test_line_names_the_risk_that_drove_it(self):
        _, line = _line_for({"task_type": "QUICK", "risk": "high"})
        assert "риск изменения высокий" in line
        assert "под РИСК изменения, а не под полноту" in line

    def test_irreversible_is_named_as_the_reason(self):
        _, line = _line_for({"task_type": "ENGINEERING", "irreversible": True})
        assert "необратимо" in line

    def test_secret_boundary_is_named_as_the_reason(self):
        _, line = _line_for({"task_type": "ENGINEERING", "secret_boundary": True})
        assert "секрет" in line.lower()

    def test_amount_grows_with_risk(self):
        _, low = _line_for({"task_type": "QUICK"})
        _, high = _line_for({"task_type": "QUICK", "risk": "critical"})
        assert "минимум" in low
        assert "по максимуму" in high


class TestBaseCriticalDoesNotLie:
    """Регрессия на БЛОКЕР: базовый L3 (без маркера эскалации) не должен падать в else и лгать
    «мелкая и обратимая — риск низкий». classify для task_type=CRITICAL даёт base=3 и НЕ добавляет
    маркер «эскалация до L3» (level уже 3), так что строке достаётся один reason без маркеров."""

    def test_task_type_critical_names_high_risk_not_low(self):
        cls, line = _line_for({"task_type": "CRITICAL"})
        assert cls["level"] == 3
        assert "мелкая" not in line and "риск низкий" not in line, f"строка лжёт на L3: {line}"
        assert "максимальный" in line
        assert "по максимуму" in line

    def test_requested_level_3_on_quick_names_high_risk(self):
        cls, line = _line_for({"task_type": "QUICK", "requested_level": 3})
        assert cls["level"] == 3
        assert "мелкая" not in line and "риск низкий" not in line, f"строка лжёт на L3: {line}"
        assert "максимальный" in line


class TestProvisionalIsHonest:
    """Тяжесть не заявлена -> честно сказано, что процесса может стать больше (не выдаём L0 за итог)."""

    def test_provisional_clause_present(self):
        line = pf.risk_ceremony_line("L0 QUICK", ["task_type=QUICK -> базовый L0 QUICK"],
                                     provisional=True)
        assert "Тяжесть пока не заявлена" in line
        assert "процесса станет больше" in line

    def test_not_provisional_has_no_clause(self):
        line = pf.risk_ceremony_line("L0 QUICK", ["task_type=QUICK -> базовый L0 QUICK"],
                                     provisional=False)
        assert "Тяжесть пока не заявлена" not in line


class TestVisibleInSpecifyPath:
    """Строка реально появляется в продуктовом выводе шага specify (не только в чистом форматтере)."""

    def test_from_specification_summary_shows_the_link(self):
        cls = spec_levels.classify({"task_type": "QUICK", "risk": "high"})
        msg = pf.from_specification(
            path="features/wi-x/spec.yaml", created=True,
            level_name=cls["level_name"], sections=spec_levels.required_sections(cls["level"]),
            blocking_missing=[], next_command="./ai-ops plan \"x\"",
            level_reason=cls["reason"])
        assert "под РИСК изменения, а не под полноту" in msg["summary"]
        # техдетали держат точный уровень; в summary имени уровня нет (продуктовый язык)
        assert "L3" not in msg["summary"]
        assert msg["technical_details"]["payload"]["процесс подобран по риску"]
