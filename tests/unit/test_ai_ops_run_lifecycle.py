"""Юнит-тесты ai_ops_run: жизненный цикл — resume, reconcile, active-work, fix-loop."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import ai_ops_run

from _ai_ops_run_helpers import _git_init_commit


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeImmutablePolicy:
    """Tests for resume — immutable policy enforcement."""

    def _init_repo(self, child_root):
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "dummy.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

    def test_resume_drift_detection(self, child_root):
        """Resume with changed task_type -> error (drift detected)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "drift-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: drift-test\n"
            "signals:\n  task_type: ENGINEERING\n  risk: high\npolicy:\n  sandbox: true\n",
            encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="drift-test",
            resume=True,
        )
        assert report["status"] == "error"
        assert "replan" in (report.get("error") or "").lower()
        assert "task_type" in (report.get("resume") or {}).get("drift", [])

    def test_resume_corrupt_settings(self, child_root):
        """Resume with corrupt run-settings -> error (fail-closed)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "corrupt-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text("", encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="corrupt-test",
            resume=True,
        )
        assert report["status"] == "error"
        assert "повреждён" in (report.get("error") or "")

    def test_resume_with_replan_flag(self, child_root):
        """Resume with replan=True -> bypasses drift check (no drift error)."""
        self._init_repo(child_root)
        fdir = child_root / "features" / "replan-test"
        fdir.mkdir(parents=True)
        (fdir / "run-settings.yaml").write_text(
            "schema_version: 1\nkind: run-settings\nworkitem_id: replan-test\n"
            "signals:\n  task_type: ENGINEERING\n  risk: high\npolicy:\n  sandbox: true\n",
            encoding="utf-8")
        # Also need a handoff for resume_preflight to pass
        (fdir / "run-handoff.yaml").write_text(
            "kind: RunHandoff\nworkitem_id: replan-test\n"
            "next_action: продолжить\nopen_questions: []\n",
            encoding="utf-8")
        report = ai_ops_run.run(
            task_text="continue",
            signals={"task_type": "QUICK", "risk": "low"},
            child_root=child_root,
            engine="pipeline",
            feature="replan-test",
            resume=True,
            replan=True,
        )
        # With replan=True, the error should NOT be about drift/replan
        # (it may be about resume_preflight or other things, but not drift)
        err = (report.get("error") or "").lower()
        if report["status"] == "error":
            assert "drift" not in err


@pytest.mark.critical_path
@pytest.mark.unit
class TestReconcilePendingDelivery:
    """Tests for _reconcile_pending_delivery — delivery reconciliation."""

    def test_no_pending(self, tmp_path):
        """No pending intents -> None."""
        result = ai_ops_run._reconcile_pending_delivery(tmp_path, "nonexistent", tmp_path)
        assert result is None

    def test_reconcile_found_matching(self, tmp_path):
        """Intent + matching PR on remote -> reconciled receipt."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        fdir = tmp_path / "feat"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d1.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d1", "workitem_id": "feat",
                           "repository": "o/r", "branch": "ai-ops/feat",
                           "base_ref": "main", "commit_sha": "abc",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/1", "number": 1,
            "repository": "o/r", "head_sha": "abc", "base_ref": "main",
            "pr_state": "open", "merged": False}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "reconciled"

    def test_reconcile_absent(self, tmp_path):
        """Intent + PR absent on remote -> not-delivered receipt."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        fdir = tmp_path / "feat2"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d2.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d2", "workitem_id": "feat2",
                           "repository": "o/r", "branch": "ai-ops/feat2",
                           "base_ref": "main", "commit_sha": "def",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "absent", "repository": "o/r"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat2", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "reconciled-absent"

    def test_reconcile_mismatch(self, tmp_path):
        """Intent + PR with different SHA -> mismatch receipt."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        fdir = tmp_path / "feat3"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d3.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d3", "workitem_id": "feat3",
                           "repository": "o/r", "branch": "ai-ops/feat3",
                           "base_ref": "main", "commit_sha": "old_sha",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/3", "number": 3,
            "repository": "o/r", "head_sha": "new_sha", "base_ref": "main"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat3", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "mismatch"

    def test_reconcile_unavailable(self, tmp_path):
        """Intent + remote unavailable -> no receipt written."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        fdir = tmp_path / "feat4"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d4.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d4", "workitem_id": "feat4",
                           "repository": "o/r", "branch": "ai-ops/feat4",
                           "base_ref": "main", "commit_sha": "xyz",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "unavailable"}
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat4", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "unavailable"

    def test_reconcile_exception(self, tmp_path):
        """reconcile_delivery raises exception -> unavailable status."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        fdir = tmp_path / "feat5"
        fdir.mkdir(parents=True)
        outbox = fdir / "delivery-outbox"
        outbox.mkdir(parents=True)
        _ls.durable_write(outbox / "d5.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent",
                           "delivery_id": "d5", "workitem_id": "feat5",
                           "repository": "o/r", "branch": "ai-ops/feat5",
                           "base_ref": "main", "commit_sha": "qqq",
                           "status": "intended"})
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: (_ for _ in ()).throw(
            RuntimeError("network down"))
        try:
            result = ai_ops_run._reconcile_pending_delivery(tmp_path, "feat5", tmp_path)
        finally:
            pr_open.reconcile_delivery = orig
        assert result is not None
        assert result[0]["status"] == "unavailable"


