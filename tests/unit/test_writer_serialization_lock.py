"""Машинный замок писателя (поле 02–03.09.2026): один локальный `claude -p` за раз на всю машину,
чтобы параллельные `run --execute` не деадлочили на общем провайдере. Здесь — доказательство
поведения замка ДЕТЕРМИНИРОВАННО (без вызова claude): взаимное исключение, очередь, escape-hatch,
и что путь с инъекцией runner (offline-selftest) замок НЕ трогает.
"""
import json
import os
import threading
import time

import pytest

from ai_ops_kit.providers import orchestrator_providers as op


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _use_temp_lock(monkeypatch, tmp_path, enabled=True):
    monkeypatch.setenv("AI_OPS_WRITER_LOCK", "1" if enabled else "0")
    monkeypatch.setenv("AI_OPS_WRITER_LOCK_PATH", str(tmp_path / "ai-ops-writer.lock"))


def test_lock_path_is_machine_global_and_overridable(monkeypatch, tmp_path):
    # По умолчанию — в системном tmp (общий для всех worktree), не в дереве репозитория.
    monkeypatch.delenv("AI_OPS_WRITER_LOCK_PATH", raising=False)
    default = op.writer_lock_path()
    import tempfile
    assert default.startswith(tempfile.gettempdir())
    assert default.endswith("ai-ops-writer.lock")
    # Переопределяется явным путём.
    monkeypatch.setenv("AI_OPS_WRITER_LOCK_PATH", str(tmp_path / "custom.lock"))
    assert op.writer_lock_path() == str(tmp_path / "custom.lock")


def test_enabled_lock_serializes_concurrent_holders(monkeypatch, tmp_path):
    pytest.importorskip("fcntl")
    _use_temp_lock(monkeypatch, tmp_path, enabled=True)
    events = []
    guard = threading.Lock()

    def worker(name):
        with op._writer_serialization_lock():
            with guard:
                events.append(("enter", name))
            time.sleep(0.25)
            with guard:
                events.append(("exit", name))

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    time.sleep(0.05)   # гарантируем, что 'a' взял замок первым
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive(), "замок завис — держатель не освободил очередь"
    # Взаимное исключение: каждый enter немедленно сопровождается СВОИМ exit, без вклинивания.
    assert [e[0] for e in events] == ["enter", "exit", "enter", "exit"], events
    assert events[0][1] == events[1][1] and events[2][1] == events[3][1], events


def test_disabled_lock_is_noop_and_allows_overlap(monkeypatch, tmp_path):
    # AI_OPS_WRITER_LOCK=0 -> замок no-op: два держателя входят ОДНОВРЕМЕННО (нет сериализации).
    _use_temp_lock(monkeypatch, tmp_path, enabled=False)
    both_inside = threading.Barrier(2, timeout=5)
    entered = []

    def worker():
        with op._writer_serialization_lock():
            try:
                both_inside.wait()   # с реальным замком второй сюда не дойдёт -> BrokenBarrier
            except threading.BrokenBarrierError:
                return
            entered.append(1)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert entered == [1, 1], "no-op замок обязан пускать обоих одновременно"


def test_lock_is_released_after_context(monkeypatch, tmp_path):
    fcntl = pytest.importorskip("fcntl")
    _use_temp_lock(monkeypatch, tmp_path, enabled=True)
    with op._writer_serialization_lock():
        pass
    # После выхода замок свободен: неблокирующий LOCK_NB обязан взять его сразу.
    f = open(op.writer_lock_path(), "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)   # не бросил -> свободен
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def test_runner_injection_bypasses_the_lock(monkeypatch, tmp_path):
    # Путь offline-selftest (runner инъектирован) писателя не вызывает и НЕ должен трогать замок:
    # даже когда замок держит кто-то ещё, вызов возвращается сразу, не вставая в очередь.
    fcntl = pytest.importorskip("fcntl")
    _use_temp_lock(monkeypatch, tmp_path, enabled=True)
    held = open(op.writer_lock_path(), "w")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)   # замок занят «другим прогоном»
    try:
        runner = lambda cmd: _FakeProc(0, stdout=json.dumps({"result": "ok", "usage": {}}))
        box = {}

        def call():
            box["out"] = op._claude_cli_call("prompt", runner=runner)

        th = threading.Thread(target=call)
        th.start()
        th.join(timeout=5)
        assert not th.is_alive(), "runner-путь встал в очередь замка — он не должен его трогать"
        assert box.get("out") == "ok"
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()
