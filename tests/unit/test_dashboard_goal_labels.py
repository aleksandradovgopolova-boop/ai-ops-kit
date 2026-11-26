"""Цели и запросы решений на пульте читаются без знания технических id."""
import json
from pathlib import Path

import pytest
import yaml

from dashboard import build_data as dashboard


ROOT = Path(__file__).resolve().parents[2]


def backlog(root, goals, waiting=()):
    return dashboard.build_modals(root, roadmap_data=[], goals_data=goals,
                                 waiting=waiting, capmap=None, obs=None)["backlog"]


def test_labels_join_by_id_and_plan_title_takes_precedence(tmp_path):
    plan = {"goals": [{"id": "first", "status": "paused", "title": "Название из плана"},
                      {"id": "second", "status": "active"}, {"id": "third", "status": "active"}]}
    roadmap = "- `second` — **Многострочное\n  название.** Подробности.\n- `first` — Устаревшее название.\n"
    goals = dashboard.goals(plan, roadmap)
    assert goals["active_list"] == ["second", "third"]
    active, paused = backlog(tmp_path, goals)["sections"]
    assert [item["name"] for item in active["list"]] == ["Многострочное название", "Название цели пока не указано"]
    assert paused["list"] == [{"name": "Название из плана"}]


def test_requests_show_the_decision_even_when_a_distinct_work_title_exists(tmp_path):
    rows = [{"title": "Проверка проекта", "human_decision": "Выбрать способ проверки"},
            {"title": "untranslated-slug", "waiting_on": "Ожидается доступ"}]
    section, = backlog(tmp_path, {}, rows)["sections"]
    assert section["list"] == [{"name": "Выбрать способ проверки", "desc": "Проверка проекта"},
                               {"name": "Решение владельца пока не сформулировано", "desc": "Ожидается доступ"}]


def test_every_current_backlog_goal_has_a_russian_name():
    plan = yaml.safe_load((ROOT / "planning/plan.yaml").read_text())
    goals = dashboard.goals(plan, (ROOT / "ROADMAP.md").read_text())
    assert set(goals["titles"]) == set(goals["active_list"] + goals["paused_list"])
    assert all(dashboard._russian_text(name) for name in goals["titles"].values())


def test_checked_in_backlog_contains_titles_and_decisions():
    data = json.loads((ROOT / "dashboard/data.json").read_text())
    sections = {s["h"]: s["list"] for s in data["modals"]["backlog"]["sections"]}
    for key, heading in (("active_list", "В работе"), ("paused_list", "На паузе")):
        assert len(sections[heading]) == len(data["goals"][key])
        assert all(dashboard._russian_text(row["name"]) and row["name"] != "Название цели пока не указано"
                   for row in sections[heading])
    assert [r["name"] for r in sections["Ждёт решения владельца"]] == [
        row["human_decision"] for row in data["waiting_on_owner"]]


@pytest.mark.parametrize("body", [None, "## Что изменилось\n\nДва пункта.\n"])
def test_release_notes_belong_to_selected_stable_tag(monkeypatch, tmp_path, body):
    def release(tag, date, **extra):
        return dict(tag_name=tag, published_at=date, html_url="https://example.test/" + tag,
                    draft=False, prerelease=False) | extra

    selected = release("v2", "2026-11-20", **({"body": body} if body is not None else {}))
    rows = [release("v3-rc", "2026-11-23", prerelease=True, body="preview"), selected,
            release("v1", "2026-11-19", body="old"), release("v3", "2026-11-24", draft=True, body="draft")]
    monkeypatch.setattr(dashboard, "repo_slug", lambda root: {"owner": "demo", "name": "kit"})
    def api(root, slug, path, *args):
        assert path == "releases?per_page=10"
        return rows
    monkeypatch.setattr(dashboard, "_github", api)
    assert dashboard.delivery_evidence(tmp_path)["release"] == {
        "tag": "v2", "published_at": "2026-11-20", "url": "https://example.test/v2", "notes": body or ""}


@pytest.fixture
def projected_notes(tmp_path):
    import hashlib
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                                        "-c", "core.hooksPath=/dev/null", *args], cwd=tmp_path, text=True).strip()
    git("init", "-q")
    folder = tmp_path / "newsfragments"
    folder.mkdir()
    fragment = folder / "project.fix.md"
    fragment.write_text("Запланированное изменение\n")
    other = folder / "extra.feat.md"
    other.write_text("Другое изменение\n")
    git("add", "newsfragments")
    git("commit", "-qm", "fixtures")
    plan = {"source": {"sha": git("rev-parse", "HEAD")}, "repository": "sample/kit", "cycle_state": "planned",
            "target_version": "2.1.0", "composition_available": True, "fragments": {"fix": ["project"]},
            "input_digests": {f"newsfragments/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (fragment, other)}}
    fragment.write_text("Незафиксированная правка\n")
    return tmp_path, plan, {"owner": "sample", "name": "kit"}


def test_upcoming_notes_use_only_committed_listed_fragment_without_changing_plan(projected_notes):
    root, plan, repo = projected_notes
    before = json.dumps(plan, sort_keys=True)
    notes = dashboard.upcoming_release_notes(root, plan, repo)
    assert notes == {"source_sha": plan["source"]["sha"], "target_version": "2.1.0",
                     "entries": [{"kind": "fix", "text": "Запланированное изменение", "path": "newsfragments/project.fix.md"}]}
    assert json.dumps(plan, sort_keys=True) == before


@pytest.mark.parametrize("case", ["no_plan", "stale", "foreign_repo", "outside", "digest", "missing", "empty"])
def test_invalid_upcoming_notes_do_not_expose_partial_or_foreign_text(projected_notes, case):
    root, plan, repo = projected_notes
    if case == "no_plan":
        plan = None
    elif case == "stale":
        plan["source"]["sha"] = "0" * 40
    elif case == "foreign_repo":
        plan["repository"] = "other/kit"
    elif case == "outside":
        plan["fragments"]["fix"].append("../other")
    elif case == "digest":
        plan["input_digests"]["newsfragments/project.fix.md"] = "0" * 64
    elif case == "missing":
        plan["fragments"]["fix"].append("absent")
        plan["input_digests"]["newsfragments/absent.fix.md"] = "0" * 64
    else:
        plan["fragments"] = {}
    assert dashboard.upcoming_release_notes(root, plan, repo) is None
