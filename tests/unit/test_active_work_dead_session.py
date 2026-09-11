"""Заявка active-work от МЁРТВОЙ сессии гасится по признаку смерти процесса, не дожидаясь 12ч.

Обратная связь ИИ-Среды (02.09.2026): заявка `session:f4d5c2e9` весь заход висела предупреждением,
хотя её сессия давно умерла — гашение было только по ВОЗРАСТУ (>12ч). Прогон длиной в заход короче
порога, поэтому мёртвая сессия мешала до самого конца.

Механизм починки (`lifecycle/active_work.py`): `register` пишет `owner_pid` — pid процесса прогона,
держащего заявку; `holder_is_gone` доказывает смерть session-заявки сразу, если этот pid на нашей
машине мёртв. Возрастное гашение остаётся страховкой для заявок без pid и живых-но-брошенных.

Триада на способность: positive (мёртвый процесс -> заявка снята сразу), fail-closed (живой/
неизвестный процесс молодую заявку НЕ снимает — без доказательства не гасим), side-effect
(register реально пишет owner_pid, и вторая сессия авто-освобождает мёртвую заявку — НАЗЫВАЯ это).
"""
import os
import subprocess
import sys

import pytest

from ai_ops_kit.lifecycle import active_work as aw

_FRESH = aw._now_iso()   # молодая заявка: по возрасту НЕ гасится, весь эффект — от признака смерти


def _dead_pid() -> int:
    """Pid процесса, которого ГАРАНТИРОВАННО уже нет: запускаем и сразу дожидаемся выхода/reap."""
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


@pytest.fixture()
def reg(tmp_path):
    p = tmp_path / ".ai" / "runtime" / "active-work.yaml"
    p.parent.mkdir(parents=True)
    return p


class TestDeadSessionClaimReleasedByProcess:
    def test_dead_process_releases_young_session_claim(self):
        """POSITIVE: мёртвый pid держателя -> session-заявка снята СРАЗУ, хотя она молода (0ч)."""
        entry = {"id": "wi-1", "owner_session": "session:f4d5c2e9",
                 "started_at": _FRESH, "owner_pid": _dead_pid()}
        assert aw.holder_is_gone(entry) is True

    def test_live_process_young_session_claim_is_not_released(self):
        """FAIL-CLOSED: живой процесс держателя (этот) -> молодую заявку НЕ снимаем (сессия жива)."""
        entry = {"id": "wi-1", "owner_session": "session:f4d5c2e9",
                 "started_at": _FRESH, "owner_pid": os.getpid()}
        assert aw.holder_is_gone(entry) is False

    def test_missing_owner_pid_young_claim_is_not_released(self):
        """FAIL-CLOSED (нет доказательства): без owner_pid молодую session-заявку не гасим по догадке."""
        entry = {"id": "wi-1", "owner_session": "session:f4d5c2e9", "started_at": _FRESH}
        assert aw.holder_is_gone(entry) is False

    def test_age_gating_still_releases_old_claim_without_pid(self):
        """РЕГРЕССИЯ: гашение по возрасту НЕ сломано — старая заявка без pid по-прежнему снимается."""
        entry = {"id": "wi-1", "owner_session": "session:f4d5c2e9",
                 "started_at": "2020-01-01T00:00:00+00:00"}
        assert aw.holder_is_gone(entry) is True

    def test_register_persists_owner_pid(self, reg):
        """SIDE-EFFECT: register реально записывает owner_pid своего процесса — без этого поля
        признак смерти проверять не по чему."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa")
        assert aw.load(reg)["active"][0].get("owner_pid") == os.getpid()

    def test_dead_holder_auto_released_for_new_session_by_name(self, reg, capsys):
        """SIDE-EFFECT (сквозной): держатель с мёртвым pid не блокирует новую сессию, и освобождение
        НАЗЫВАЕТСЯ (как у pid-личности), а не проходит молча."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:dead")
        data = aw.load(reg)
        data["active"][0]["owner_pid"] = _dead_pid()   # процесс прогона умер
        aw.save(reg, data)
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:new")
        out = capsys.readouterr().out
        assert rc == 0, "мёртвая заявка заблокировала работу"
        assert "ЗАЯВКА ОСВОБОЖДЕНА" in out, out
