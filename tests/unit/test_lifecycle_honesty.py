"""Unit-тесты честности lifecycle и режима исполнителя (F-012) — active_work + ai_ops_run.

Находка живой квалификации на niti (2026-08-06): прогон с провайдером mock печатал
`tool-loop: bad-proposal: no-json · шагов 0 · правок 0`, оставлял гейты незакрытыми — и при этом
помечал работу в active-work как `done`. `ai-ops status` показывал пустоту, хотя код не написан.
А то, что писать его должен внешний агент в созданном worktree, нигде не говорилось: исполнитель
понимал это по косвенным признакам.

Три обязательных теста на capability (AGENTS.md):
  * positive       — доведённая работа получает done; при живых правках отчёт не читает нотаций;
  * fail-closed    — NOT_READY никогда не даёт done; неизвестный статус отвергается;
  * side-effect    — active-work.yaml НА ДИСКЕ содержит blocked с причиной после реального прогона.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

import active_work
import ai_ops_run


def _repo(root):
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _registry(tmp_path, status="in-progress"):
    path = tmp_path / "active-work.yaml"
    active_work.register(path, "wi-1", "ai-ops/wi-1", ["core"], "cli", status=status)
    return path


def _entry(path):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {})["active"][0]


def _report(**kw):
    base = {"kind": "execution-pipeline", "workitem_id": "wi-1", "base_workflow": "QUICK",
            "provider": "mock", "runtime": "claude-code", "ready_for_pr": False,
            "loop": {"stopped": "done", "steps": 0, "applied_writes": 0, "denied": 0},
            "commit": {}, "gates": {}, "profile": None}
    base.update(kw)
    return base


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestFinishedWorkIsMarkedDone:

    def test_done_is_still_reachable(self, tmp_path):
        path = _registry(tmp_path)
        assert active_work.finish_cmd(path, "wi-1", status="done") == 0
        assert _entry(path)["status"] == "done"

    def test_done_entry_disappears_from_active_list(self, tmp_path):
        """classify() отбрасывает done — на этом держится прогноз конфликтов."""
        path = _registry(tmp_path)
        active_work.finish_cmd(path, "wi-1", status="done")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert active_work.classify(data["active"], {"id": "other", "affected_areas": ["core"],
                                                     "depends_on": [], "shared_contracts": []}) == []

    def test_live_run_report_has_no_external_executor_notice(self, capsys):
        """Правки есть — значит писатель отработал, и инструкция для внешнего агента не нужна."""
        ai_ops_run.print_human(_report(provider="claude-cli",
                                       loop={"stopped": "done", "steps": 3, "applied_writes": 2,
                                             "denied": 0}))
        assert "исполнитель: внешний агент" not in capsys.readouterr().out


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestUnfinishedWorkIsNeverDone:

    def test_unknown_status_is_rejected(self, tmp_path):
        path = _registry(tmp_path)
        assert active_work.finish_cmd(path, "wi-1", status="выдуманный") == 1
        assert _entry(path)["status"] == "in-progress", "статус изменён вопреки отказу"

    def test_blocked_keeps_work_visible(self, tmp_path):
        """Смысл фикса: незавершённая работа остаётся видимой в `ai-ops status`."""
        path = _registry(tmp_path)
        active_work.finish_cmd(path, "wi-1", status="blocked", reason="гейты не закрыты")
        entry = _entry(path)
        assert entry["status"] == "blocked"
        assert entry["status_reason"] == "гейты не закрыты"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert active_work.classify(data["active"], {"id": "other", "affected_areas": ["core"],
                                                     "depends_on": [], "shared_contracts": []}), \
            "blocked-работа исчезла из активных — конфликт с ней больше не предскажут"

    def test_mock_run_report_names_the_executor_and_next_step(self, capsys):
        ai_ops_run.print_human(_report(isolation={"worktree": ".ai/worktrees/wi-1"}))
        out = capsys.readouterr().out
        assert "исполнитель: внешний агент" in out
        assert ".ai/worktrees/wi-1" in out, "не сказано, где писать код"
        assert "--reevaluate-only" in out, "не сказано, чем закрыть гейты после правок"
        assert "--provider claude-cli" in out, "не назван способ получить живого писателя"


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_not_ready_run_really_leaves_blocked_on_disk(tmp_path, monkeypatch):
    """Полный прогон с mock: в active-work.yaml на диске — blocked с причиной, а не done."""
    _repo(tmp_path)
    monkeypatch.setenv("AI_OPS_PROVIDER_AUTORESOLVE", "0")

    rep = ai_ops_run.run("починить сложение",
                         {"task_type": "QUICK", "size": "small", "risk": "low",
                          "affected_areas": ["core"]},
                         tmp_path, provider_name="mock", engine="pipeline")

    assert not rep.get("ready_for_pr"), "предпосылка теста: прогон не должен быть готов к PR"
    entry = _entry(tmp_path / ".ai" / "runtime" / "active-work.yaml")
    assert entry["status"] == "blocked", "незавершённая работа помечена done — status снова врёт"
    assert "правок 0" in entry.get("status_reason", "")


@pytest.mark.unit
class TestWritesAreReconciledWithTheCommit:
    """F-017 (раунд C, T5): `loop.applied_writes: 0` при коммите на 2 файла.

    applied_writes считает правки, прошедшие ЧЕРЕЗ брокера, а writer уровня `claude -p` правит
    файлы своими инструментами. Цифра не была неверной — она отвечала на другой вопрос, и отчёт
    читался как «ничего не произошло». Ground truth — коммит.
    """

    def test_report_names_files_when_broker_saw_no_writes(self, capsys):
        ai_ops_run.print_human(_report(
            commit={"sha": "abc123def456", "branch": "ai-ops/wi-1",
                    "changed_files": ["src/a.ts", "src/b.ts"]}))
        out = capsys.readouterr().out
        assert "файлов в коммите 2" in out
        assert "напрямую, не через брокера" in out
        assert "src/a.ts" in out

    def test_no_note_when_broker_applied_the_writes(self, capsys):
        ai_ops_run.print_human(_report(
            loop={"stopped": "done", "steps": 4, "applied_writes": 2, "denied": 0},
            commit={"sha": "abc123", "branch": "b", "changed_files": ["src/a.ts"]}))
        assert "напрямую, не через брокера" not in capsys.readouterr().out

    def test_no_commit_means_no_file_count(self, capsys):
        """Без коммита считать нечего — не выдумываем ноль файлов как факт."""
        ai_ops_run.print_human(_report())
        assert "файлов в коммите" not in capsys.readouterr().out
