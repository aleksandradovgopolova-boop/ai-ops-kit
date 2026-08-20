"""Совет `next` действительно ВЫЧИТАЕТ замороженное — на непустом множестве.

ПОВОД — ВЫЖИВШИЙ МУТАНТ. Проба `next-does-not-offer-frozen-work` снимает из `next_work.compute`
строку вычитания, и весь набор остаётся ЗЕЛЁНЫМ. То есть механизм, ради которого заведена работа
`capability-freeze-enforced`, держался на честном слове: его можно было снести, не уронив ни одного
теста.

ПОЧЕМУ ТАК ВЫШЛО. Шов проверялся тестом `test_nothing_frozen_is_ever_offered` на НАСТОЯЩЕМ плане:
«что заморозка вычла, то не предлагается». 19.08.2026 владелец снял заморозку решением, замороженных
работ не осталось — и утверждение стало истинным впустую: пустое пересечение пусто при любом коде.
Тест переписывали именно затем, чтобы он не зависел от состояния плана на один день, и он перестал
зависеть от него настолько, что перестал зависеть и от механизма.

Проверка ЗДЕСЬ ставит непустое множество сама и потому не умирает ни от снятия заморозки, ни от
её возвращения.

ОТДЕЛЬНЫМ ФАЙЛОМ, а не строчкой в `test_capability_freeze_enforced.py`, — потому что предмет
(`ai_ops_kit/planning/`) ведёт параллельная сессия, и общий файл стал бы конфликтом ради соседства.

Три обязательных теста на capability (AGENTS.md):
  * positive     — замороженное вычтено из совета и названо человеку;
  * fail-closed  — при непустой заморозке совет НЕ равен списку готового (вычитание состоялось);
  * side-effect  — незамороженное вычитание не задело: ответ не съеден целиком.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import delivery_plan as dp
from ai_ops_kit.planning import next_work

pytestmark = pytest.mark.unit


@pytest.fixture
def ready_ids():
    """Что кит считает готовым к работе на настоящем плане — БЕЗ заморозки."""
    rep = next_work.compute(".", me="session:test-frozen")
    ids = [r["id"] for r in rep["ready"]]
    if not ids:
        pytest.skip("на плане нет готовых работ — вычитать не из чего")
    return ids


def _compute_with_frozen(monkeypatch, frozen_ids):
    """Прогнать совет так, будто перечисленные работы заморожены.

    Подменяется ИСТОЧНИК заморозки (`delivery_plan.frozen_work`), а не результат: вычитание, ради
    которого написан тест, остаётся настоящим кодом и исполняется целиком.
    """
    monkeypatch.setattr(
        next_work._plan, "frozen_work",
        lambda plan: {wid: "цель заморожена решением (фикстура теста)" for wid in frozen_ids})
    return next_work.compute(".", me="session:test-frozen")


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_frozen_work_is_subtracted_from_the_advice(monkeypatch, ready_ids):
    """Замороженное не предлагается — ни первым советом, ни параллельной работой."""
    frozen = {ready_ids[0]}

    rep = _compute_with_frozen(monkeypatch, frozen)

    offered = {(rep["next_best"] or {}).get("id")} | {p["id"] for p in rep["parallel_with"]}
    assert not (offered & frozen), (
        f"замороженная работа предложена: {offered & frozen}. Совет, противоречащий решению "
        f"владельца, хуже отсутствия совета — он выглядит как санкция")


def test_the_frozen_work_is_named_to_the_human(monkeypatch, ready_ids):
    """Молча вычесть — значит оставить человека без ответа на вопрос «а где эта работа?»."""
    frozen = {ready_ids[0]}

    rep = _compute_with_frozen(monkeypatch, frozen)

    assert {row["id"] for row in rep["frozen"]} == frozen, rep["frozen"]
    assert all(row["reason"].strip() for row in rep["frozen"]), rep["frozen"]


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_the_ready_list_itself_no_longer_carries_frozen_work(monkeypatch, ready_ids):
    """Вычитание обязано состояться В ГОТОВОМ, а не только в итоговом совете.

    Иначе `ready` продолжал бы утверждать «эту работу можно взять», и любой следующий потребитель
    списка (обзор, отчёт, параллельные ветки) снова предложил бы замороженное.
    """
    frozen = {ready_ids[0]}

    rep = _compute_with_frozen(monkeypatch, frozen)

    assert frozen & {r["id"] for r in rep["ready"]} == set(), (
        "замороженная работа осталась в списке готового — вычитание не выполнено")


def test_freezing_everything_leaves_no_advice(monkeypatch, ready_ids):
    """Крайний случай называется, а не подменяется: если заморожено всё, совета нет.

    Совет «возьми хоть что-нибудь» при полностью замороженном плане был бы прямым обходом решения.
    """
    rep = _compute_with_frozen(monkeypatch, set(ready_ids))

    offered = {(rep["next_best"] or {}).get("id")} | {p["id"] for p in rep["parallel_with"]}
    assert not (offered & set(ready_ids)), f"после полной заморозки всё ещё предложено: {offered}"
    assert len(rep["frozen"]) == len(ready_ids), rep["frozen"]


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_unfrozen_work_survives_the_subtraction(monkeypatch, ready_ids):
    """КОНТРОЛЬ: вычитание убирает ровно замороженное. Иначе тест был бы зелёным и на коде,
    который выбрасывает из совета всё подряд."""
    if len(ready_ids) < 2:
        pytest.skip("нужна хотя бы одна незамороженная работа рядом с замороженной")
    frozen = {ready_ids[0]}

    rep = _compute_with_frozen(monkeypatch, frozen)

    survivors = {r["id"] for r in rep["ready"]}
    assert survivors == set(ready_ids) - frozen, (
        f"вычитание задело незамороженное: пропало {set(ready_ids) - frozen - survivors}")


def test_without_freeze_the_advice_is_the_plain_one(ready_ids):
    """Замера ради: без заморозки ответ не пуст — значит, тесты выше меряют вычитание, а не тишину."""
    rep = next_work.compute(".", me="session:test-frozen")
    assert rep["next_best"] is not None, "на плане нет совета — предыдущие проверки ничего не значат"
    assert rep["frozen"] == [], rep["frozen"]
    assert dp.freeze_state(dp.load("."))["frozen"] is False
