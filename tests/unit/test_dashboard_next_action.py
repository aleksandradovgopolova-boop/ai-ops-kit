"""Пульт использует реальный next_work и не выдумывает совет при отказе."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("dashboard_next_under_test", KIT / "dashboard/build_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(KIT))
    (tmp_path / "planning").mkdir()
    work = [{"id": x, "title": f"Задача {x}", "type": "engineering", "goal": "g1", "status": "todo",
             "owner_role": "engineer", "depends_on": ["zzz"] if x == "dependent" else [],
             "write_scope": [f"src/{x}/"]} for x in ["aaa", "zzz", "dependent"]]
    (tmp_path / "planning/plan.yaml").write_text(yaml.safe_dump({"schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "g1", "status": "active", "outcome": {"works": False}}], "work": work}))
    (tmp_path / "ROADMAP.md").write_text("# ROADMAP\n\n## Сейчас\n\n- `g1` — пользователь получает результат\n\n## Следующий результат\n\n- `next-thing` — новая возможность\n\n## Дальше\n\n- возможность\n\n## Later\n\n- идея\n")
    (tmp_path / "VERSION").write_text("1.0.0\n")
    return tmp_path


def test_actual_next_engine_selects_unblocker(repo):
    result = load().next_action(repo)
    assert result["state"] == "known"
    assert result["report"]["next_best"]["id"] == "zzz"
    assert result["report"]["next_best"]["why"]
    assert result["source"] == "planning/plan.yaml"


def test_missing_plan_has_no_recommendation(tmp_path):
    result = load().next_action(tmp_path)
    assert result["state"] != "known"
    assert result["report"] is None


def test_corrupt_plan_has_no_recommendation(repo):
    (repo / "planning/plan.yaml").write_text("work: [broken")
    result = load().next_action(repo)
    assert result["state"] != "known"
    assert result["report"] is None


def test_tool_timeout_cannot_become_empty_success(repo, monkeypatch):
    mod = load()
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("next_work", 60)
    monkeypatch.setattr(mod.subprocess, "run", fail)
    result = mod.next_action(repo)
    assert result["state"] == "unavailable"
    assert result["report"] is None


def test_actual_build_writes_selected_work(repo, monkeypatch):
    mod = load()
    monkeypatch.setattr(mod, "open_issues", lambda root: None)
    data = mod.build(repo)
    output = repo / "data.json"
    output.write_text(json.dumps(data, ensure_ascii=False))
    written = json.loads(output.read_text())
    assert written["next_action"]["report"]["next_best"]["id"] == "zzz"
    assert written["next_action"]["state"] == "known"


def test_waiting_reason_and_human_decision_are_preserved():
    result = load().waiting_on_owner({"work": [{"id": "held", "title": "Ожидание", "status": "waiting_on_owner",
        "waiting_on": "OAuth недоступен", "human_decision": "Восстановить доступ", "evidence": "proof.md"}]})
    assert result[0]["waiting_on"] == "OAuth недоступен"
    assert result[0]["human_decision"] == "Восстановить доступ"
    assert result[0]["evidence"] == "proof.md"


def test_snapshot_retains_text_without_closing_script(tmp_path):
    mod = load()
    target = tmp_path / "index.html"
    target.write_text("<script>\n/* SNAPSHOT:BEGIN */\nconst SNAPSHOT = null;\n/* SNAPSHOT:END */\n</script>")
    attack = "</script><script>alert(1)</script>"
    assert mod.sync_snapshot(target, {"title": attack}) == 1
    actual = target.read_text()
    assert actual.count("<script>") == 1
    assert actual.count("</script>") == 1
    assert "\\u003c/script>" in actual
    payload = actual.split("const SNAPSHOT = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(payload)["title"] == attack


def test_recent_changes_match_an_actual_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "note.txt").write_text("Первое изменение")
    subprocess.run(["git", "-C", str(tmp_path), "add", "note.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fix: реальное изменение"], check=True)
    actual = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    rows = load().recent_changes(tmp_path)
    assert rows[0]["sha"] == actual
    assert rows[0]["title"] == "fix: реальное изменение"
    assert rows[0]["date"]


def test_missing_git_history_is_unknown(tmp_path):
    assert load().recent_changes(tmp_path) is None


def test_custom_plan_path_matches_engine_source(repo):
    (repo / "coordination").mkdir()
    (repo / "planning/plan.yaml").rename(repo / "coordination/work.yaml")
    (repo / ".ai-ops.yaml").write_text("product_operating_model:\n  paths:\n    plan: coordination/work.yaml\n")
    result = load().next_action(repo)
    assert result["state"] == "known"
    assert result["source"] == "coordination/work.yaml"
    assert result["report"]["next_best"]["id"] == "zzz"
    plan_path = repo / "coordination/work.yaml"
    plan = yaml.safe_load(plan_path.read_text())
    plan["work"].append({"id": "held", "title": "Ожидает доступа", "type": "engineering", "goal": "g1",
        "status": "waiting_on_owner", "owner_role": "engineer", "write_scope": ["src/held/"],
        "waiting_on": "Доступ недоступен", "human_decision": "Восстановить доступ", "evidence": "proof.md"})
    (repo / "proof.md").write_text("Тестовый источник")
    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True))
    built = load().build(repo)
    assert built["next_action"]["source"] == "coordination/work.yaml"
    assert built["waiting_on_owner"][0]["id"] == "held"
    assert built["waiting_on_owner"][0]["waiting_on"] == "Доступ недоступен"



def test_missing_size_baseline_does_not_mean_zero_violations(tmp_path):
    dims = load().tech_dimensions(tmp_path)
    code = next(x for x in dims if x["key"] == "code")
    assert code["state"] == "unknown"
    assert code["detail"] == "не измерено"