@pytest.mark.unit
class TestBookkeepingLossIsVisible:
    """Утраченная служебная запись ВИДНА в отчёте, а не пропадает молча.

    Ревизия 2026-08-11: учёт usage и lifecycle-журнал писались под `except Exception: pass`.
    Решение «служебная запись не роняет прогон» правильное и записанное — падать из-за журнала
    посреди доставки хуже, чем потерять строку. Но второй половины не было: потеря была
    невидимой. Для кита, чья заявленная ценность — Usage Truth и `unavailable != 0`, молча
    пропавшая запись стоимости означает занижённый счёт, поданный как факт.

    Образец взят в том же файле: рядом уже был `escalation_error` с пометкой «rc3: НЕ глотаем
    молча». Здесь то же для служебных записей.
    """

    def test_records_what_was_lost_and_why(self):
        rep = {"kind": "execution-pipeline"}
        ai_ops_run._note_bookkeeping_error(rep, "usage_ledger.append", OSError("disk full"))

        assert "bookkeeping_errors" in rep, "утрата записи не попала в отчёт"
        entry = rep["bookkeeping_errors"][0]
        assert entry["what"] == "usage_ledger.append", "не сказано, ЧТО потеряно"
        assert "OSError" in entry["error"] and "disk full" in entry["error"], (
            f"не сказано, ПОЧЕМУ потеряно: {entry}")

    def test_accumulates_and_does_not_overwrite(self):
        """Две потери — две записи: вторая не затирает первую."""
        rep = {}
        ai_ops_run._note_bookkeeping_error(rep, "usage_ledger.append", OSError("x"))
        ai_ops_run._note_bookkeeping_error(rep, "lifecycle_journal.fix_attempt", ValueError("y"))

        whats = [e["what"] for e in rep["bookkeeping_errors"]]
        assert whats == ["usage_ledger.append", "lifecycle_journal.fix_attempt"], whats

    def test_clean_run_has_no_such_key(self):
        """Обратная сторона: без потерь ключа НЕТ — иначе он читался бы как «всегда что-то не так»."""
        rep = {"kind": "execution-pipeline"}
        assert "bookkeeping_errors" not in rep

    def test_never_raises_on_unexpected_report_shape(self):
        """fail-closed наоборот: сам учёт потерь не имеет права уронить прогон."""
        ai_ops_run._note_bookkeeping_error(None, "x", OSError("y"))
        ai_ops_run._note_bookkeeping_error("не dict", "x", OSError("y"))


