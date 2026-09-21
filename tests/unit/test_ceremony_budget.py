"""Сторож против РАСПОЛЗАНИЯ ЦЕРЕМОНИИ (направление risk-based-ceremony, исход
`ceremony_creep_is_guarded`).

Инвариант продукт-ревью: «сложность растёт с риском, а не с полнотой». Объём процесса (число
обязательных разделов спеки на уровень) обязан подниматься ТОЛЬКО вместе с сознательным подъёмом
потолка и записью, что риск это оправдывает. Здесь — три обязательных теста на capability:
  * positive     — на РЕАЛЬНОМ ките (LEVEL_SECTIONS против LEVEL_SECTION_BUDGET) сторож зелёный;
  * fail-closed  — искусственно раздутая церемония (лишний раздел / новый уровень / дубль) КРАСНЕЕТ;
  * side-effect  — потолки живут в объявленном бюджете (LEVEL_SECTION_BUDGET), а не в assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.gates import spec_levels

pytestmark = pytest.mark.unit


class TestBaselineIsGreen:
    """Реальный кит: счётчики разделов не превышают объявленный бюджет — сторож молчит."""

    def test_real_kit_has_no_creep(self):
        assert spec_levels.ceremony_budget_errors() == []

    def test_budget_matches_current_counts(self):
        """Потолок каждого уровня == текущему числу разделов: бюджет не устарел молча (как
        module-size-baseline). Иначе сторож защищал бы не ту границу."""
        for lv, secs in spec_levels.LEVEL_SECTIONS.items():
            assert spec_levels.LEVEL_SECTION_BUDGET.get(lv) == len(secs), (
                f"L{lv}: потолок {spec_levels.LEVEL_SECTION_BUDGET.get(lv)} != разделов {len(secs)} "
                f"— пере-зафиксируй бюджет с записью в LEVEL_SECTION_BUDGET_RAISES")

    def test_every_raise_has_a_human_note(self):
        """Каждая запись подъёма несёт причину словами — «нужно больше» причиной не считается."""
        for entry in spec_levels.LEVEL_SECTION_BUDGET_RAISES:
            assert entry.get("note", "").strip(), entry


class TestCreepIsRefused:
    """ПРОБА ПОКРАСНЕНИЯ: церемония выросла без обоснования — сторож обязан поймать."""

    def test_extra_section_over_budget_reddens(self):
        """Раздел дописан в L0 сверх потолка 6 — рост объёма без роста риска ловится."""
        enlarged = {0: spec_levels.LEVEL_SECTIONS[0] + ["gold_plating"],
                    1: spec_levels.LEVEL_SECTIONS[1],
                    2: spec_levels.LEVEL_SECTIONS[2],
                    3: spec_levels.LEVEL_SECTIONS[3]}
        errors = spec_levels.ceremony_budget_errors(enlarged, spec_levels.LEVEL_SECTION_BUDGET)
        assert errors, "распухшая церемония не покраснела"
        assert any("L0" in e and "потолок" in e for e in errors), errors

    def test_new_level_without_budget_reddens(self):
        """Новый уровень без объявленного потолка обязан краснеть, а не проскользнуть."""
        with_new = dict(spec_levels.LEVEL_SECTIONS)
        with_new[4] = ["extra_a", "extra_b"]
        errors = spec_levels.ceremony_budget_errors(with_new, spec_levels.LEVEL_SECTION_BUDGET)
        assert any("L4" in e and "потолка в бюджете нет" in e for e in errors), errors

    def test_shrinking_is_allowed(self):
        """Раздел УБРАЛИ (усыхание) — сторож не ложно-краснит: потолок держит рост, не размер."""
        smaller = dict(spec_levels.LEVEL_SECTIONS)
        smaller[0] = spec_levels.LEVEL_SECTIONS[0][:-1]
        assert spec_levels.ceremony_budget_errors(smaller, spec_levels.LEVEL_SECTION_BUDGET) == []


class TestMonotonicityAndNoDuplicates:
    """Церемония ПРИРАСТАЕТ с риском: каждый уровень выше ⊇ нижнего и не дублирует его разделы."""

    def test_required_sections_are_cumulative(self):
        for lv in range(1, 4):
            lower = set(spec_levels.required_sections(lv - 1))
            higher = set(spec_levels.required_sections(lv))
            assert lower <= higher, f"L{lv} потерял разделы нижнего уровня — церемония разошлась"
            assert higher > lower, f"L{lv} не добавил ни одного раздела — уровень пустой"

    def test_duplicate_section_across_levels_reddens(self):
        """Раздел объявлен на двух уровнях — объём растёт без смысла, сторож ловит дубль."""
        dup = dict(spec_levels.LEVEL_SECTIONS)
        dup[1] = spec_levels.LEVEL_SECTIONS[1] + ["goal"]  # goal уже на L0
        budget = dict(spec_levels.LEVEL_SECTION_BUDGET)
        budget[1] = len(dup[1])  # снять бюджетную ошибку, оставить только дубль
        errors = spec_levels.ceremony_budget_errors(dup, budget)
        assert any("дублир" in e for e in errors), errors

    def test_real_kit_has_no_duplicates(self):
        seen: set[str] = set()
        for lv in sorted(spec_levels.LEVEL_SECTIONS):
            secs = set(spec_levels.LEVEL_SECTIONS[lv])
            assert not (seen & secs), f"L{lv} дублирует разделы нижнего уровня"
            seen |= secs
