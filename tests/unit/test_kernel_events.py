"""Тесты шины событий ядра (Wave 3: спутники на KernelEvent)."""
from __future__ import annotations

import pytest

from ai_ops_kit.shared.events import emit, subscribe, unsubscribe, clear, subscriber_count


@pytest.fixture(autouse=True)
def _clean_bus():
    """Чистим шину между тестами."""
    clear()
    yield
    clear()


def test_subscribe_and_emit():
    """Подписчик получает событие."""
    received = []
    subscribe("run_completed", lambda data: received.append(data))
    emit("run_completed", {"workitem_id": "w1", "status": "done"})
    assert len(received) == 1
    assert received[0]["workitem_id"] == "w1"


def test_multiple_subscribers():
    """Несколько подписчиков на одно событие — все получают."""
    a, b = [], []
    subscribe("run_completed", lambda d: a.append(d))
    subscribe("run_completed", lambda d: b.append(d))
    emit("run_completed", {"workitem_id": "w1"})
    assert len(a) == 1 and len(b) == 1


def test_subscriber_error_does_not_crash_emit():
    """Ошибка в подписчике НЕ роняет emit — fail-safe."""
    results = []

    def bad_handler(data):
        raise RuntimeError("boom")

    def good_handler(data):
        results.append(data)

    subscribe("run_completed", bad_handler)
    subscribe("run_completed", good_handler)
    emit("run_completed", {"workitem_id": "w1"})
    assert len(results) == 1  # good_handler получил событие несмотря на bad_handler


def test_unsubscribe():
    """Отписка работает."""
    received = []
    handler = lambda d: received.append(d)
    subscribe("run_completed", handler)
    emit("run_completed", {"workitem_id": "w1"})
    assert len(received) == 1
    unsubscribe("run_completed", handler)
    emit("run_completed", {"workitem_id": "w2"})
    assert len(received) == 1  # больше не получает


def test_emit_no_subscribers():
    """emit без подписчиков — не падает."""
    emit("nonexistent_event", {"foo": "bar"})


def test_subscriber_count():
    """subscriber_count считает правильно."""
    assert subscriber_count() == 0
    subscribe("a", lambda d: None)
    subscribe("a", lambda d: None)
    subscribe("b", lambda d: None)
    assert subscriber_count() == 3
    assert subscriber_count("a") == 2
    assert subscriber_count("b") == 1


def test_kernel_event_typeddict():
    """KernelEvent — TypedDict (dict-подкласс)."""
    from ai_ops_kit.shared.contracts import KernelEvent
    assert issubclass(KernelEvent, dict)
