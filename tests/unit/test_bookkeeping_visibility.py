"""Unit-тесты видимости УТРАЧЕННЫХ служебных записей (срез engine ратчета, 2026-08-12).

НАХОДКА. Ревизия 2026-08-11 верно решила: «служебная запись не роняет прогон, но её утрата обязана
быть ВИДНОЙ», и поставила `_note_bookkeeping_error` на `usage_ledger.append` и
`lifecycle_journal.fix_attempt`. Решение поставили на путь ИСКЛЮЧЕНИЯ — а `journal_append` при сбое
не бросает: он возвращает `{"ok": False, "error": ...}`. Замер 2026-08-12: ни один из 11 вызовов
`journal_append` в пакете возврат не читал. То есть закрыт был путь, которого почти не бывает, а
основной путь сбоя — битая checksum-цепочка, недоступный лок, полный диск — проходил молча. Для
журнала это дороже, чем для ledger: пропуск рвёт ЦЕПОЧКУ, и `journal_read` сообщит «broken_at»
позже, в другом месте и другому человеку.

Три обязательных теста на capability (AGENTS.md):
  * positive    — успешный append не сочиняет утрат: отчёт остаётся без `bookkeeping_errors`;
  * fail-closed — сбой append РЕГИСТРИРУЕТСЯ и попадает в отчёт с адресом пропуска; слив
                  однократен (та же утрата не приезжает во второй отчёт);
  * side-effect — sequence-report.yaml НА ДИСКЕ содержит утрату, а не только возвращённый dict.
"""
from __future__ import annotations

import pytest
import yaml

import lifecycle_store


@pytest.fixture(autouse=True)
def _clean_accumulator():
    """Накопитель — модульный: чужая утрата не должна протекать в чужой тест."""
    lifecycle_store.drain_bookkeeping_losses()
    yield
    lifecycle_store.drain_bookkeeping_losses()


def _event(kind="package_end", **extra):
    return {"kind": kind, "run_id": "wi-1", "workitem_id": "wi-1", **extra}


# ─── positive ───────────────────────────────────────────────────────────────────────────────────
def test_successful_append_registers_no_loss(tmp_path):
    res = lifecycle_store.journal_append(tmp_path / "lifecycle-journal.jsonl", _event("run_start"))
    assert res["ok"] is True, res
    assert lifecycle_store.drain_bookkeeping_losses() == [], "успешная запись выдумала утрату"


def test_merge_into_report_adds_nothing_when_nothing_lost(tmp_path):
    lifecycle_store.journal_append(tmp_path / "j.jsonl", _event("run_start"))
    rep = {"ready_for_pr": True}
    assert lifecycle_store.merge_bookkeeping_losses(rep) == 0
    assert "bookkeeping_errors" not in rep, "пустой список утрат не должен появляться в отчёте"


# ─── fail-closed ────────────────────────────────────────────────────────────────────────────────
def test_broken_chain_append_is_registered_not_silent(tmp_path):
    """Битый журнал -> append запрещён (не расширяем битую цепочку) И утрата зарегистрирована."""
    journal = tmp_path / "lifecycle-journal.jsonl"
    lifecycle_store.journal_append(journal, _event("run_start"))
    # порча цепочки: строка с checksum, который ни от чего не считается
    with journal.open("a", encoding="utf-8") as f:
        f.write('{"kind": "tampered", "seq": 1, "prev_checksum": null, "checksum": "deadbeef"}\n')
    lifecycle_store.drain_bookkeeping_losses()   # утраты предыдущих шагов нас не интересуют

    res = lifecycle_store.journal_append(journal, _event("package_end", package_id="p1"))
    assert res["ok"] is False, "на битую цепочку дописывать нельзя"

    losses = lifecycle_store.drain_bookkeeping_losses()
    assert len(losses) == 1, f"утрата записи журнала не зарегистрирована: {losses}"
    loss = losses[0]
    assert loss["what"] == "lifecycle_journal.package_end", loss
    assert loss["event_ref"]["package_id"] == "p1", "адрес пропуска потерян — искать придётся руками"
    assert "повреждён" in loss["error"], loss


def test_loss_reaches_the_report(tmp_path):
    journal = tmp_path / "j.jsonl"
    journal.write_text('{"kind": "x", "seq": 0, "checksum": "nope"}\n', encoding="utf-8")
    lifecycle_store.journal_append(journal, _event("run_end"))

    rep = {"ready_for_pr": True}
    assert lifecycle_store.merge_bookkeeping_losses(rep) == 1
    assert rep["bookkeeping_errors"][0]["what"] == "lifecycle_journal.run_end"
    assert rep["ready_for_pr"] is True, "утрата служебной записи не должна менять исход прогона"


def test_drain_is_exactly_once(tmp_path):
    """Слив ОБНУЛЯЕТ накопитель: иначе прогон в том же процессе показал бы чужие потери как свои."""
    journal = tmp_path / "j.jsonl"
    journal.write_text('{"kind": "x", "seq": 0, "checksum": "nope"}\n', encoding="utf-8")
    lifecycle_store.journal_append(journal, _event("run_end"))

    first, second = {}, {}
    assert lifecycle_store.merge_bookkeeping_losses(first) == 1
    assert lifecycle_store.merge_bookkeeping_losses(second) == 0
    assert "bookkeeping_errors" not in second, "та же утрата приехала во второй отчёт"


def test_report_object_that_is_not_a_dict_does_not_crash(tmp_path):
    journal = tmp_path / "j.jsonl"
    journal.write_text('{"kind": "x", "seq": 0, "checksum": "nope"}\n', encoding="utf-8")
    lifecycle_store.journal_append(journal, _event("run_end"))
    assert lifecycle_store.merge_bookkeeping_losses(None) == 0
    assert lifecycle_store.merge_bookkeeping_losses("не dict") == 0


# ─── side-effect ────────────────────────────────────────────────────────────────────────────────
def test_sequence_report_on_disk_names_the_loss(tmp_path):
    """Утрата обязана быть в ФАЙЛЕ отчёта: dict в памяти живёт до конца процесса, файл — дольше."""
    features = tmp_path / "features"
    (features / "wi-1").mkdir(parents=True)

    journal = features / "wi-1" / "lifecycle-journal.jsonl"
    journal.write_text('{"kind": "x", "seq": 0, "checksum": "nope"}\n', encoding="utf-8")
    lifecycle_store.journal_append(journal, _event("package_end", package_id="p1"))

    seq = {"schema_version": 1, "kind": "WorkPackageSequence", "workitem_id": "wi-1", "packages": []}
    lifecycle_store.merge_bookkeeping_losses(seq)
    res = lifecycle_store.durable_write(features / "wi-1" / "sequence-report.yaml", seq)
    assert res["ok"] is True, res

    on_disk = yaml.safe_load((features / "wi-1" / "sequence-report.yaml").read_text(encoding="utf-8"))
    assert on_disk["bookkeeping_errors"][0]["what"] == "lifecycle_journal.package_end", on_disk
