"""Гранулярные тесты workpackage_executor (мигрировано из test_workpackage_executor_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
import tempfile

import pytest

from workpackage_executor import (
    Path,
    _aggregate_close_security,
    _aggregate_code_review,
    _collect_base_checks_at,
    _git,
    _hard_stop,
    _ordered,
    _pkg_hash,
    _plan_hash,
    _validate_sequence_plan_schema,
    execute_sequence,
    json,
    retry_package,
)

import atomic_planner


# ─── helpers ───────────────────────────────────────────────────────────────────

def _mkrepo(td):
    (Path(td) / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
              ("add", "-A"), ("commit", "-q", "-m", "i")):
        _git(td, *a)
    return _git(td, "rev-parse", "--abbrev-ref", "HEAD")[1]


def _author(prompt):
    if "requirements-artifact" in prompt:
        return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                "  - id: R1\n    statement: пакет реализован\n    acceptance:\n      - when готово then тест зелёный\n")
    if "spec-change" in prompt:
        return ("schema_version: 1\nkind: spec-change\ncapability: mod\nwhy: нужно\n"
                "what_changes:\n  - изменение\ntasks:\n  - шаг\nrequirements:\n"
                "  - name: R\n    text: The system SHALL work.\n    scenarios:\n"
                "      - {name: T, when: x, then: y}\n")
    return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
            "  - id: WP1\n    summary: пакет\n    depends_on: []\nwrite_scope:\n  - .\n")


def _pass_reviewer(prompt):
    p = prompt or ""
    _cand = re.search(r"\+\+\+ b/(\S+)", p)
    _path = _cand.group(1) if _cand else "calc.py"
    if f"--- {_path} ---" not in p:
        return json.dumps({"op": "read", "path": _path})
    res = {"kind": "reviewer-result", "status": "pass", "checks": [{"id": "ok", "status": "pass"}]}
    m = re.search(r"применимым доменам:\s*([^\n(]+)", p)
    if m:
        doms = [d.strip() for d in m.group(1).split(",") if d.strip()]
        if doms:
            res["domain_results"] = [{"domain": d, "status": "pass",
                                      "checks": [{"id": f"{d}_ok", "status": "pass"}],
                                      "evidence": [{"type": "code-read", "path": _path, "lines": "1-10"}]}
                                     for d in doms]
    return json.dumps(res, ensure_ascii=False)


def _prop_for(pkg):
    fname = f"src/{pkg['id']}.py"
    it = iter([{"op": "write", "path": fname, "content": f"# {pkg['id']}\nx=1\n"}, {"done": True}])
    return lambda c: next(it)


def _prop_ws(pkg):
    sub = (pkg.get("scope") or ["core"])[0]
    it = iter([{"op": "write", "path": f"src/{sub}/mod.py", "content": "x = 1\n"}, {"done": True}])
    return lambda c: next(it)


def _valid_plan(wid="seq"):
    _o = _ordered([{"id": "WP1", "order": 1, "depends_on": [], "scope": "a", "write_scope": ["."]},
                   {"id": "WP2", "order": 2, "depends_on": ["WP1"], "scope": "b", "write_scope": ["."]}])
    return {"schema_version": 1, "kind": "SequencePlan", "workitem_id": wid, "total": 2,
            "plan_hash": _plan_hash(_o), "base_ref": "main", "sequence_base_sha": "deadbeef",
            "packages": [{"id": p["id"], "order": p["order"], "depends_on": p["depends_on"],
                          "scope": p["scope"], "write_scope": p["write_scope"],
                          "pkg_hash": _pkg_hash(p)} for p in _o]}


def _reseal(plan):
    for _p in plan["packages"]:
        _p["pkg_hash"] = _pkg_hash(_p)
    plan["plan_hash"] = _plan_hash(_ordered(plan["packages"]))
    return plan


# ─── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def three_area_sig():
    return {"task_type": "ENGINEERING", "size": "large", "risk": "low",
            "affected_areas": ["catalog", "orders", "billing"]}


@pytest.fixture
def two_area_sig():
    return {"task_type": "ENGINEERING", "size": "large", "risk": "low",
            "affected_areas": ["catalog", "orders"]}


# ─── Plan decomposition ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestPlanDecomposition:
    def test_three_packages_with_deps(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mkrepo(td)
            wp = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)
            pkgs = wp["work_packages"]
            assert len(pkgs) == 3
            assert pkgs[1]["depends_on"] == [pkgs[0]["id"]]


# ─── execute_sequence: happy path ──────────────────────────────────────────────

@pytest.mark.unit
class TestExecuteSequenceHappyPath:
    def test_all_three_executed(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert seq["executed_all"] is True

    def test_unique_sha_per_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            shas = [p.get("sha") for p in seq["packages"]]
            assert all(shas) and len(set(shas)) == 3

    def test_sequential_chain(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert seq["sequential_chain"] is True

    def test_per_package_reports_on_disk(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all((root / "features" / "seq" / "work-packages" / p["id"] / "report.json").is_file()
                       for p in seq["packages"])

    def test_sequence_report_saved(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert (root / "features" / "seq" / "sequence-report.yaml").is_file()

    def test_resume_point_per_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all(p.get("resume_point") for p in seq["packages"])


# ─── v2.124: immutable SequencePlan + lifecycle ────────────────────────────────

@pytest.mark.unit
class TestSequencePlanImmutable:
    def test_sequence_plan_yaml_written(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                 feature="seq", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            assert (root / "features" / "seq" / "sequence-plan.yaml").is_file()

    def test_sequence_base_sha_durable(self, three_area_sig):
        import yaml as _yy
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                 feature="seq", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            plan = _yy.safe_load((root / "features" / "seq" / "sequence-plan.yaml").read_text(encoding="utf-8"))
            assert bool(plan.get("sequence_base_sha")) and bool(plan.get("base_ref"))

    def test_corrupt_plan_lifecycle_corrupted(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rc = Path(td)
            cur_c = _mkrepo(td)
            pk = atomic_planner.decompose(three_area_sig, wid="seqc", child_root=rc)["work_packages"]
            (rc / "features" / "seqc").mkdir(parents=True, exist_ok=True)
            (rc / "features" / "seqc" / "sequence-plan.yaml").write_text("{ это: [не, валидный, yaml", encoding="utf-8")
            before = (rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            seq_c = execute_sequence("x", three_area_sig, rc, pk, _prop_for, feature="seqc", base=cur_c,
                                     author=True, author_proposer=_author, review=True, reviewer_proposer=_pass_reviewer)
            after = (rc / "features" / "seqc" / "sequence-plan.yaml").read_text(encoding="utf-8")
            assert "lifecycle-corrupted" in (seq_c.get("error") or "")
            assert not seq_c.get("packages")
            assert after == before
            assert seq_c.get("corrupt_sha256")

    def test_per_package_lifecycle_snapshot(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert all((root / "features" / "seq" / "work-packages" / p["id"] / "run-plan.yaml").is_file()
                       for p in seq["packages"])

    def test_aggregate_ready_in_report(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert "aggregate_ready" in seq

    def test_aggregate_verify_on_final_sha(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            assert (seq.get("aggregate") or {}).get("verified") is True
            assert (seq.get("aggregate") or {}).get("final_sha") == seq["final_sha"]


# ─── Resume ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestResume:
    def test_head_not_at_checkpoint_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                       base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            seq_drift = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                         base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer,
                                         resume_from=pkgs[1]["id"])
            assert "error" in seq_drift
            assert "checkpoint" in (seq_drift.get("error") or "").lower()

    def test_valid_checkpoint_resumed_skip(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                       feature="seq", base=cur, author=True, author_proposer=_author,
                                       review=True, reviewer_proposer=_pass_reviewer)
            _git(root / ".ai" / "worktrees" / "seq", "reset", "--hard", seq["packages"][0]["sha"])
            buf2 = io.StringIO()
            with contextlib.redirect_stderr(buf2):
                seq_r = execute_sequence("большой рефактор", three_area_sig, root, pkgs, _prop_for,
                                         feature="seq", base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer,
                                         resume_from=pkgs[1]["id"])
            skipped = [p for p in seq_r["packages"] if p.get("status") == "resumed-skip"]
            assert "error" not in seq_r
            assert seq_r.get("resumed_from") == pkgs[1]["id"]
            assert len(skipped) == 1
            assert skipped[0]["id"] == pkgs[0]["id"]
            assert skipped[0].get("sha")

    def test_unknown_resume_from_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            seq_bad = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                       base=cur, resume_from="pkg-НЕТ-ТАКОГО")
            assert "error" in seq_bad
            assert seq_bad["executed_all"] is False
            assert not seq_bad["packages"]

    def test_plan_drift_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            # Сначала исполняем, чтобы sequence-plan.yaml появился на диске
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                 base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            pkgs_drift = [dict(p) for p in pkgs]
            pkgs_drift[0] = {**pkgs_drift[0], "scope": ["ДРУГАЯ-ПОДСИСТЕМА"]}
            seq_pd = execute_sequence("x", three_area_sig, root, pkgs_drift, _prop_for, feature="seq",
                                      base=cur, resume_from=pkgs[1]["id"])
            assert "error" in seq_pd
            assert "дрейф" in (seq_pd.get("error") or "").lower()

    def test_plan_drift_without_resume_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            # Сначала исполняем, чтобы sequence-plan.yaml появился на диске
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seq",
                                 base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            pkgs_drift = [dict(p) for p in pkgs]
            pkgs_drift[0] = {**pkgs_drift[0], "scope": ["ДРУГАЯ-ПОДСИСТЕМА"]}
            seq_pd2 = execute_sequence("x", three_area_sig, root, pkgs_drift, _prop_for, feature="seq", base=cur)
            assert "error" in seq_pd2
            assert "дрейф" in (seq_pd2.get("error") or "").lower()

    def test_unconfirmed_skipped_package_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqe", child_root=root)["work_packages"]
            seq_e = execute_sequence("x", three_area_sig, root, pkgs, _prop_for, feature="seqe",
                                     base=cur, resume_from=pkgs[1]["id"])
            assert "error" in seq_e
            assert pkgs[0]["id"] not in seq_e.get("completed", [])


# ─── Plan integrity validation ─────────────────────────────────────────────────

@pytest.mark.unit
class TestPlanIntegrity:
    def test_valid_plan_no_error(self):
        assert _validate_sequence_plan_schema(_valid_plan(), expected_wid="seq") is None

    def test_foreign_workitem_error(self):
        result = _validate_sequence_plan_schema(_valid_plan("OTHER"), expected_wid="seq")
        assert "чужой" in (result or "")

    def test_unsupported_schema_version(self):
        result = _validate_sequence_plan_schema({**_valid_plan(), "schema_version": 2}, expected_wid="seq")
        assert "schema_version" in (result or "")

    def test_duplicate_package_id(self):
        dup = _valid_plan()
        dup["packages"][1]["id"] = "WP1"
        _reseal(dup)
        result = _validate_sequence_plan_schema(dup, expected_wid="seq")
        assert "дубли package id" in (result or "")

    def test_duplicate_order(self):
        dupord = _valid_plan()
        dupord["packages"][1]["order"] = 1
        _reseal(dupord)
        result = _validate_sequence_plan_schema(dupord, expected_wid="seq")
        assert "дубли order" in (result or "")

    def test_depends_on_nonexistent(self):
        baddep = _valid_plan()
        baddep["packages"][1]["depends_on"] = ["WP-NONE"]
        _reseal(baddep)
        result = _validate_sequence_plan_schema(baddep, expected_wid="seq")
        assert "несуществующего" in (result or "")

    def test_dependency_cycle(self):
        cyc = _valid_plan()
        cyc["packages"][0]["depends_on"] = ["WP2"]
        _reseal(cyc)
        result = _validate_sequence_plan_schema(cyc, expected_wid="seq")
        assert "цикл" in (result or "")

    def test_tampered_pkg_hash(self):
        badpk = _valid_plan()
        badpk["packages"][0]["pkg_hash"] = "0" * 16
        result = _validate_sequence_plan_schema(badpk, expected_wid="seq")
        assert "pkg_hash не сходится" in (result or "")

    def test_tampered_plan_hash(self):
        badph = _valid_plan()
        badph["plan_hash"] = "0" * 16
        result = _validate_sequence_plan_schema(badph, expected_wid="seq")
        assert "plan_hash не сходится" in (result or "")


# ─── Provider exception handling ───────────────────────────────────────────────

@pytest.mark.unit
class TestProviderException:
    def test_connection_reset_honest_failure(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            p0 = seq_x["packages"][0] if seq_x.get("packages") else {}
            assert bool(p0.get("stop_reason"))
            assert "error" in (p0.get("stop_reason") or "")

    def test_failure_classified_network_retryable(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            p0 = seq_x["packages"][0] if seq_x.get("packages") else {}
            assert (p0.get("failure") or {}).get("failure_class") == "network"
            assert (p0.get("failure") or {}).get("retryable") is True
            assert (p0.get("failure") or {}).get("exception_type") == "ConnectionResetError"
            assert (p0.get("failure") or {}).get("traceback_hash")

    def test_chain_stops_at_failed_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            seq_x = execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                                     base=cur_x, author=True, author_proposer=boom_author, review=False)
            assert seq_x.get("stopped_at") == pkgs_x[0]["id"]
            assert len(seq_x["packages"]) == 1
            assert seq_x["executed_all"] is False
            assert seq_x["ready_all"] is False

    def test_per_package_snapshot_saved(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            rx = Path(td)
            cur_x = _mkrepo(td)
            pkgs_x = atomic_planner.decompose(three_area_sig, wid="seqx", child_root=rx)["work_packages"]

            def prop_boom(pkg):
                return lambda c: {"done": True}

            def boom_author(prompt):
                raise ConnectionResetError("[Errno 54] Connection reset by peer")

            execute_sequence("x", three_area_sig, rx, pkgs_x, prop_boom, feature="seqx",
                             base=cur_x, author=True, author_proposer=boom_author, review=False)
            assert (rx / "features" / "seqx" / "work-packages" / pkgs_x[0]["id"] / "report.json").is_file()


# ─── write_scope ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestWriteScope:
    def test_authored_artifacts_not_scope_violation(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seq", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq_ws = execute_sequence("рефактор со scope", three_area_sig, root, pkgs, _prop_ws,
                                          feature="seqws", base=cur, author=True, author_proposer=_author,
                                          review=True, reviewer_proposer=_pass_reviewer,
                                          write_scope_for=lambda pkg: pkg.get("write_scope"))
            assert not any("scope-violation" in (p.get("stop_reason") or "") for p in seq_ws["packages"])


# ─── _hard_stop ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHardStop:
    def test_no_commit_stop(self):
        assert _hard_stop({"commit": {"sha": None}}) == "no-commit"

    def test_regression_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "baseline": {"regressions": ["test"]}}) == "regression"

    def test_security_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "fail"}}) == "security-fail"

    def test_reviewer_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "reviews": [{"gate": "code_review", "status": "fail"}]}) == "reviewer-blocked"

    def test_reviewer_warn_blocking_stop(self):
        assert _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "blocked"}]}) == "reviewer-blocked"

    def test_gate_results_fail_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "reviews": [],
                           "gates": {"gate_results": [{"gate": "code_review", "status": "fail",
                                     "evidence": ["independent reviewer verdict @ abc"]}]}}) == "reviewer-blocked"

    def test_reviewer_warn_nonblocking_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"},
                           "reviews": [{"gate": "code_review", "status": "warn", "closed_as": "warn"}]}) is None

    def test_scope_violation_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["'x' вне write_scope ['src']"]}}) == "scope-violation"

    def test_awaiting_evidence_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "gates": {"blocked": True, "unmet": ["requirements"]}}) is None

    def test_blocked_push_not_scope_violation(self):
        assert _hard_stop({"commit": {"sha": "a"}, "loop": {"denied_reasons": ["git push запрещён политикой"]}}) is None

    def test_security_scan_blocked_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "blocked"}}) == "security-fail"

    def test_security_gate_fail_no_approval(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("dependencies: нет валидного ApprovalRecord")) == "security-gate-fail"

    def test_security_gate_fail_scanner_crash(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("security scan упал (fail-closed): boom")) == "security-gate-fail"

    def test_security_gate_fail_no_pass(self):
        def _g(blk):
            return {"commit": {"sha": "a"}, "gates": {"gate_results": [
                {"gate": "security", "status": "fail", "blockers": [blk]}]}}
        assert _hard_stop(_g("security-reviewer не вынес pass")) == "security-gate-fail"

    def test_needs_review_awaiting_no_stop(self):
        assert _hard_stop({"commit": {"sha": "a"}, "security_scan": {"overall": "needs_review"},
                           "gates": {"gate_results": [{"gate": "security", "status": "fail",
                           "blockers": ["нужен независимый security-reviewer/человек по доменам: input_validation"]}]}}) is None


# ─── open_pr not ready ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOpenPrNotReady:
    def test_not_ready_all_pr_not_opened(self, two_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(two_area_sig, wid="seqpr", child_root=root)["work_packages"]

            def prop_pr(pkg):
                it = iter([{"op": "write", "path": f"src/{pkg['id']}.py", "content": "x=1\n"}, {"done": True}])
                return lambda c: next(it)

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqpr = execute_sequence("рефактор", two_area_sig, root, pkgs, prop_pr, feature="seqpr",
                                         base=cur, open_pr=True)
            dpr = seqpr.get("delivery") or {}
            assert seqpr["ready_all"] is False
            assert dpr.get("status") == "not-attempted"
            assert seqpr.get("draft_pr") is None
            assert dpr.get("requested") is True


# ─── Reviewer fail/warn stops chain ───────────────────────────────────────────

@pytest.mark.unit
class TestReviewerFailStopsChain:
    def test_reviewer_fail_stops_chain(self, three_area_sig):
        def fail_reviewer(prompt):
            return json.dumps({"kind": "reviewer-result", "status": "fail",
                               "checks": [{"id": "c", "status": "fail"}], "blockers": ["FAIL"]})

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqr", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqr = execute_sequence("рефактор с fail-ревью", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqr", base=cur, author=True, author_proposer=_author,
                                        review=True, reviewer_proposer=fail_reviewer)
            ids_seen = [p["id"] for p in seqr["packages"]]
            assert seqr["stopped_at"] == pkgs[0]["id"]
            assert seqr["executed_all"] is False
            assert seqr["packages"][0]["stop_reason"] == "reviewer-blocked"
            assert pkgs[2]["id"] not in ids_seen


@pytest.mark.unit
class TestReviewerWarnBlockingStopsChain:
    def test_reviewer_warn_blocking_stops_chain(self, three_area_sig):
        warn_reviewer = lambda p: ('{"kind":"reviewer-result","status":"warn",'
                                   '"checks":[{"id":"c","status":"warn"}],"blockers":["сомнение по API"]}')

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqw", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqw = execute_sequence("рефактор с warn-ревью", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqw", base=cur, author=True, author_proposer=_author,
                                        review=True, reviewer_proposer=warn_reviewer)
            ids_w = [p["id"] for p in seqw["packages"]]
            assert seqw["stopped_at"] == pkgs[0]["id"]
            assert seqw["executed_all"] is False
            assert seqw["packages"][0]["stop_reason"] == "reviewer-blocked"
            assert pkgs[2]["id"] not in ids_w


# ─── retry_package ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRetryPackage:
    def test_retry_resets_to_predecessor_checkpoint(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seqrt = execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                         feature="seqrt", base=cur, author=True, author_proposer=_author,
                                         review=True, reviewer_proposer=_pass_reviewer)
            p1_sha = seqrt["packages"][0].get("sha")
            wt = root / ".ai" / "worktrees" / "seqrt"
            assert p1_sha
            assert (root / "features" / "seqrt" / "sequence-plan.yaml").is_file()

            rt = retry_package(root, "seqrt", pkgs[1]["id"])
            head_after = _git(wt if wt.is_dir() else root, "rev-parse", "HEAD")[1]
            assert rt.get("ok") is True
            assert rt.get("checkpoint") == p1_sha
            assert head_after == p1_sha
            assert rt.get("predecessor") == pkgs[0]["id"]

    def test_retry_archives_failed_attempt(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            retry_package(root, "seqrt", pkgs[1]["id"])
            assert (root / "features" / "seqrt" / "work-packages" / pkgs[1]["id"] / "attempts" / "attempt-1" / "report.json").is_file()

    def test_retry_unknown_package_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            assert retry_package(root, "seqrt", "НЕТ-ТАКОГО").get("ok") is False

    def test_base_contract_drift_error(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqrt", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор для retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqrt", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            seq_bd = execute_sequence("другая база", three_area_sig, root, pkgs, _prop_for, feature="seqrt",
                                      base="release-xyz", author=True, author_proposer=_author,
                                      review=True, reviewer_proposer=_pass_reviewer,
                                      resume_from=pkgs[1]["id"])
            assert "error" in seq_bd
            assert "base-contract-drift" in (seq_bd.get("error") or "")


# ─── retry safety ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRetrySafety:
    def test_no_worktree_fail_closed(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(three_area_sig, wid="seqsafe", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор safe-retry", three_area_sig, root, pkgs, _prop_for,
                                 feature="seqsafe", base=cur, author=True, author_proposer=_author,
                                 review=True, reviewer_proposer=_pass_reviewer)
            main_head_before = _git(root, "rev-parse", "HEAD")[1]
            main_status_before = _git(root, "status", "--porcelain")[1]

            wt = root / ".ai" / "worktrees" / "seqsafe"
            _git(root, "worktree", "remove", "--force", str(wt))
            shutil.rmtree(wt, ignore_errors=True)

            rt_unsafe = retry_package(root, "seqsafe", pkgs[1]["id"])
            main_head_after = _git(root, "rev-parse", "HEAD")[1]
            main_status_after = _git(root, "status", "--porcelain")[1]

            assert rt_unsafe.get("ok") is False
            assert "fail-closed" in (rt_unsafe.get("error") or "")
            assert main_head_after == main_head_before
            assert main_status_after == main_status_before


# ─── aggregate code_review ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestAggregateCodeReview:
    def test_no_verdict_ok_false(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            nover = lambda p: "я не буду выносить структурный вердикт, просто текст"
            ok_nv, _ = _aggregate_code_review(root, cur, cur, {"task_type": "ENGINEERING"}, nover, True)
            assert ok_nv is False

    def test_no_review_requested_ok_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            ok_nr, _ = _aggregate_code_review(root, cur, cur, {}, None, False)
            assert ok_nr is True


# ─── baseline provenance ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestBaselineProvenance:
    def test_nonexistent_base_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _mkrepo(td)
            assert _collect_base_checks_at(root, "0" * 40, False) is None

    def test_valid_base_proven_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            res = _collect_base_checks_at(root, _git(root, "rev-parse", "HEAD")[1], False)
            assert isinstance(res, dict)
            assert res.get("proven") is True


# ─── aggregate_close_security ──────────────────────────────────────────────────

@pytest.mark.unit
class TestAggregateCloseSecurity:
    def test_generic_reviewer_does_not_close_security(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        r_i, _ = _aggregate_close_security(dict(agg_nr), Path("."), None, isha, {}, gen_reviewer, True,
                                           security_reviewer_proposer=None, strict_judge_qualified=False,
                                           wid=None, child_root=None)
        assert r_i.get("overall") == "needs_review"
        assert r_i.get("closed_by") is None

    def test_human_approval_on_integration_sha_closes(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        with tempfile.TemporaryDirectory() as hd:
            _appr_t.write_record(hd, "seq-agg", approval="rate_limiting", approved_by="human@owner",
                                 scope="security rate_limiting", reason="человек одобрил integration-SHA",
                                 created_at="2026-07-29", binds_to=isha, expires_at="2026-12-31",
                                 risk="high", source="human")
            r_ii, _ = _aggregate_close_security(dict(agg_nr), Path(hd), None, isha, {}, gen_reviewer, True,
                                                security_reviewer_proposer=None, strict_judge_qualified=False,
                                                wid="seq-agg", child_root=hd)
            assert r_ii.get("overall") == "clear"
            assert r_ii.get("closed_by") == "human-approval-integration-sha"

    def test_approval_on_different_sha_does_not_close(self):
        import approvals as _appr_t
        isha = "a" * 40
        agg_nr = {"overall": "needs_review", "needs_review": ["rate_limiting"], "results": []}
        gen_reviewer = lambda *a, **k: "VERDICT: pass"
        with tempfile.TemporaryDirectory() as hd:
            _appr_t.write_record(hd, "seq-agg", approval="rate_limiting", approved_by="human@owner",
                                 scope="security rate_limiting", reason="человек одобрил integration-SHA",
                                 created_at="2026-07-29", binds_to=isha, expires_at="2026-12-31",
                                 risk="high", source="human")
            r_iii, _ = _aggregate_close_security(dict(agg_nr), Path(hd), None, "b" * 40, {}, gen_reviewer, True,
                                                 security_reviewer_proposer=None, strict_judge_qualified=False,
                                                 wid="seq-agg", child_root=hd)
            assert r_iii.get("overall") == "needs_review"


# ─── sandbox inheritance ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestSandboxInheritance:
    def test_sandbox_true_inherited(self):
        sig = {"task_type": "QUICK", "size": "large", "risk": "low",
               "affected_areas": ["catalog", "orders", "billing"]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            pkgs = atomic_planner.decompose(sig, wid="seqs", child_root=root)["work_packages"]
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                execute_sequence("рефактор в sandbox", sig, root, pkgs, _prop_for, feature="seqs",
                                 base=cur, sandbox=True, baseline_diff=False)
            rep0 = json.loads((root / "features" / "seqs" / "work-packages" / pkgs[0]["id"] / "report.json").read_text())
            assert (rep0.get("containment") or {}).get("sandbox") is True
            assert (rep0.get("containment") or {}).get("shell_mode") == "allowlist"


# ─── Package block stops sequence ──────────────────────────────────────────────

@pytest.mark.unit
class TestPackageBlockStopsSequence:
    def test_secret_boundary_blocks_package(self, three_area_sig):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cur = _mkrepo(td)
            wp = atomic_planner.decompose(three_area_sig, wid="seqb", child_root=root)
            pkgs = wp["work_packages"]

            def sig_for(pkg):
                return {"secret_boundary": True} if pkg["id"] == pkgs[1]["id"] else {}

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                seq2 = execute_sequence("рефактор с блоком", three_area_sig, root, pkgs, _prop_for,
                                        feature="seqb", base=cur, signals_for=sig_for,
                                        author=True, author_proposer=_author)
            ids_seen = [p["id"] for p in seq2["packages"]]
            assert seq2["stopped_at"] == pkgs[1]["id"]
            assert pkgs[0]["id"] in seq2["completed"]
            assert pkgs[2]["id"] not in ids_seen
            assert seq2["executed_all"] is False
