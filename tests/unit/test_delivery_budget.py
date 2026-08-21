# -*- coding: utf-8 -*-
"""Потолок поставки — не только число: видно, ЧТО его занимает, и подъём требует названного файла.

Работа `delivery-budget-is-declared`, цель `checks-that-run`.

ЗАМЕР 20.08.2026, три находки одного дня — все три про механизм, а не про число.

1. ПОТОЛОК БЫЛ ИСЧЕРПАН ДО РАБОТЫ, КОТОРАЯ ЕГО УРОНИЛА: запас на main 12 783 Б, работа 15 751 Б.
   Об исчерпании узнают падением. Сам тест записал это ещё 13.08 — «наказывать того, кто пришёл
   последним, значит мерить очередь, а не размер» — и с тех пор это повторилось четыре раза.
2. ЗАПИСИ О ПОДЪЁМАХ ЖИЛИ В ДВУХ БЛОКАХ одного файла (по объёму и по числу файлов). Я сама прочитала
   блок объёма, не нашла там записи о подъёме 3.7 -> 3.8 и назвала подъём молчаливым — а запись была,
   в блоке файлов. Вопрос «записан ли этот подъём» не имел одного места для ответа.
3. ЧИСЛО В ЗАПИСИ УСТАРЕЛО ЗА ПОЛДНЯ: замер, сделанный до слияния с main, остался в ленте как
   текущий. Дата у записи это лечит, отсутствие даты — нет.

Три обязательных теста на capability (AGENTS.md):
  * positive     — состав поставки виден и сходится с самой поставкой (одна формула, не два подсчёта);
  * fail-closed  — подъём без названных файлов, без причины «почему работает в дочке» или с файлом,
                   которого нет в поставке, ОТКЛОНЯЕТСЯ;
  * side-effect  — потолок в тесте берётся ИЗ РЕЕСТРА, а не вписан числом: иначе реестр и проверка
                   разъедутся молча, и потолков станет два.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
BUDGET_REL = "quality/delivery-budget.yaml"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def ai_ops():
    spec = importlib.util.spec_from_file_location("_ai_ops_budget", KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def budget():
    return yaml.safe_load((KIT / BUDGET_REL).read_text(encoding="utf-8"))


REQUIRED = ("at", "what", "measured_before", "measured_after", "files",
            "why_it_works_in_the_child")


# ─── positive: состав виден и сходится ──────────────────────────────────────────────────────────

class TestBreakdownIsHonest:
    def test_breakdown_sums_to_the_delivery(self, ai_ops):
        """Разбивка считается по тому же списку, что поставка. Два независимых подсчёта разъехались бы,
        и тогда «что занимает поставку» отвечало бы не про поставку."""
        rep = ai_ops.delivery_breakdown()
        assert sum(d["bytes"] for d in rep["by_dir"]) == rep["total_bytes"]
        assert sum(d["files"] for d in rep["by_dir"]) == rep["file_count"]
        measured = sum(src.stat().st_size for src, _ in ai_ops.managed_set())
        assert rep["total_bytes"] == measured, "разбивка и поставка считают разное"

    def test_largest_files_are_named_with_paths(self, ai_ops):
        """«Что занимает» — это путь, а не каталог: 66% поставки лежит в одном каталоге, и без имён
        файлов ответ бесполезен. Замер: крупнейший файл — manifest на 252 КБ, 6.6% в одиночку."""
        rep = ai_ops.delivery_breakdown(top=5)
        assert len(rep["largest"]) == 5
        for f in rep["largest"]:
            assert (KIT / f["path"]).is_file(), f"в разбивке путь, которого нет: {f['path']}"
        assert rep["largest"][0]["bytes"] >= rep["largest"][-1]["bytes"], "не отсортировано по весу"

    def test_human_lines_show_dirs_and_files(self, ai_ops):
        lines = "\n".join(ai_ops.delivery_breakdown_lines(top=3))
        assert "по каталогам" in lines and "крупнейшие файлы" in lines, lines
        assert "ai_ops_kit" in lines, lines


# ─── side-effect proof: потолок один, и он в реестре ────────────────────────────────────────────

class TestTheCeilingHasOneHome:
    def test_the_delivery_test_asks_the_registry(self):
        """Потолок, вписанный числом в assert, — второй потолок: он расходится с реестром молча."""
        src = (KIT / "tests" / "unit" / "test_installer.py").read_text(encoding="utf-8")
        assert "ai_ops.delivery_budget()" in src, (
            "тест поставки не спрашивает реестр потолков — реестр и проверка разъедутся")
        assert "3.8 * 1024 * 1024" not in src, "потолок остался вписанным числом"

    def test_the_ceiling_is_not_below_what_ships_now(self, ai_ops, budget):
        """Потолок ниже фактической поставки означал бы, что он не проверяется вовсе."""
        now = sum(src.stat().st_size for src, _ in ai_ops.managed_set())
        assert now <= budget["ceilings"]["volume_bytes"], (
            f"поставка {now} Б уже выше объявленного потолка "
            f"{budget['ceilings']['volume_bytes']} Б")


# ─── positive: настоящий реестр назван полностью ────────────────────────────────────────────────

def _shipped(ai_ops):
    return {rel for _, rel in ai_ops.managed_set()}


def _exists(rel):
    return (KIT / rel).is_file()


class TestTheRealRegistryIsComplete:
    def test_no_problems_in_the_declared_budget(self, ai_ops, budget):
        """Кит применяет правило к себе: у каждого подъёма названы файлы, причина и замеры."""
        assert ai_ops.delivery_budget_errors(budget, _shipped(ai_ops), _exists) == []


# ─── fail-closed: подъём без основания ОТКЛОНЯЕТСЯ ─────────────────────────────────────────────
#
# ЗАМЕР 20.08.2026: первая версия этих проверок утверждала только, что НАСТОЯЩИЙ реестр в порядке —
# то есть была позитивом, а не fail-closed. Три мутационные пробы ВЫЖИЛИ: снятие охраны не роняло
# тест, потому что отрицательного случая не было. Проверка без «а вот так — нельзя» непробиваема по
# построению, и это ровно тот класс, ради которого контур проб и стоит.

class TestARaiseWithoutGroundsIsRefused:
    def test_headroom_is_not_a_reason(self, ai_ops, budget):
        bad = dict(budget, raises=[dict(budget["raises"][0],
                                        why_it_works_in_the_child="нужен запас на будущее, "
                                                                  "иначе следующая работа упрётся")])
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("не причина, а запас" in x for x in probs), probs

    def test_a_file_that_does_not_ship_cannot_justify_a_raise(self, ai_ops, budget):
        """ГЛАВНАЯ ОХРАНА: причина «этот файл работает в дочке» проверяема только против поставки."""
        dev_only = "ai_ops_kit/devtools/mutation_probe.py"
        assert _exists(dev_only) and dev_only not in _shipped(ai_ops), "предусловие изменилось"
        bad = dict(budget, raises=[dict(budget["raises"][0], files=[dev_only])])
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("НЕ едет в дочку" in x for x in probs), probs

    def test_a_named_file_that_does_not_exist_is_refused(self, ai_ops, budget):
        bad = dict(budget, raises=[dict(budget["raises"][0], files=["ai_ops_kit/нет-такого.py"])])
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("названного файла нет" in x for x in probs), probs

    def test_a_raise_without_files_or_reason_is_refused(self, ai_ops, budget):
        for field in ("files", "why_it_works_in_the_child", "measured_before", "at"):
            bad = dict(budget, raises=[{k: v for k, v in budget["raises"][0].items() if k != field}])
            probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
            assert any(field in x for x in probs), f"{field}: {probs}"

    def test_a_ceiling_raised_without_a_record_is_refused(self, ai_ops, budget):
        """Ровно случай, из которого работа и выросла: число поднято, записи нет.

        Сентинел — заведомо НЕзаписанное значение. Было 4*1024*1024, но 4.0 МБ стал настоящим
        потолком (подъём backlog-reachable-via-ai-ops, 20.08), и запись под него теперь есть —
        поэтому сентинел поднят до 5 МБ, значения, под которое записи нет."""
        bad = dict(budget, ceilings=dict(budget["ceilings"], volume_bytes=5 * 1024 * 1024))
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("БЕЗ записи" in x for x in probs), probs

    def test_a_raise_that_does_not_raise_is_refused(self, ai_ops, budget):
        r = dict(budget["raises"][0], from_bytes=3932160, to_bytes=3879731)
        bad = dict(budget, raises=[r])
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("не поднимает" in x for x in probs), probs

    def test_an_undated_measurement_is_refused(self, ai_ops, budget):
        bad = dict(budget, raises=[dict(budget["raises"][0], at="вчера")])
        probs = ai_ops.delivery_budget_errors(bad, _shipped(ai_ops), _exists)
        assert any("не ISO" in x for x in probs), probs


# ─── сообщение о пробое несёт состав, а не только число ─────────────────────────────────────────

class TestTheBreachMessageAnswersWhatOccupies:
    def test_message_has_number_rule_and_composition(self, ai_ops):
        msg = ai_ops.footprint_breach_message("объём managed", 4_000_000, 3_984_588)
        assert "4000000" in msg and "3984588" in msg, msg
        assert "quality/delivery-budget.yaml" in msg, "сообщение не говорит, КАК поднять потолок"
        # Проверяем ИМЕННО заголовок состава: мутация, убравшая его, оставляет строки каталогов
        # висеть без подписи — то есть сообщение перестаёт ОБЪЯВЛЯТЬ, что показывает состав.
        assert "Что занимает поставку сейчас:" in msg, (
            "сообщение о пробое не вводит состав поставки — узнав число, человек снова не узнает, "
            "что там лежит")
        assert "по каталогам" in msg and "крупнейшие файлы" in msg, msg
        assert "ai_ops_kit" in msg, msg

    def test_the_delivery_test_uses_that_message(self):
        src = (KIT / "tests" / "unit" / "test_installer.py").read_text(encoding="utf-8")
        assert "footprint_breach_message" in src, (
            "тест поставки печатает своё сообщение — состав в него не попадёт")
