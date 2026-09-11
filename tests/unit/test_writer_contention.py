"""Сигнал контента писателя (#661): «писатель занят + работа независима → годится параллельный
субагентный путь».

  * assess      — чистое решение: занят И нет пересечений → параллель годится; иначе fail-closed;
  * record      — пишет машиночитаемый сигнал в durable-дом; годный путь кладёт РЕШЕНИЕ в шину
                  внимания (#633), негодный — не кладёт (side-effect proof в обе стороны);
  * probe       — неблокирующая проба замка: свободен → False, держит другой fd → True;
  * wired       — сигнал доходит до человека через inbox (8-й источник, шина внимания).
"""
from __future__ import annotations

import json

import pytest
import yaml

from ai_ops_kit.engine import writer_contention as WC
from ai_ops_kit.providers import orchestrator_providers as OP
from ai_ops_kit.lifecycle import attention_bus as AB
from ai_ops_kit.cli import ai_ops_cli_intents as CI


# ── assess (чистое решение) ────────────────────────────────────────────────────────────────────

def test_assess_busy_and_independent_is_viable():
    d = WC.assess(writer_busy=True, conflicts=[])
    assert d["parallel_viable"] is True
    assert "независим" in d["reason"]


def test_assess_busy_but_conflicting_is_not_viable():
    """Fail-closed: любое пересечение с активной работой закрывает параллельный путь."""
    d = WC.assess(writer_busy=True, conflicts=[{"kind": "area", "id": "w9", "detail": ["ui/"]}])
    assert d["parallel_viable"] is False
    assert "area" in d["reason"]


def test_assess_free_writer_is_not_viable():
    """Писатель свободен → очереди нет → рекомендовать параллель нечего (даже без пересечений)."""
    assert WC.assess(writer_busy=False, conflicts=[])["parallel_viable"] is False


# ── record (durable-сигнал + шина) ──────────────────────────────────────────────────────────────

def test_record_writes_machine_readable_signal(tmp_path):
    d = WC.assess(writer_busy=True, conflicts=[])
    p = WC.record(tmp_path, "w1", d, wait_seconds=42.0, areas=["engine"])
    assert p == WC.signal_path(tmp_path, "w1") and p.is_file()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["kind"] == "writer-contention-signal"
    assert payload["workitem_id"] == "w1"
    assert payload["parallel_viable"] is True
    assert payload["recommended_path"] == "parallel-subagent"
    assert payload["wait_estimate_seconds"] == 42.0
    assert payload["areas"] == ["engine"]


def test_record_viable_puts_decision_on_attention_bus(tmp_path):
    """Годный путь доходит до inbox через шину внимания — как РЕШЕНИЕ (работа не остановлена)."""
    d = WC.assess(writer_busy=True, conflicts=[])
    WC.record(tmp_path, "w1", d, areas=["engine"])
    recs = AB.collect(tmp_path)
    assert len(recs) == 1
    assert recs[0]["key"] == "writer-contention:w1"
    assert recs[0]["kind"] == AB.DECISION


def test_record_not_viable_writes_signal_but_not_bus(tmp_path):
    """Негодный путь пишет сигнал (машиночитаемый факт), но человека НЕ зовёт — звать не о чем."""
    d = WC.assess(writer_busy=True, conflicts=[{"kind": "area", "detail": ["ui/"]}])
    p = WC.record(tmp_path, "w1", d)
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["parallel_viable"] is False and payload["recommended_path"] == "queue-wait"
    assert AB.collect(tmp_path) == []


def test_record_idempotent_by_fid(tmp_path):
    d = WC.assess(writer_busy=True, conflicts=[])
    WC.record(tmp_path, "w1", d, areas=["engine"])
    WC.record(tmp_path, "w1", d, areas=["engine", "providers"])
    assert len(AB.collect(tmp_path)) == 1                       # обновление, не второй повод
    payload = json.loads(WC.signal_path(tmp_path, "w1").read_text(encoding="utf-8"))
    assert payload["areas"] == ["engine", "providers"]         # сигнал перезаписан свежим


def test_record_none_root_is_noop():
    assert WC.record(None, "w1", {"parallel_viable": True}) is None


# ── probe (неблокирующая проба замка) ────────────────────────────────────────────────────────

def test_writer_lock_busy_false_when_free(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_OPS_WRITER_LOCK_PATH", str(tmp_path / "w.lock"))
    monkeypatch.delenv("AI_OPS_WRITER_LOCK", raising=False)
    assert OP.writer_lock_busy() is False


def test_writer_lock_busy_true_when_held(tmp_path, monkeypatch):
    """Замок держит ОТДЕЛЬНЫЙ открытый дескриптор (flock ассоциирован с ним, не с процессом) →
    проба обязана увидеть занятость. Без fcntl (Windows) тест неприменим."""
    fcntl = pytest.importorskip("fcntl")
    lock = tmp_path / "w.lock"
    monkeypatch.setenv("AI_OPS_WRITER_LOCK_PATH", str(lock))
    monkeypatch.delenv("AI_OPS_WRITER_LOCK", raising=False)
    holder = open(lock, "w")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert OP.writer_lock_busy() is True
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    assert OP.writer_lock_busy() is False                       # отпущен — снова свободен


def test_writer_lock_busy_false_when_disabled(tmp_path, monkeypatch):
    """Замок выключен (`AI_OPS_WRITER_LOCK=0`) → сериализации нет, «занятости» нет → False."""
    monkeypatch.setenv("AI_OPS_WRITER_LOCK", "0")
    assert OP.writer_lock_busy() is False


# ── wired (сигнал виден человеку через inbox) ─────────────────────────────────────────────────

def test_signal_reaches_inbox(tmp_path):
    """То, что записано в шину сигналом #661, ВИДНО в inbox (8-й источник) и делает статус
    «нужно решение»."""
    p = tmp_path / ".ai" / "runtime" / "active-work.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"schema_version": 1, "kind": "active-work", "active": []}),
                 encoding="utf-8")
    WC.record(tmp_path, "w1", WC.assess(writer_busy=True, conflicts=[]), areas=["engine"])
    queue = CI._inbox_collect(tmp_path)
    assert any(a["key"] == "writer-contention:w1" for a in queue["attention"])
