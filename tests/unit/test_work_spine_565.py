"""Work — хребет, а не read-only витрина (issue #565).

Проверяем ЧЕТЫРЕ обязательства:
  1. `project_work` отдаёт `runs`, `delivery`, `outcome` из РЕАЛЬНЫХ приёмников (журнал прогонов,
     DeliveryReceipt, план+PRR), а не заглушки;
  2. связь работа->PR закрыта: проекция знает PR(ы) работы из delivery-приёмника (и кладёт их в
     artifacts как ссылки kind=pr);
  3. `explain`, `status` и `next` читают ту же Work-проекцию — per-work факты (статус, ветка)
     совпадают с тем, что отдаёт `project_work`, а не собираются каждой командой вразнобой;
  4. проекция остаётся READ-ONLY (ничего не пишет), а её новые поля пусты, когда приёмник молчит.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

import pytest
import yaml

from ai_ops_kit.lifecycle import work_view


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


WID = "spine-01"
BRANCH = "feat/spine-01"
PR_URL = "https://github.com/acme/repo/pull/42"
PR_NUMBER = 42


def _spine_repo(root, wid=WID):
    """Дочка со всеми источниками ПЛЮС реальными приёмниками прогонов/доставки/исхода."""
    _write_yaml(root / "features" / wid / "workitem.yaml", {
        "schema_version": 1, "kind": "workitem", "id": wid, "task": "построить хребет",
        "workflow": "engineering", "status": "in_progress", "lifecycle_intent": "implementation",
        "human_approval_required": False,
        "paths": {"blueprint": f"features/{wid}/blueprint.yaml",
                  "run_state": f".ai/runtime/workitems/{wid}/TaskState.yaml",
                  "workitem": f"features/{wid}/workitem.yaml"}})
    (root / "features" / wid / "blueprint.yaml").write_text("kind: blueprint\n", encoding="utf-8")
    _write_yaml(root / ".ai" / "runtime" / "active-work.yaml", {
        "schema_version": 1, "kind": "active-work",
        "active": [{"id": wid, "branch": BRANCH, "status": "in-progress",
                    "affected_areas": ["src/spine/"], "depends_on": [],
                    "owner_session": "session:live", "owner_pid": os.getpid(),
                    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}]})
    _write_yaml(root / "work-graph.yaml", {
        "schema_version": 1, "kind": "WorkGraph", "id": "WG-1", "feature": wid,
        "execution_mode": "single",
        "packages": [{"id": wid, "depends_on": [], "write_scope": ["src/spine/**"]}],
        "integration_order": [wid]})
    _write_yaml(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "goal-1", "status": "active", "outcome": {"users_export_weekly": False}}],
        "work": [{"id": wid, "title": "Построить хребет", "type": "engineering", "goal": "goal-1",
                  "status": "in_progress", "owner_role": "engineer", "value": "high",
                  "write_scope": ["src/spine/"]}]})
    # ── реальные приёмники ─────────────────────────────────────────────────────────────────────
    # (a) прогоны — событийный журнал, как его пишет engine/ai_ops_run_lifecycle.py
    jp = root / "features" / wid / "lifecycle-journal.jsonl"
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(
        json.dumps({"kind": "run_start", "run_id": wid, "workitem_id": wid, "attempt_id": "a1"}) + "\n"
        + json.dumps({"kind": "run_end", "run_id": wid, "workitem_id": wid, "attempt_id": "a1",
                      "status": "ready"}) + "\n",
        encoding="utf-8")
    # (b) доставка — DeliveryReceipt в delivery-outbox (связь работа->PR)
    _write_yaml(root / "features" / wid / "delivery-outbox" / "abc123.receipt.yaml", {
        "schema_version": 1, "kind": "DeliveryReceipt", "delivery_id": "abc123",
        "workitem_id": wid, "repository": "acme/repo", "branch": BRANCH,
        "commit_sha": "deadbeef", "base_ref": "main", "status": "opened",
        "remote_sha": "deadbeef", "sha_verified": True,
        "pr_url": PR_URL, "pr_number": PR_NUMBER})
    # (c) исход — PostReleaseReadout
    _write_yaml(root / "features" / wid / "PRR-001.yaml", {
        "schema_version": 1, "kind": "PostReleaseReadout", "id": "PRR-001",
        "delivery_receipt": {"ref": "abc123", "sha_verified": True},
        "downstream_ci": {"status": "pass", "ref": "deadbeef"},
        "product_health": {"band": "healthy", "score": 0.9},
        "evolution": {"promise_broken": False, "cost_realized": 1},
        "readout_decision": "watch"})
    return wid


@pytest.mark.unit
class TestProjectionReadsRealReceivers:
    def test_runs_come_from_the_journal(self, tmp_path):
        wid = _spine_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        assert view["runs"], "runs пуст — журнал прогонов не прочитан"
        assert view["runs"][0]["status"] == "ready"                # из run_end
        assert "runs" in view["sources"]

    def test_delivery_closes_work_to_pr_link(self, tmp_path):
        wid = _spine_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        assert view["delivery"] is not None
        prs = view["delivery"]["prs"]
        assert prs and prs[0]["url"] == PR_URL and prs[0]["number"] == PR_NUMBER
        assert prs[0]["sha_verified"] is True
        # PR попал в artifacts как ссылка kind=pr — раньше это был TODO(#549)
        pr_arts = [a for a in view["artifacts"] if a.get("kind") == "pr"]
        assert pr_arts and pr_arts[0]["url"] == PR_URL
        assert "delivery" in view["sources"]

    def test_outcome_reads_goal_and_prr(self, tmp_path):
        wid = _spine_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        oc = view["outcome"]
        assert oc is not None
        assert oc["goal"] == "goal-1"
        assert oc["goal_outcome"] == {"users_export_weekly": False}
        assert oc["goal_outcome_reached"] is False                 # флаг ещё не выставлен (#566 — не здесь)
        assert oc["prr"]["readout_decision"] == "watch"
        assert "outcome" in view["sources"]

    def test_new_fields_empty_when_receivers_silent(self, tmp_path):
        """Ранняя работа без прогонов/доставки/исхода: поля пусты, приёмники не в sources — честно."""
        _write_yaml(tmp_path / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan",
            "work": [{"id": "solo", "title": "Одна", "status": "todo", "owner_role": "engineer"}]})
        view = work_view.project_work("solo", tmp_path)
        assert view["runs"] == [] and view["delivery"] is None and view["outcome"] is None
        assert "runs" not in view["sources"] and "delivery" not in view["sources"]
        assert not [a for a in view["artifacts"] if a.get("kind") == "pr"]


@pytest.mark.unit
class TestProjectionStaysReadOnly:
    def test_reading_the_spine_writes_nothing(self, tmp_path):
        wid = _spine_repo(tmp_path)

        def snapshot():
            return {p: p.stat().st_mtime_ns for p in sorted(tmp_path.rglob("*")) if p.is_file()}

        before = snapshot()
        work_view.project_work(wid, tmp_path)
        assert snapshot() == before


@pytest.mark.unit
class TestThreeCommandsReadOneProjection:
    """explain / status / next берут per-work факты из ОДНОЙ Work-проекции — не расходятся с ней."""

    def test_explain_focus_matches_projection(self, tmp_path):
        from ai_ops_kit.cli import ai_ops_cli_intents as intents
        wid = _spine_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        state = intents._explain_state(tmp_path)
        focus = state["focus"]
        assert focus is not None, "explain не собрал фокусную работу — не с чем сверять"
        assert focus["wid"] == wid
        assert focus["status"] == view["status"]                   # ОДИН источник статуса
        assert focus["branch"] == view["branch"]                   # ОДИН источник ветки
        assert focus["workflow"] == view["workflow"]
        assert state["work_view"]["id"] == wid                     # сама проекция вложена в ответ

    def test_status_resolves_running_work_via_projection(self, tmp_path):
        from ai_ops_kit.cli.ai_ops_cli import _enrich_running_with_work_view
        wid = _spine_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        team = [{"id": wid, "branch": "stale/old-branch", "status": "in-progress"}]
        _enrich_running_with_work_view(tmp_path, team)
        assert team[0]["work_view"]["id"] == wid                   # проекция прикреплена
        assert team[0]["branch"] == view["branch"]                 # ветка синхронизирована из проекции
        assert team[0]["work_view"]["status"] == view["status"]

    def test_next_in_progress_row_carries_projection_branch(self, tmp_path):
        from ai_ops_kit.planning import next_work
        root = tmp_path / "repo"
        _spine_repo(root)
        (root / "ROADMAP.md").write_text(
            "# Направление\n\n## Сейчас\n- `goal-1` — построить хребет\n\n"
            "## Следующий результат\n- пользователь выгружает заказы сам\n\n"
            "## Дальше\n- аналитика\n\n## Не берём\n- мобильное приложение\n", encoding="utf-8")
        (root / "f.txt").write_text("x\n", encoding="utf-8")
        for a in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"]):
            subprocess.run(["git", *a], cwd=root, capture_output=True)
        view = work_view.project_work(WID, root)
        rep = next_work.compute(root, me="session:someone")
        rows = {r["id"]: r for r in rep.get("in_progress", [])}
        assert WID in rows, "работа не попала в in_progress — нечего сверять с проекцией"
        assert rows[WID].get("branch") == view["branch"]           # ветка из ЕДИНОЙ проекции