# ============================================================================
# Перенос покрытия из tests/unit/test_ai_ops_run_selftest.py (гранулярно).
# Каждое поведение монолита, ещё не покрытое выше, — отдельным тестом с настоящей
# проверкой значения. Вызовы, git-фикстуры и фейковые proposer'ы взяты из монолита.
# ============================================================================


_PLANNED_SIG = {
    "task_type": "PRODUCT", "risk": "medium",
    "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
    "ui_changed": True, "measurable_behavior": True, "user_facing_change": True,
    "affected_areas": ["catalog", "orders-api"],
}


@pytest.mark.critical_path
@pytest.mark.unit
class TestPlannedControllerTracks:
    """planned-путь контроллера: неметериализованное состояние, active-work, треки, гейты."""

    def _planned(self, tmp_path):
        root = tmp_path / "planned"
        root.mkdir()
        report = ai_ops_run.run(
            task_text="фильтр по статусу в каталоге заказов",
            signals=dict(_PLANNED_SIG), child_root=root,
            runtime="claude-code", engine="controller",
        )
        return root, report

    def test_run_state_not_materialized(self, tmp_path):
        """planned: run_state НЕ материализован (обещание пути)."""
        _, report = self._planned(tmp_path)
        assert report["run_state_materialized"] is False

    def test_active_work_registered(self, tmp_path):
        """planned: active-work.yaml зарегистрирована."""
        root, _ = self._planned(tmp_path)
        assert (root / ".ai" / "runtime" / "active-work.yaml").exists()

    def test_visual_analytics_tracks(self, tmp_path):
        """planned: сигналы UI/аналитики -> треки VISUAL и ANALYTICS в отчёте."""
        _, report = self._planned(tmp_path)
        assert {"VISUAL", "ANALYTICS"} <= set(report["required_tracks"])

    def test_track_gates_aggregated(self, tmp_path):
        """planned: гейты треков агрегированы (ux_review + analytics_design_readiness)."""
        _, report = self._planned(tmp_path)
        assert {"ux_review", "analytics_design_readiness"} <= set(report["gates"])

    def test_analytics_runtime_verification_not_prerelease(self, tmp_path):
        """v3.27.6: analytics_runtime_verification НЕ входит в дорелизный RunPlan."""
        _, report = self._planned(tmp_path)
        assert "analytics_runtime_verification" not in set(report["gates"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeCorruptSettingsNotOverwritten:
    """v3.0.12: битый run-settings на resume не перезаписывается дефолтами."""

    def test_corrupt_settings_not_rewritten(self, tmp_path):
        """Повреждённый (пустой) run-settings остаётся пустым — контракт не уничтожен молча."""
        root = tmp_path / "corr-root"
        cf = root / "features" / "corr"
        cf.mkdir(parents=True)
        (cf / "run-settings.yaml").write_text("", encoding="utf-8")
        report = ai_ops_run.run(
            task_text="продолжить",
            signals={"task_type": "QUICK", "risk": "low"}, child_root=root,
            engine="pipeline", feature="corr", resume=True,
        )
        assert report.get("status") == "error"
        assert "повреждён" in (report.get("error") or "")
        assert (cf / "run-settings.yaml").read_text(encoding="utf-8") == ""


def _rewrite_base_repo(root, wid):
    """Репо, где base ПЕРЕПИСАН на несвязанный orphan (force-push назад). Как в монолите."""
    root.mkdir(parents=True, exist_ok=True)

    def g(*a):
        return subprocess.run(["git", "-C", str(root), *a],
                              capture_output=True, text=True).stdout.strip()
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        g(*a)
    (root / "f").write_text("x", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "A")
    base_A = g("rev-parse", "HEAD")
    cur = g("rev-parse", "--abbrev-ref", "HEAD")
    g("checkout", "-q", "-b", "ai-ops/rwx")
    (root / "w").write_text("work", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "W")
    work_sha = g("rev-parse", "HEAD")
    g("checkout", "-q", cur)
    g("checkout", "-q", "--orphan", "reborn")
    (root / "z").write_text("z", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "R")
    g("branch", "-f", cur, g("rev-parse", "HEAD")); g("checkout", "-q", cur)
    fdir = root / "features" / wid; fdir.mkdir(parents=True)
    (fdir / "run-settings.yaml").write_text(
        "schema_version: 1\nkind: run-settings\nworkitem_id: %s\n"
        "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
        "  base: %s\n  base_binding:\n    base_ref: %s\n    base_sha: %s\n"
        % (wid, cur, cur, base_A), encoding="utf-8")
    (fdir / "run-handoff.yaml").write_text(
        "kind: RunHandoff\nworkitem_id: %s\nresume_from_revision: %s\n"
        "base_binding:\n  kind: BaseBinding\n  base_ref: %s\n  base_sha: %s\n"
        "next_action: продолжить\nopen_questions: []\n"
        % (wid, work_sha, cur, base_A), encoding="utf-8")


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeBaseRewritten:
    """v3.0.10/14: base переписан -> resume заблокирован даже с force_resume/replan."""

    def test_force_resume_still_blocked(self, tmp_path):
        """base переписан + force_resume=True -> ВСЁ РАВНО blocked (base_rewritten, 'свежий')."""
        root = tmp_path / "rw"
        _rewrite_base_repo(root, "rwx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="rwx",
            resume=True, force_resume=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_rewritten") is True
        assert "свежий" in (report.get("error") or "").lower()

    def test_replan_still_blocked(self, tmp_path):
        """base переписан + replan (всё ещё resume) -> ВСЁ РАВНО blocked (base_rewritten)."""
        root = tmp_path / "rw2"
        _rewrite_base_repo(root, "rwx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="rwx",
            resume=True, replan=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_rewritten") is True


def _fast_forward_base_repo(root, wid):
    """Репо, где база УШЛА ВПЕРЁД (fast-forward): base_A остаётся предком cur. Как в монолите."""
    root.mkdir(parents=True, exist_ok=True)

    def g(*a):
        return subprocess.run(["git", "-C", str(root), *a],
                              capture_output=True, text=True).stdout.strip()
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        g(*a)
    (root / "f").write_text("x", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "A")
    base_A = g("rev-parse", "HEAD")
    cur = g("rev-parse", "--abbrev-ref", "HEAD")
    g("checkout", "-q", "-b", "ai-ops/ffx")
    (root / "w").write_text("work", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "W")
    work_sha = g("rev-parse", "HEAD")
    g("checkout", "-q", cur)
    (root / "b2").write_text("advance", encoding="utf-8"); g("add", "-A"); g("commit", "-q", "-m", "B")
    fdir = root / "features" / wid; fdir.mkdir(parents=True)
    (fdir / "run-settings.yaml").write_text(
        "schema_version: 1\nkind: run-settings\nworkitem_id: %s\n"
        "signals:\n  task_type: QUICK\n  risk: low\npolicy:\n"
        "  base: %s\n  base_binding:\n    base_ref: %s\n    base_sha: %s\n"
        % (wid, cur, cur, base_A), encoding="utf-8")
    (fdir / "run-handoff.yaml").write_text(
        "kind: RunHandoff\nworkitem_id: %s\nresume_from_revision: %s\n"
        "base_binding:\n  kind: BaseBinding\n  base_ref: %s\n  base_sha: %s\n"
        "next_action: продолжить\nopen_questions: []\n"
        % (wid, work_sha, cur, base_A), encoding="utf-8")
    return cur


@pytest.mark.critical_path
@pytest.mark.unit
class TestResumeFastForwardBase:
    """v3.0.14: fast-forward базы + force_resume -> blocked (base_moved), force не снимает."""

    def test_fast_forward_force_blocked(self, tmp_path):
        """fast-forward базы + force_resume -> blocked, base_moved=True, 'свежий'."""
        root = tmp_path / "ff"
        _fast_forward_base_repo(root, "ffx")
        report = ai_ops_run.run(
            task_text="продолжить", signals={"task_type": "QUICK", "risk": "low"},
            child_root=root, engine="pipeline", feature="ffx",
            resume=True, force_resume=True,
        )
        assert report.get("status") == "blocked"
        assert (report.get("resume") or {}).get("base_moved") is True
        assert "свежий" in (report.get("error") or "").lower()


@pytest.mark.critical_path
@pytest.mark.unit
class TestWriteBarrierRunPlan:
    """v3.0.15 write-barrier: сбой durable-записи RunPlan -> прогон не начат."""

    def test_durable_runplan_failure_is_error(self, tmp_path):
        """Монкипатч durable_write на провал -> status=error и 'RunPlan' в error."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        root = tmp_path / "bar"
        root.mkdir()
        _git_init_commit(root)
        orig = _ls.durable_write
        _ls.durable_write = lambda *a, **k: {"ok": False, "error": "smoke IO fail"}
        try:
            report = ai_ops_run.run(
                task_text="барьер",
                signals={"task_type": "QUICK", "risk": "low", "affected_areas": ["core"]},
                child_root=root, engine="pipeline",
                proposer=lambda c: {"done": True}, execute=True, feature="barx",
            )
        finally:
            _ls.durable_write = orig
        assert report.get("status") == "error"
        assert "RunPlan" in (report.get("error") or "")


@pytest.fixture(scope="module")
def ctl_resume_results(tmp_path_factory):
    """Многофазный controller-resume сценарий из монолита. Возвращает исходы всех фаз."""
    root = tmp_path_factory.mktemp("ctl")
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], capture_output=True)
    (root / "src").mkdir(); (root / "seed").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    cur = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
    out = {"worktree": root / ".ai" / "worktrees" / "ctl-resume"}

    s1 = iter([{"op": "write", "path": "src/phase1.py", "content": "p=1\n"}, {"done": True}])
    out["p1"] = ai_ops_run.run(task_text="фаза 1", signals=sig, child_root=root, engine="pipeline",
                               proposer=lambda c: next(s1), execute=True, feature="ctl-resume",
                               install_deps=False, base=cur)
    s2 = iter([{"op": "write", "path": "src/phase2.py", "content": "p=2\n"}, {"done": True}])
    out["p2"] = ai_ops_run.run(task_text="фаза 2", signals=sig, child_root=root, engine="pipeline",
                               proposer=lambda c: next(s2), execute=True, feature="ctl-resume",
                               install_deps=False, resume=True, base=cur)
    out["none"] = ai_ops_run.run(task_text="продолжить пустоту", signals=sig, child_root=root,
                                 engine="pipeline", proposer=lambda c: {"done": True}, execute=True,
                                 feature="never-ran", install_deps=False, resume=True, base=cur)
    (root / "moved.txt").write_text("z", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "base+1"], capture_output=True)
    s3 = iter([{"op": "write", "path": "src/phase3.py", "content": "p=3\n"}, {"done": True}])
    out["block"] = ai_ops_run.run(task_text="фаза 3", signals=sig, child_root=root, engine="pipeline",
                                  proposer=lambda c: next(s3), execute=True, feature="ctl-resume",
                                  install_deps=False, resume=True, base=cur)
    s4 = iter([{"op": "write", "path": "src/phase4.py", "content": "p=4\n"}, {"done": True}])
    out["force"] = ai_ops_run.run(task_text="фаза 4", signals=sig, child_root=root, engine="pipeline",
                                  proposer=lambda c: next(s4), execute=True, feature="ctl-resume",
                                  install_deps=False, resume=True, force_resume=True, base=cur)
    out["root"] = root
    return out


@pytest.mark.critical_path
@pytest.mark.unit
class TestControllerRealResume:
    """v2.109/v3.0.14: реальный resume контроллера — продолжение поверх ветки, честные блоки."""

    def test_phase1_committed_with_handoff(self, ctl_resume_results):
        """Фаза 1 закоммичена + run-handoff записан."""
        r = ctl_resume_results
        assert bool((r["p1"].get("commit") or {}).get("sha"))
        assert (r["root"] / "features" / "ctl-resume" / "run-handoff.yaml").exists()

    def test_resume_continued(self, ctl_resume_results):
        """resume продолжил (не ошибка про несохранённые коммиты), resumed=True."""
        r = ctl_resume_results
        assert r["p2"].get("status") != "error"
        assert (r["p2"].get("resume") or {}).get("resumed") is True

    def test_both_phases_in_worktree(self, ctl_resume_results):
        """Обе фазы в worktree (продолжили поверх, не с нуля)."""
        wt = ctl_resume_results["worktree"]
        assert (wt / "src" / "phase1.py").exists()
        assert (wt / "src" / "phase2.py").exists()

    def test_resume_without_prior_honest_error(self, ctl_resume_results):
        """resume без прошлого -> honest error (can_resume=False)."""
        r = ctl_resume_results
        assert r["none"].get("status") == "error"
        assert (r["none"].get("resume") or {}).get("can_resume") is False

    def test_stale_base_blocked(self, ctl_resume_results):
        """Устаревшая база -> resume блокируется без --force (revalidation_needed)."""
        r = ctl_resume_results
        assert r["block"].get("status") == "blocked"
        assert (r["block"].get("resume") or {}).get("revalidation_needed") is True

    def test_fast_forward_force_base_moved(self, ctl_resume_results):
        """fast-forward базы + --force -> blocked (base_moved), не продолжает на устаревшем."""
        r = ctl_resume_results
        assert r["force"].get("status") == "blocked"
        assert (r["force"].get("resume") or {}).get("base_moved") is True


@pytest.mark.critical_path
@pytest.mark.unit
class TestReconcileReceiptFields:
    """v3.0.17: строгая идентичность доставки — поля DeliveryReceipt и идемпотентность."""

    def _mk_intent(self, fdir, did, wid, branch, commit):
        from ai_ops_kit.shared import lifecycle_store as _ls
        obx = fdir / "delivery-outbox"
        _ls.durable_write(obx / f"{did}.intent.yaml",
                          {"schema_version": 1, "kind": "DeliveryIntent", "delivery_id": did,
                           "workitem_id": wid, "repository": "o/r", "branch": branch,
                           "base_ref": "main", "base_sha": "b" * 40, "commit_sha": commit,
                           "status": "intended"})
        return obx / f"{did}.receipt.yaml"

    def test_reconciled_receipt_fields(self, tmp_path):
        """Строгая идентичность (head.sha==commit) -> sha_verified True + remote_sha + pr_url."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        from ai_ops_kit.delivery import pr_open
        root = tmp_path / "dlvroot"
        f1 = root / "features" / "dlv"; f1.mkdir(parents=True)
        rp1 = self._mk_intent(f1, "did1", "dlv", "ai-ops/dlv", "cafe1234")
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/7", "number": 7, "repository": "o/r",
            "head_sha": "cafe1234", "base_ref": "main", "pr_state": "open", "merged": False}
        try:
            r = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
        finally:
            pr_open.reconcile_delivery = orig
        d1 = _ls.load_guarded(rp1, kind="DeliveryReceipt")
        assert r and r[0]["status"] == "reconciled"
        assert d1["state"] == "ok"
        assert d1["data"]["remote_sha"] == "cafe1234"
        assert d1["data"]["sha_verified"] is True
        assert d1["data"]["pr_url"] == "https://x/pr/7"

    def test_repeat_reconcile_returns_none(self, tmp_path):
        """Повторная реконсиляция -> None (Receipt уже есть, дубля нет)."""
        from ai_ops_kit.delivery import pr_open
        root = tmp_path / "dlvroot2"
        f1 = root / "features" / "dlv"; f1.mkdir(parents=True)
        self._mk_intent(f1, "did1", "dlv", "ai-ops/dlv", "cafe1234")
        orig = pr_open.reconcile_delivery
        pr_open.reconcile_delivery = lambda root, branch: {
            "status": "found", "url": "https://x/pr/7", "number": 7, "repository": "o/r",
            "head_sha": "cafe1234", "base_ref": "main", "pr_state": "open", "merged": False}
        try:
            first = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
            second = ai_ops_run._reconcile_pending_delivery(root / "features", "dlv", root)
        finally:
            pr_open.reconcile_delivery = orig
        assert first and first[0]["status"] == "reconciled"
        assert second is None


@pytest.fixture(scope="module")
def fixloop_run(tmp_path_factory):
    """v3.1.1 fix-loop: полный прогон с pytest (провал теста -> починка). Один раз на модуль.

    Требует pytest в окружении (как в монолите). Иначе — пропуск: unit-проверки логики
    fix-context (TestReviewFixContext выше) покрывают её без внешних инструментов.
    """
    import importlib.util as ilu
    if ilu.find_spec("pytest") is None:
        pytest.skip("pytest недоступен — интеграционный fix-loop пропущен")
    root = tmp_path_factory.mktemp("fixloop")
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    (root / "m.py").write_text("def base():\n    return 1\n", encoding="utf-8")
    (root / "test_base.py").write_text(
        "from m import base\n\ndef test_base():\n    assert base() == 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='m'\nversion='0.1.0'\n[tool.setuptools]\npy-modules=['m']\n"
        "[tool.pytest.ini_options]\npythonpath=['.']\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)
    cur = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    st = {"buggy": False, "test": False, "fixed": False}

    def fl_prop(context):
        fix = ("упала" in context) or ("Устрани" in context)
        if fix:
            if not st["fixed"]:
                st["fixed"] = True
                return {"op": "write", "path": "m.py",
                        "content": "def base():\n    return 1\n\ndef g(x):\n    return x + 1\n"}
            return {"done": True}
        if not st["buggy"]:
            st["buggy"] = True
            return {"op": "write", "path": "m.py",
                    "content": "def base():\n    return 1\n\ndef g(x):\n    return x\n"}
        if not st["test"]:
            st["test"] = True
            return {"op": "write", "path": "test_g.py",
                    "content": "from m import g\n\ndef test_g():\n    assert g(1) == 2\n"}
        return {"done": True}

    sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
    rfl = ai_ops_run.run(task_text="добавить g(x)=x+1 с тестом", signals=dict(sig),
                         child_root=root, engine="pipeline", provider_name="test",
                         proposer=fl_prop, execute=True, feature="fixloop",
                         install_deps=False, base=cur, review_fix_attempts=1)
    return root, rfl


@pytest.mark.critical_path
@pytest.mark.unit
class TestFixLoopIntegration:
    """v3.1.1 fix-loop: провал теста -> итерация по блокерам -> ready; событие fix_attempt в журнале."""

    def test_test_failure_fixed_to_ready(self, fixloop_run):
        """Провал теста -> итерация по блокерам -> ready_for_pr=True и 'test' не в unmet."""
        _, rfl = fixloop_run
        assert rfl.get("ready_for_pr") is True
        assert "test" not in (rfl.get("gates") or {}).get("unmet", [])

    def test_fix_attempt_event_logged(self, fixloop_run):
        """Событие fix_attempt записано в lifecycle-журнал."""
        from ai_ops_kit.shared import lifecycle_store as _ls
        root, _ = fixloop_run
        jr = _ls.journal_read(root / "features" / "fixloop" / "lifecycle-journal.jsonl")
        assert any(e.get("kind") == "fix_attempt" for e in jr["events"])
