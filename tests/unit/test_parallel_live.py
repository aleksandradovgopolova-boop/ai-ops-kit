"""Гранулярные тесты parallel_live (мигрировано из test_parallel_live_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import importlib.util as _ilu
import os as _os
import subprocess
import tempfile

import pytest

from parallel_live import (
    Path,
    _ensure_identity,
    _git,
    _glob_match,
    _pkg_signals,
    _scope_ok,
    make_integration_runner,
    make_isolated_package_runner,
    package_result_from_rep,
    pe,
    preflight_disposable,
    run_live_concurrent,
)


# ── package_result_from_rep ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestPackageResultFromRep:
    def test_ready_gives_pass(self):
        assert package_result_from_rep(
            {"ready_for_pr": True, "commit": {"sha": "a" * 40}})["status"] == "pass"

    def test_not_ready_gives_fail(self):
        assert package_result_from_rep(
            {"ready_for_pr": False, "commit": {"sha": "b" * 40}})["status"] == "fail"

    def test_none_gives_error(self):
        assert package_result_from_rep(None)["status"] == "error"


# ── orchestration with mock runners ─────────────────────────────────────────────

@pytest.fixture
def simple_wg():
    return {
        "schema_version": 1, "kind": "WorkGraph", "id": "WG-T", "feature": "f",
        "execution_mode": "hybrid",
        "packages": [
            {"id": "api", "depends_on": [], "write_scope": ["a/**"]},
            {"id": "ui", "depends_on": [], "write_scope": ["b/**"]},
        ],
    }


def _fake_run(task, sig, root, **kw):
    return {"ready_for_pr": True, "commit": {"sha": kw["feature"].ljust(40, "0")}}


def _pr_runner(pkg):
    return package_result_from_rep(_fake_run(None, None, None, feature=pkg["id"]))


def _ir_runner(results):
    return ("c" * 40, {"all_pass": True, "tested_revision": "c" * 40}, 0, False)


@pytest.mark.unit
class TestOrchestrationMock:
    def test_two_green_packages_fan_in(self, simple_wg):
        rec = pe.execute_parallel(simple_wg, _pr_runner, _ir_runner, contract_shas=None, max_parallel=1)
        assert rec["proceed"]
        assert rec["delivery"]["open_pr"]
        assert rec["integration_sha"] == "c" * 40

    def test_conflict_at_fan_in_no_pr(self, simple_wg):
        def ir_conflict(results):
            return ("d" * 40, {"all_pass": False, "tested_revision": "d" * 40}, 1, False)
        rec = pe.execute_parallel(simple_wg, _pr_runner, ir_conflict, contract_shas=None, max_parallel=1)
        assert rec["delivery"]["open_pr"] is False

    def test_package_fail_blocks_fan_in(self, simple_wg):
        def pr_fail(pkg):
            return {"status": "fail", "sha": None, "gate_report": {"all_pass": False}}
        rec = pe.execute_parallel(simple_wg, pr_fail, _ir_runner, contract_shas=None, max_parallel=1)
        assert rec["delivery"]["open_pr"] is False
        assert rec["stage"] == "pre-fan-in"


# ── preflight disposable ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPreflightDisposable:
    def test_clean_checkout_ok(self):
        with tempfile.TemporaryDirectory() as td:
            _git(td, "init", "-q", check=False)
            _git(td, "config", "user.email", "t@t")
            _git(td, "config", "user.name", "t")
            (Path(td) / "a.py").write_text("x=1\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-qm", "init", check=False)
            okp, _ = preflight_disposable(td)
            assert okp is True

    def test_dirty_checkout_refused(self):
        with tempfile.TemporaryDirectory() as td:
            _git(td, "init", "-q", check=False)
            _git(td, "config", "user.email", "t@t")
            _git(td, "config", "user.name", "t")
            (Path(td) / "a.py").write_text("x=1\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-qm", "init", check=False)
            (Path(td) / "dirty.py").write_text("y=2\n", encoding="utf-8")
            okp, rsn = preflight_disposable(td)
            assert okp is False
            assert "грязный" in rsn


# ── stack-aware integration runner ──────────────────────────────────────────────

_has_pytest = _ilu.find_spec("pytest") is not None


@pytest.mark.unit
class TestStackAwareIntegration:
    def test_aggregate_is_stack_aware(self):
        with tempfile.TemporaryDirectory() as td:
            _git(td, "init", "-q", check=False)
            _git(td, "config", "user.email", "t@t")
            _git(td, "config", "user.name", "t")
            (Path(td) / "pyproject.toml").write_text(
                "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n",
                encoding="utf-8")
            Path(td, "tests").mkdir()
            (Path(td) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-qm", "seed", check=False)
            base = _git(td, "rev-parse", "HEAD").stdout.strip()
            _git(td, "checkout", "-q", "-b", "ai-ops/p1", check=False)
            (Path(td) / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-qm", "p1", check=False)
            _git(td, "checkout", "-q", base, check=False)
            ir = make_integration_runner(td, base, integration_branch="ai-ops/it-test")
            _isha, agg, _conf, _bm = ir({"p1": {"status": "pass"}})
            assert agg.get("stack_aware") is True
            assert "test" in (agg.get("stack_checks") or {})
            if _has_pytest:
                assert agg.get("all_pass") is True
                assert _conf == 0


# ── true concurrent execution ───────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.unit
class TestRunLiveConcurrent:
    def _setup_repo(self, td):
        _git(td, "init", "-q", check=False)
        _git(td, "config", "user.email", "t@t")
        _git(td, "config", "user.name", "t")
        (Path(td) / "pyproject.toml").write_text(
            "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n",
            encoding="utf-8")
        Path(td, "tests").mkdir()
        (Path(td) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        _git(td, "add", "-A")
        _git(td, "commit", "-qm", "seed", check=False)
        return _git(td, "rev-parse", "HEAD").stdout.strip()

    def _commit_run(self, task, sig, root, **kw):
        pid = kw["feature"]
        _git(root, "config", "user.email", "t@t")
        _git(root, "config", "user.name", "t")
        _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
        (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", f"pkg {pid}", check=False)
        return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}

    def test_concurrent_execution_with_per_package_clone(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cdir:
            base = self._setup_repo(td)
            wg = {
                "schema_version": 1, "kind": "WorkGraph", "id": "WG-C", "feature": "f",
                "execution_mode": "hybrid",
                "packages": [
                    {"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                    {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]},
                ],
            }
            rec = run_live_concurrent(wg, td, base, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                                      self._commit_run, cdir)
            assert rec.get("execution_concurrency") == "concurrent"
            assert rec.get("isolation") == "per-package-clone"
            assert all((Path(cdir) / p).is_dir() for p in ("aa", "bb", "_integration"))
            agg = rec.get("aggregate") or {}
            assert agg.get("conflicts") == 0

    def test_delivery_plan_returned(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cdir:
            base = self._setup_repo(td)
            wg = {
                "schema_version": 1, "kind": "WorkGraph", "id": "WG-C", "feature": "f",
                "execution_mode": "hybrid",
                "packages": [
                    {"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                    {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]},
                ],
            }
            rec = run_live_concurrent(wg, td, base, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                                      self._commit_run, cdir)
            dp = rec.get("delivery_plan") or {}
            assert dp.get("kind") == "DeliveryPlan"
            assert "github_remote" in dp
            assert rec.get("pr") is None

    @pytest.mark.skipif(not _has_pytest, reason="requires pytest")
    def test_concurrent_fan_in_green(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cdir:
            base = self._setup_repo(td)
            wg = {
                "schema_version": 1, "kind": "WorkGraph", "id": "WG-C", "feature": "f",
                "execution_mode": "hybrid",
                "packages": [
                    {"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                    {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]},
                ],
            }
            rec = run_live_concurrent(wg, td, base, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                                      self._commit_run, cdir)
            assert rec.get("proceed") is True
            assert rec.get("delivery", {}).get("open_pr") is True
            dp = rec.get("delivery_plan") or {}
            assert dp.get("ready") is True
            assert bool(dp.get("integration_sha"))


# ── post-commit scope ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPostCommitScope:
    def _setup_repo(self, td):
        _git(td, "init", "-q", check=False)
        _git(td, "config", "user.email", "t@t")
        _git(td, "config", "user.name", "t")
        (Path(td) / "pyproject.toml").write_text(
            "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n",
            encoding="utf-8")
        Path(td, "tests").mkdir()
        (Path(td) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        _git(td, "add", "-A")
        _git(td, "commit", "-qm", "seed", check=False)
        return _git(td, "rev-parse", "HEAD").stdout.strip()

    def test_write_outside_scope_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = self._setup_repo(td)

            def rogue_run(task, sig, root, **kw):
                pid = kw["feature"]
                _git(root, "config", "user.email", "t@t")
                _git(root, "config", "user.name", "t")
                _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
                (Path(root) / "OUTSIDE_scope.py").write_text("x=1\n", encoding="utf-8")
                _git(root, "add", "-A")
                _git(root, "commit", "-qm", f"rogue {pid}", check=False)
                _sha = _git(root, "rev-parse", "HEAD").stdout.strip()
                _git(root, "checkout", "-q", base, check=False)
                return {"ready_for_pr": True, "commit": {"sha": _sha}}

            with tempfile.TemporaryDirectory() as cdir:
                runner = make_isolated_package_runner(td, base, {"cc": "t"}, {"task_type": "QUICK"},
                                                       rogue_run, cdir, {})
                res = runner({"id": "cc", "write_scope": ["cc.py"]})
                assert res.get("status") == "fail"
                assert "OUTSIDE_scope.py" in (res.get("scope_violation") or [])

    def test_write_within_scope_passes(self):
        with tempfile.TemporaryDirectory() as td:
            base = self._setup_repo(td)

            def commit_run(task, sig, root, **kw):
                pid = kw["feature"]
                _git(root, "config", "user.email", "t@t")
                _git(root, "config", "user.name", "t")
                _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
                (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
                _git(root, "add", "-A")
                _git(root, "commit", "-qm", f"pkg {pid}", check=False)
                return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}

            with tempfile.TemporaryDirectory() as cdir:
                runner = make_isolated_package_runner(td, base, {"cc": "t"}, {"task_type": "QUICK"},
                                                       commit_run, cdir, {})
                res = runner({"id": "cc", "write_scope": ["cc.py"]})
                assert (res.get("scope_check") or {}).get("ok") is True


# ── identity fallback ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestEnsureIdentity:
    def test_fallback_set_when_unresolvable(self):
        with tempfile.TemporaryDirectory() as tdi:
            src = Path(tdi) / "src"
            src.mkdir()
            _git(src, "init", "-q", check=False)
            _git(src, "config", "user.email", "own@t")
            _git(src, "config", "user.name", "own")
            (src / "f.py").write_text("x=1\n", encoding="utf-8")
            _git(src, "add", "-A")
            _git(src, "commit", "-qm", "seed", check=False)
            cl = Path(tdi) / "clone"
            subprocess.run(["git", "clone", "-q", str(src), str(cl)], capture_output=True, text=True)
            saved = {k: _os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")}
            try:
                _os.environ["GIT_CONFIG_GLOBAL"] = _os.devnull
                _os.environ["GIT_CONFIG_SYSTEM"] = _os.devnull
                resolvable = subprocess.run(
                    ["git", "-C", str(cl), "var", "GIT_COMMITTER_IDENT"],
                    capture_output=True, text=True).returncode == 0
                assert _ensure_identity(cl) is (not resolvable)
                (cl / "g.py").write_text("y=2\n", encoding="utf-8")
                _git(cl, "add", "-A")
                assert _git(cl, "commit", "-qm", "c", check=False).returncode == 0
                assert _ensure_identity(src) is False
                assert _git(src, "config", "user.email").stdout.strip() == "own@t"
            finally:
                for _k, _v in saved.items():
                    if _v is None:
                        _os.environ.pop(_k, None)
                    else:
                        _os.environ[_k] = _v


# ── helpers ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHelpers:
    def test_pkg_signals_affected_areas(self):
        sig = _pkg_signals({"task_type": "X"}, {"id": "p", "write_scope": ["api/**", "db/x.py"]})
        assert sig.get("affected_areas") == ["api", "db"]

    def test_glob_match_nested(self):
        assert _glob_match("api/routes/x.py", "api/**")
        assert not _glob_match("ui/x.py", "api/**")

    def test_scope_ok_infra_paths(self):
        ok, violations = _scope_ok([".ai/plan.yaml", "api/x.py", "ui/y.py"], ["api/**"])
        assert ok is False
        assert "ui/y.py" in violations

    def test_scope_ok_build_artifacts_excluded(self):
        ok, violations = _scope_ok(
            ["calc.py", "tasks.egg-info/PKG-INFO", "__pycache__/x.pyc", "package-lock.json"],
            ["calc.py"])
        assert ok is True
        assert violations == []

    def test_scope_ok_rogue_file_caught(self):
        ok, violations = _scope_ok(
            ["calc.py", "tasks.egg-info/PKG-INFO", "rogue.py"], ["calc.py"])
        assert ok is False
        assert "rogue.py" in violations


@pytest.mark.unit
class TestSelfCleanClonesDir:
    def test_self_created_clones_dir_cleaned(self):
        with tempfile.TemporaryDirectory() as td:
            _git(td, "init", "-q", check=False)
            _git(td, "config", "user.email", "t@t")
            _git(td, "config", "user.name", "t")
            (Path(td) / "s.py").write_text("x=1\n", encoding="utf-8")
            _git(td, "add", "-A")
            _git(td, "commit", "-qm", "s", check=False)
            base = _git(td, "rev-parse", "HEAD").stdout.strip()

            def commit_run(task, sig, root, **kw):
                pid = kw["feature"]
                _git(root, "config", "user.email", "t@t")
                _git(root, "config", "user.name", "t")
                _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}", check=False)
                (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
                _git(root, "add", "-A")
                _git(root, "commit", "-qm", f"pkg {pid}", check=False)
                return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}

            pre = set(Path(tempfile.gettempdir()).glob("ai-ops-parallel-*"))
            run_live_concurrent(
                {"schema_version": 1, "kind": "WorkGraph", "id": "WG-X", "feature": "f",
                 "execution_mode": "hybrid",
                 "packages": [{"id": "z", "depends_on": [], "write_scope": ["z.py"]}]},
                td, base, {"z": "t"}, {"task_type": "QUICK"}, commit_run)
            post = set(Path(tempfile.gettempdir()).glob("ai-ops-parallel-*"))
            assert post == pre
