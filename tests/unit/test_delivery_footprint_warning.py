# -*- coding: utf-8 -*-
"""Тающий запас объёма поставки называется ДО пробоя, в том же прогоне.

Работа `delivery-footprint-warns-before-breach`, цель `checks-that-run`.

Три обязательных теста на capability (AGENTS.md):
  * positive     — тонкий запас распознаётся, и предупреждение несёт разбор (сколько до пробоя + состав);
  * fail-closed  — пробой (actual >= ceiling) НЕ выдаётся за предупреждение: его ловит блокирующий
                   assert поставки, красным; предупреждение его не глотает и не превращает в advisory;
  * side-effect  — порог берётся ИЗ РЕЕСТРА (`quality/delivery-budget.yaml`), а не вписан числом, и
                   тест поставки этот порог реально применяет — иначе реестр и проверка разъедутся.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.validation import delivery_footprint_warning as dfw

KIT = Path(__file__).resolve().parents[2]
BUDGET_REL = "quality/delivery-budget.yaml"

pytestmark = pytest.mark.unit


# ─── positive: тонкий запас распознан, предупреждение несёт разбор ────────────────────────────────

class TestThinReserveIsRecognised:
    def test_comfortable_reserve_is_not_thin(self):
        # запас 50% потолка при пороге 10% — предупреждать не о чем
        assert dfw.reserve_is_thin(actual=500, ceiling=1000, fraction=0.10) is False

    def test_thin_reserve_is_thin(self):
        # осталось 50 из 1000 (5%) при пороге 10% — тонко
        assert dfw.reserve_is_thin(actual=950, ceiling=1000, fraction=0.10) is True

    def test_the_threshold_is_a_strict_boundary(self):
        # ровно на пороге (осталось 10%) — ещё НЕ тонко; тоньше — тонко
        assert dfw.reserve_is_thin(actual=900, ceiling=1000, fraction=0.10) is False
        assert dfw.reserve_is_thin(actual=901, ceiling=1000, fraction=0.10) is True

    def test_warning_carries_numbers_and_the_breakdown(self):
        breakdown = ["ПОСТАВКА: 950 Б в 3 файлах.", "  по каталогам:", "    600 Б  ai_ops_kit"]
        msg = dfw.thinning_reserve_warning(actual=950, ceiling=1000, fraction=0.10,
                                           breakdown_lines=breakdown)
        assert "950" in msg and "1000" in msg, msg          # число и потолок
        assert "осталось 50" in msg, msg                    # запас до пробоя
        assert "5.0%" in msg, msg                           # доля запаса
        assert "НЕ пробой" in msg, "предупреждение обязано отличать себя от пробоя"
        # АВТО-РАЗБОР: состав переданных строк дошёл до человека дословно
        assert "Что занимает поставку сейчас:" in msg, msg
        assert "ai_ops_kit" in msg, msg
        # молча не удаляет — решение за человеком
        assert "молча НЕ удаляет" in msg or "решает человек" in msg, msg


# ─── fail-closed: пробой не маскируется предупреждением ───────────────────────────────────────────

class TestBreachIsNotAWarning:
    def test_breach_is_not_thin(self):
        # actual == ceiling и выше — это ПРОБОЙ, его ловит блокирующий assert, а не этот мягкий путь
        assert dfw.reserve_is_thin(actual=1000, ceiling=1000, fraction=0.10) is False
        assert dfw.reserve_is_thin(actual=1200, ceiling=1000, fraction=0.10) is False

    def test_garbage_inputs_do_not_warn(self):
        # мусорный потолок/доля не порождают ложное предупреждение (и не делят на ноль)
        assert dfw.reserve_is_thin(actual=10, ceiling=0, fraction=0.10) is False
        assert dfw.reserve_is_thin(actual=10, ceiling=1000, fraction=0.0) is False
        assert dfw.reserve_is_thin(actual=10, ceiling=1000, fraction=1.0) is False


# ─── side-effect: порог живёт в реестре и реально применяется ─────────────────────────────────────

class TestTheThresholdHasOneHome:
    def test_the_fraction_is_declared_in_the_registry(self):
        budget = yaml.safe_load((KIT / BUDGET_REL).read_text(encoding="utf-8"))
        frac = (budget.get("warnings") or {}).get("volume_reserve_fraction")
        assert isinstance(frac, (int, float)) and 0.0 < frac < 1.0, (
            "порог предупреждения о запасе объёма не объявлен в реестре как доля в (0;1)")

    def test_the_delivery_test_reads_and_applies_the_threshold(self):
        """Порог, вписанный числом в тест, — второй порог: он разойдётся с реестром молча."""
        src = (KIT / "tests" / "unit" / "test_installer.py").read_text(encoding="utf-8")
        assert 'volume_reserve_fraction' in src, "тест поставки не спрашивает реестр про порог запаса"
        assert "reserve_is_thin" in src and "thinning_reserve_warning" in src, (
            "тест поставки не применяет предупреждение — тающий запас не будет назван в его прогоне")


# ─── доставляемый footprint итога слияния = дерево-итог ∩ managed_set (чистая логика) ──────────────

class TestDeliveredMergeFootprintIsAnIntersection:
    def test_only_managed_files_of_the_merge_result_are_counted(self):
        # дерево-итог несёт три файла; в managed_set — только два, третий (dev-ассет) НЕ считается
        entries = [("ai_ops_kit/a.py", 100), ("ai_ops_kit/b.py", 250), ("tools/dev.py", 9000)]
        managed = {"ai_ops_kit/a.py", "ai_ops_kit/b.py"}
        res = dfw.delivered_merge_footprint(entries, managed)
        assert res["delivered_bytes"] == 350, res       # 100 + 250, БЕЗ 9000 dev-ассета
        assert res["delivered_files"] == 2, res
        assert res["paths"] == ["ai_ops_kit/a.py", "ai_ops_kit/b.py"], res

    def test_file_in_merge_result_but_not_managed_is_ignored(self):
        # файл присутствует в итоге, но НЕ доставляется -> в счёт доставляемого не входит
        res = dfw.delivered_merge_footprint([("x/only-in-tree.txt", 5000)], {"ai_ops_kit/a.py"})
        assert res["delivered_bytes"] == 0 and res["delivered_files"] == 0, res

    def test_managed_file_absent_from_merge_result_adds_nothing(self):
        # managed-путь, которого в дереве-итоге нет, ничего не прибавляет (пересечение, не объединение)
        res = dfw.delivered_merge_footprint([("ai_ops_kit/a.py", 100)],
                                            {"ai_ops_kit/a.py", "ai_ops_kit/missing.py"})
        assert res["delivered_bytes"] == 100 and res["delivered_files"] == 1, res


class TestDeliveredFootprintVerdict:
    def test_breach_when_delivered_reaches_ceiling(self):
        # доставляемый объём >= потолок — пробой (та же граница «>=», что у блокирующего assert поставки)
        assert dfw.delivered_footprint_verdict(1000, ceiling=1000, fraction=0.10)["breached"] is True
        assert dfw.delivered_footprint_verdict(1200, ceiling=1000, fraction=0.10)["breached"] is True

    def test_thin_reserve_below_ceiling_is_a_warning_not_a_breach(self):
        v = dfw.delivered_footprint_verdict(950, ceiling=1000, fraction=0.10)
        assert v["breached"] is False and v["thin"] is True, v
        assert v["reserve"] == 50, v

    def test_comfortable_reserve_passes_clean(self):
        v = dfw.delivered_footprint_verdict(100, ceiling=1000, fraction=0.10)
        assert v["breached"] is False and v["thin"] is False, v
        assert v["reserve"] == 900, v
