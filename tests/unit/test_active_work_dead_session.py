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
from datetime import datetime, timedelta, timezone

import pytest

from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.lifecycle import work_reconcile as wr

_FRESH = aw._now_iso()   # молодая заявка: по возрасту НЕ гасится, весь эффект — от признака смерти


def _iso_days_ago(days: float) -> str:
    """ISO-время `days` дней назад в UTC — для заявок известного возраста в тестах."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


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


_LOCAL = "this-host.local"
_FOREIGN = "some-other-host.local"


class TestHardTtlReleasesForeignDeadClaim:
    """#1048: жёсткий потолок возраста снимает мёртвую заявку ДАЖЕ с чужой машины, не задевая свежие.

    Реальный случай: session-заявка с чужой машины (session:5e296f8f, MacBook-Air-Sasa.local) провисела
    24 дня и навсегда блокировала `next` — reap чужую session-личность не трогал, а возрастной порог
    12ч применялся только к своей машине.
    """

    @pytest.fixture(autouse=True)
    def _stub_local_machine(self, monkeypatch):
        """Зафиксировать имя ЭТОЙ машины, чтобы `_FOREIGN` гарантированно был чужим."""
        monkeypatch.setattr(wr, "_machine", lambda: _LOCAL)

    def test_foreign_fresh_session_claim_is_respected(self):
        """(а) ЧУЖАЯ СВЕЖАЯ заявка (моложе потолка) — держится: авторитет координации не ослаблен."""
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _FOREIGN,
                 "started_at": _iso_days_ago(3), "owner_pid": 999999}
        assert aw.holder_is_gone(entry) is False

    def test_foreign_claim_older_than_hard_ttl_is_released(self):
        """(б) ЧУЖАЯ заявка СТАРШЕ потолка (24 дня, как в поле) — снимается, хоть машина чужая."""
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _FOREIGN,
                 "started_at": _iso_days_ago(24), "owner_pid": 999999}
        assert aw.holder_is_gone(entry) is True

    def test_own_machine_age_over_12h_still_released(self):
        """(в) СВОЯ заявка возрастом >12ч (но < потолка) — снимается по старому порогу, как раньше."""
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _LOCAL,
                 "started_at": _iso_days_ago(1)}
        assert aw.holder_is_gone(entry) is True

    def test_own_machine_live_pid_is_held(self):
        """(г) СВОЯ заявка с живым pid — держится: поведение своей машины не тронуто."""
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _LOCAL,
                 "started_at": _FRESH, "owner_pid": os.getpid()}
        assert aw.holder_is_gone(entry) is False

    def test_hard_ttl_is_configurable_via_env(self, monkeypatch):
        """SIDE-EFFECT: потолок настраивается env — чужая заявка 3 дней снимается при потолке в 1 день,
        и НЕ снимается при дефолте (14 дней)."""
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _FOREIGN,
                 "started_at": _iso_days_ago(3), "owner_pid": 999999}
        assert aw.holder_is_gone(entry) is False               # дефолт 14д — держится
        monkeypatch.setenv("AI_OPS_CLAIM_HARD_TTL_DAYS", "1")
        assert aw.holder_is_gone(entry) is True                # потолок 1д — снимается

    def test_bad_env_falls_back_to_default(self, monkeypatch):
        """FAIL-CLOSED: битое значение env НЕ отключает защиту — чужая свежая заявка держится по дефолту."""
        monkeypatch.setenv("AI_OPS_CLAIM_HARD_TTL_DAYS", "not-a-number")
        entry = {"id": "wi-1", "owner_session": "session:5e296f8f", "machine": _FOREIGN,
                 "started_at": _iso_days_ago(3), "owner_pid": 999999}
        assert aw.holder_is_gone(entry) is False
