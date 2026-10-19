"""#542: opt-in `--parallel` РЕАЛЬНО достигает run_live_concurrent, а дефолт (single-path) неизменен.

Маршрутизация проверяется без запуска настоящих клонов/провайдера: тяжёлое исполнение подменяется
инъекцией `runner`/`run_fn`. Проверяем ровно шов проводки:
  - мультипакетный план -> вызов dispatch-runner (run_live_concurrent) с построенным WorkGraph;
  - атомарная задача -> None (вызыватель делает обычный прогон — дефолт не меняется);
  - CLI объявляет флаг `--parallel` и по умолчанию он ВЫКЛ.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp


@pytest.mark.unit
class TestBuildWorkGraph:
    def test_multi_package_builds_graph(self, monkeypatch):
        monkeypatch.setattr(
            dsp.atomic_planner, "decompose",
            lambda signals, wid=None, child_root=None, **kw: {
                "should_decompose": True,
                "work_packages": [
                    {"id": f"{wid}-pkg-1", "title": "часть 1", "depends_on": [], "write_scope": ["a/**"]},
                    {"id": f"{wid}-pkg-2", "title": "часть 2", "depends_on": [], "write_scope": ["b/**"]},
                ]})
        wg, task_map = dsp.build_work_graph({"task_text": "сделать X"}, "WG-1", ".")
        assert wg["kind"] == "WorkGraph"
        assert [p["id"] for p in wg["packages"]] == ["WG-1-pkg-1", "WG-1-pkg-2"]
        # каждый пакет несёт СВОЙ текст (общая задача + подзадача пакета)
        assert set(task_map) == {"WG-1-pkg-1", "WG-1-pkg-2"}
        assert "сделать X" in task_map["WG-1-pkg-1"]
        assert "WG-1-pkg-1" in task_map["WG-1-pkg-1"]

    def test_atomic_returns_none(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose",
                            lambda *a, **k: {"should_decompose": False, "work_packages": []})
        assert dsp.build_work_graph({"task_text": "t"}, "WG", ".") == (None, None)

    def test_single_package_is_not_parallelized(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [{"id": "only", "depends_on": [], "write_scope": ["a/**"]}]})
        assert dsp.build_work_graph({"task_text": "t"}, "WG", ".") == (None, None)


@pytest.mark.unit
class TestOptInReachesRunLiveConcurrent:
    def test_dispatch_calls_run_live_concurrent(self, monkeypatch):
        """Опт-ин достигает run_live_concurrent: инъектированный runner получает построенный WorkGraph."""
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "title": "t1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "title": "t2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        # база-SHA нужна run_parallel_live — не зовём git, стабим _base_sha
        monkeypatch.setattr(dsp.gitio, "resolve_base", lambda *a: {
            "resolved": True, "base_ref": "main", "base_sha": "f" * 40})
        captured = {}

        def fake_runner(wg, child_root, base_sha, task_map, signals, run_fn, **kw):
            captured.update(wg=wg, base_sha=base_sha, task_map=task_map, run_fn=run_fn, kw=kw)
            return {"proceed": True, "execution_concurrency": "concurrent",
                    "delivery": {"open_pr": True}, "integration_sha": "c" * 40}

        # run_fn НЕ вызывается (fake_runner его не дергает) — реальные клоны не создаются
        rec = dsp.run_parallel_live("сделать X", {"task_text": "сделать X"}, ".",
                                    feature="WG-9", provider="mock", runner=fake_runner,
                                    run_fn=lambda *a, **k: None)
        assert rec["parallel"] is True
        assert captured["base_sha"] == "f" * 40
        assert [p["id"] for p in captured["wg"]["packages"]] == ["p1", "p2"]
        assert set(captured["task_map"]) == {"p1", "p2"}
        # реальный дефолтный runner — это именно run_live_concurrent
        from ai_ops_kit.engine import parallel_live
        assert dsp.parallel_live.run_live_concurrent is parallel_live.run_live_concurrent

    def test_atomic_task_falls_back_to_none(self, monkeypatch):
        """Атомарная задача -> None: вызыватель уходит в обычный (single-path) прогон, дефолт цел."""
        monkeypatch.setattr(dsp.atomic_planner, "decompose",
                            lambda *a, **k: {"should_decompose": False, "work_packages": []})
        called = {"runner": False}

        def fake_runner(*a, **k):
            called["runner"] = True
            return {}

        rec = dsp.run_parallel_live("t", {"task_text": "t"}, ".", runner=fake_runner)
        assert rec is None
        assert called["runner"] is False

    def test_no_base_sha_refuses_without_touching_runner(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        monkeypatch.setattr(dsp.gitio, "resolve_base", lambda *a: {"resolved": False})
        called = {"runner": False}
        rec = dsp.run_parallel_live("t", {"task_text": "t"}, ".",
                                    runner=lambda *a, **k: called.__setitem__("runner", True))
        assert rec["proceed"] is False
        assert rec["stage"] == "preflight"
        assert called["runner"] is False


@pytest.mark.unit
class TestExitAndPrint:
    def test_exit_code_green_delivery(self):
        assert dsp.exit_code({"proceed": True, "delivery_requested": True,
                              "delivery": {"status": "opened", "sha_verified": True,
                                           "receipt": "features/W/outbox/receipt.yaml"}}) == 0

    def test_exit_code_not_ready(self):
        assert dsp.exit_code({"proceed": False, "stage": "fan-in"}) == 1

    def test_exit_code_blocked(self):
        assert dsp.exit_code({"proceed": False, "stage": "preflight"}) == 2

    def test_print_does_not_raise(self, capsys):
        dsp.print_parallel({"proceed": True, "id": "WG", "execution_concurrency": "concurrent",
                            "isolation": "per-package-clone", "integration_sha": "c" * 40,
                            "aggregate": {"conflicts": 0}, "delivery_plan": {"ready": True},
                            "package_results": {"p1": {"status": "pass", "sha": "a" * 40}}})
        assert "PARALLEL" in capsys.readouterr().out


@pytest.mark.unit
class TestCliDeclaresFlag:
    def test_parallel_flag_default_off(self):
        """CLI объявляет --parallel и по умолчанию он ВЫКЛ (дефолтный run — single-path)."""
        from ai_ops_kit.cli import ai_ops_cli
        ap = ai_ops_cli._build_cli_arg_parser()
        ns = ap.parse_args(["run", "задача"])
        assert getattr(ns, "parallel", False) is False
        ns2 = ap.parse_args(["run", "задача", "--parallel"])
        assert ns2.parallel is True


def test_smoke_module_imports():
    with tempfile.TemporaryDirectory():
        assert callable(dsp.run_parallel_live)
        assert callable(dsp.build_work_graph)


def _real_repo(tmp_path, monkeypatch):
    from ai_ops_kit.engine import parallel_live as live
    root = tmp_path / "child"
    root.mkdir()
    live._git(root, "init", "-q", "-b", "main")
    live._git(root, "config", "user.email", "test@example.test")
    live._git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text("features/\n.ai/\n")
    (root / "seed.txt").write_text("base\n")
    live._git(root, "add", ".")
    live._git(root, "commit", "-qm", "seed")
    live._git(root, "remote", "add", "origin", "https://github.com/example/child.git")
    base = live._git(root, "rev-parse", "HEAD").stdout.strip()
    wg = {"id": "WG", "packages": [
        {"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
        {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]}]}
    monkeypatch.setattr(dsp, "build_work_graph", lambda *a: (wg, {"aa": "A", "bb": "B"}))
    from ai_ops_kit.gates import evidence_collector
    monkeypatch.setattr(evidence_collector, "collect", lambda *a, **k: {
        "gate_evidence": {"implementation_verification": {"status": "pass"}}, "checks": {},
        "revision": live._git(a[1], "rev-parse", "HEAD").stdout.strip()})
    return root, base, wg


def _real_commit(task, signals, root, **options):
    from ai_ops_kit.engine import parallel_live as live
    pid = options["feature"]
    live._git(root, "checkout", "-q", "-B", f"ai-ops/{pid}")
    (root / f"{pid}.py").write_text(f"VALUE = '{pid}'\n")
    live._git(root, "add", f"{pid}.py")
    live._git(root, "commit", "-qm", pid)
    return {"ready_for_pr": True,
            "commit": {"sha": live._git(root, "rev-parse", "HEAD").stdout.strip()}}


@pytest.mark.unit
def test_selected_policy_and_real_integration_survive_until_canonical_receipt(tmp_path, monkeypatch):
    from ai_ops_kit.engine import parallel_live as live, execution_pipeline
    from ai_ops_kit.delivery import pr_open
    root, base, _ = _real_repo(tmp_path, monkeypatch)
    live._git(root, "branch", "release")
    (root / "main-only.txt").write_text("new main\n")
    live._git(root, "add", ".")
    live._git(root, "commit", "-qm", "advance main")
    (root / "seed.txt").write_text("dirty original, never copy\n")
    before = live._git(root, "status", "--porcelain").stdout
    original_sha = live._git(root, "rev-parse", "HEAD").stdout
    options_seen, external = [], []

    def run(task, signals, clone, **options):
        assert live._git(clone, "rev-parse", "HEAD").stdout.strip() == base
        assert not (clone / "main-only.txt").exists()
        assert (clone / "seed.txt").read_text() == "base\n"
        assert signals["work_package_id"] == options["feature"]
        options_seen.append(options)
        return _real_commit(task, signals, clone, **options)

    def open_pr(clone, branch, **kwargs):
        sha = live._git(clone, "rev-parse", "HEAD").stdout.strip()
        assert (Path(clone) / "aa.py").is_file() and (Path(clone) / "bb.py").is_file()
        outbox = root / "features/WG/delivery-outbox"
        assert len(list(outbox.glob("*.intent.yaml"))) == 1, "Intent must precede external call"
        assert (root / "features/WG/run-handoff.yaml").is_file()
        assert (root / "features/WG/run-report.json").is_file()
        assert kwargs["base"] == "release" and kwargs["delivery_id"] and branch == "ai-ops/WG"
        external.append((str(clone), sha))
        return {"status": "opened", "head_sha": sha, "number": 7,
                "url": "https://github.com/example/child/pull/7"}

    monkeypatch.setattr(execution_pipeline, "_reverify_against_current_target", lambda *a: {
        "stale": False, "verdict": "verified-equal"})
    monkeypatch.setattr(pr_open, "open_draft_pr", open_pr)
    rec = dsp.run_parallel_live("T", {"task_type": "QUICK"}, root, feature="WG",
        provider="openai", model="selected-model", base="release", max_steps=7, open_pr=True,
        author=False, review=True, sandbox=True, baseline_diff=True, install_deps=False, run_fn=run)
    assert dsp.exit_code(rec) == 0 and len(external) == 1
    assert len(options_seen) == 2
    for options in options_seen:
        assert {k: options[k] for k in ("provider_name", "model", "base", "max_steps", "author",
            "review", "sandbox", "baseline_diff", "install_deps", "open_pr", "verification_intent")} == {
            "provider_name": "openai", "model": "selected-model", "base": "release", "max_steps": 7,
            "author": False, "review": True, "sandbox": True, "baseline_diff": True,
            "install_deps": False, "open_pr": False, "verification_intent": "draft"}
    assert Path(external[0][0]).is_dir(), "ready integration source must survive return"
    assert rec["delivery"]["sha_verified"] is True
    assert len(list((root / "features/WG/delivery-outbox").glob("*.receipt.yaml"))) == 1
    assert live._git(root, "status", "--porcelain").stdout == before
    assert live._git(root, "rev-parse", "HEAD").stdout == original_sha
    assert (root / "seed.txt").read_text() == "dirty original, never copy\n"


@pytest.mark.unit
@pytest.mark.parametrize("signals,provider,base,reason", [
    ({}, "codex", "main", "provider unsupported"),
    ({}, None, "main", "provider"),
    ({}, "mock", "missing", "base-preflight"),
    ({"budget_contract": {"max_model_calls": 0}}, "mock", "main", "budget unsupported"),
    ({"execution_budget": {"max_cost": 1}}, "mock", "main", "budget unsupported"),
    ({"execution_budget": []}, "mock", "main", "budget unsupported"),
    ({"execution_budget": False}, "mock", "main", "budget unsupported"),
    ({"execution_budget": 0}, "mock", "main", "budget unsupported"),
    ({"dependency_addition": True}, "mock", "main", "approval-preflight"),
    ({"destructive": True}, "mock", "main", "approval-preflight"),
])
def test_parallel_policy_refusal_precedes_clones_and_external_calls(
        tmp_path, monkeypatch, signals, provider, base, reason):
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    calls = []
    rec = dsp.run_parallel_live("T", signals, root, feature="WG", provider=provider, base=base,
        open_pr=True, runner=lambda *a, **k: calls.append("clone"),
        run_fn=lambda *a, **k: calls.append("model"))
    assert reason in rec["reason"] and dsp.exit_code(rec) == 2
    assert calls == [] and not (root / ".git/ai-ops-parallel").exists()


@pytest.mark.unit
def test_requested_delivery_cannot_use_green_boolean_without_receipt():
    rec = {"proceed": True, "delivery_requested": True,
           "aggregate": {"all_pass": True, "tested_revision": "a" * 40}, "integration_sha": "a" * 40,
           "delivery": {"open_pr": True}}
    assert dsp.exit_code(rec) == 1
    rec["delivery"].update(status="opened", sha_verified=False, receipt="receipt.yaml")
    assert dsp.exit_code(rec) == 1


@pytest.mark.unit
def test_failed_fan_in_never_reaches_external_delivery(tmp_path, monkeypatch):
    from ai_ops_kit.engine import parallel_live as live, execution_pipeline
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(execution_pipeline, "_deliver_pr", lambda *a, **k: calls.append("PR"))
    # The two actual commits deliberately conflict; do not manufacture conflict from a mock flag.
    def run(task, signals, clone, **options):
        pid = options["feature"]
        live._git(clone, "checkout", "-q", "-B", f"ai-ops/{pid}")
        (clone / "features").mkdir(exist_ok=True)
        (clone / "features/conflict.txt").write_text(pid)
        live._git(clone, "add", "-f", "features/conflict.txt")
        live._git(clone, "commit", "-qm", pid)
        return {"ready_for_pr": True,
                "commit": {"sha": live._git(clone, "rev-parse", "HEAD").stdout.strip()}}
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True, run_fn=run)
    assert rec["aggregate"]["conflicts"] > 0 and dsp.exit_code(rec) == 1
    assert calls == [] and not list((root / ".git/ai-ops-parallel").glob("run-*"))


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["intent", "source", "policy"])
def test_delivery_barrier_failure_retains_source_and_calls_no_external_api(tmp_path, monkeypatch, failure):
    from ai_ops_kit.engine import parallel_live as live, execution_pipeline
    from ai_ops_kit.shared import lifecycle_store
    from ai_ops_kit.governance import enforcement
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(execution_pipeline, "_deliver_pr", lambda *a, **k: calls.append("PR"))
    monkeypatch.setattr(execution_pipeline, "_reverify_against_current_target", lambda *a: {
        "stale": False, "verdict": "verified-equal"})
    original_write = lifecycle_store.durable_write

    def write(path, data, **kwargs):
        if failure == "intent" and str(path).endswith(".intent.yaml"):
            return {"ok": False, "error": "controlled durable-write failure"}
        return original_write(path, data, **kwargs)
    monkeypatch.setattr(lifecycle_store, "durable_write", write)
    if failure == "policy":
        monkeypatch.setattr(enforcement, "gate_delivery", lambda *a, **k: {
            "blocked": True, "reason": "controlled policy refusal"})

    def runner(*args, **kwargs):
        rec = live.run_live_concurrent(*args, **kwargs)
        if failure == "source":
            (Path(rec["delivery_plan"]["integration_clone"]) / "aa.py").write_text("tampered\n")
        return rec
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True,
                                run_fn=_real_commit, runner=runner)
    assert dsp.exit_code(rec) != 0 and calls == []
    assert Path(rec["integration_source"]["integration_clone"]).is_dir()
    assert not list((root / "features/WG/delivery-outbox").glob("*.receipt.yaml"))


@pytest.mark.unit
def test_ready_without_pr_is_persisted_and_not_reported_as_opened(tmp_path, monkeypatch):
    import json
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", run_fn=_real_commit)
    saved = json.loads((root / "features/WG/parallel-report.json").read_text())
    assert dsp.exit_code(rec) == 0 and saved["delivery"]["status"] == "not-requested"
    source = Path(saved["integration_source"]["integration_clone"])
    assert source.is_dir() and (source / "aa.py").is_file() and (source / "bb.py").is_file()


@pytest.mark.unit
def test_parallel_report_failure_cannot_hide_behind_verified_receipt(tmp_path, monkeypatch):
    from ai_ops_kit.engine import execution_pipeline
    from ai_ops_kit.shared import lifecycle_store
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    original = lifecycle_store.durable_write_json
    calls = []

    def write(path, data, **kwargs):
        return ({"ok": False, "error": "controlled final report failure"}
                if Path(path).name == "parallel-report.json" else original(path, data, **kwargs))
    def deliver(*args, **kwargs):
        calls.append(args[5])
        return {"status": "opened", "pr": {"head_sha": args[5], "number": 7,
            "url": "https://github.com/example/child/pull/7"}}
    monkeypatch.setattr(lifecycle_store, "durable_write_json", write)
    monkeypatch.setattr(execution_pipeline, "_reverify_against_current_target", lambda *a: {
        "stale": False, "verdict": "verified-equal"})
    monkeypatch.setattr(execution_pipeline, "_deliver_pr", deliver)
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True,
                                run_fn=_real_commit)
    assert calls == [rec["integration_sha"]] and rec["delivery"]["sha_verified"] is True
    assert (root / rec["delivery"]["receipt"]).is_file()
    assert rec["stage"] == "lifecycle" and dsp.exit_code(rec) == 2


@pytest.mark.unit
@pytest.mark.parametrize("available", [True, False])
def test_unknown_delivery_is_reconciled_before_new_package_calls(tmp_path, monkeypatch, available):
    import yaml
    from ai_ops_kit.engine import parallel_live as live, execution_pipeline
    from ai_ops_kit.delivery import pr_open
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    phase, runs, posts = [1], [], []

    def run(task, signals, clone, **options):
        if phase[0] == 2:
            receipts = list((root / "features/WG/delivery-outbox").glob("*.receipt.yaml"))
            assert receipts and yaml.safe_load(receipts[0].read_text())["reconciled"] is True
        runs.append(options["feature"])
        rep = _real_commit(task, signals, clone, **options)
        (clone / f"{options['feature']}.py").write_text(f"PHASE = {phase[0]}\n")
        live._git(clone, "add", ".")
        live._git(clone, "commit", "-qm", f"phase {phase[0]}")
        rep["commit"]["sha"] = live._git(clone, "rev-parse", "HEAD").stdout.strip()
        return rep

    def post(clone, branch, **kwargs):
        posts.append(branch)
        return ({"status": "outcome_unknown"} if phase[0] == 1 else {
            "status": "updated", "head_sha": live._git(clone, "rev-parse", "HEAD").stdout.strip(),
            "number": 7, "url": "https://github.com/example/child/pull/7"})
    monkeypatch.setattr(execution_pipeline, "_reverify_against_current_target", lambda *a: {
        "stale": False, "verdict": "verified-equal"})
    monkeypatch.setattr(pr_open, "open_draft_pr", post)
    first = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True, run_fn=run)
    assert first["delivery"]["status"] == "outcome_unknown" and dsp.exit_code(first) == 1
    assert len(runs) == 2 and len(posts) == 1
    old_sha = first["integration_sha"]
    monkeypatch.setattr(pr_open, "reconcile_delivery", lambda *a: {
        "status": "found" if available else "unavailable", "repository": "example/child",
        "head_sha": old_sha, "base_ref": "main", "url": "https://github.com/example/child/pull/7",
        "number": 7, "checks": {"status": "success", "total": 1, "failed": 0}})
    phase[0] = 2
    second = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True, run_fn=run)
    if available:
        assert dsp.exit_code(second) == 0 and second["integration_sha"] != old_sha
        assert second["reconciliation"][0]["status"] == "reconciled"
        assert len(runs) == 4 and len(posts) == 2
    else:
        assert dsp.exit_code(second) == 2 and len(runs) == 2 and len(posts) == 1
    assert Path(first["integration_source"]["integration_clone"]).is_dir()

@pytest.mark.parametrize("outcome", ["pass", "failed-package", "exception"])
def test_package_usage_and_safe_evidence_survive_cleanup(tmp_path, monkeypatch, outcome):
    import json
    from ai_ops_kit.engine import parallel_live as live
    from ai_ops_kit.shared import usage_ledger as ledger
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    before = live._git(root, "status", "--porcelain").stdout
    paths = []
    def run(task, signals, clone, **options):
        paths.append(clone)
        record = {"run_id": options["feature"], "role": "implementation", "usage_status": "measured",
                  "input_tokens": 9, "output_tokens": 3, "cost": None, "cost_status": "unavailable",
                  "api_key": "do-not-copy", "prompt": "do-not-copy"}
        ledger.append(clone, options["feature"], [record, record])
        (clone / "secret-config.txt").write_text("do-not-copy")
        if outcome == "exception":
            raise RuntimeError("do-not-copy")
        result = _real_commit(task, signals, clone, **options)
        result["ready_for_pr"] = outcome == "pass"
        return result
    rec = live.run_live_concurrent(wg, root, base, {"aa": "A", "bb": "B"}, {}, run)
    artifact = rec["package_artifacts"]
    assert artifact["status"] == "preserved" and artifact["new_product_calls"] == 4
    receipt = json.loads(Path(artifact["receipt"]).read_text())
    assert len(receipt["packages"]) == 2 and receipt["base_sha"] == base
    assert all(item["source_head"] and item["usage_streams"] for item in receipt["packages"])
    assert all(not path.exists() for path in paths), "cleanup follows durable retention"
    assert len(ledger.load_product(root)) == 4
    assert len(ledger.load_task(root, "aa")) == len(ledger.load_task(root, "bb")) == 2
    assert all(row["cost"] is None for row in ledger.load_product(root))
    assert "do-not-copy" not in Path(artifact["receipt"]).read_text()
    assert all("prompt" not in row and "api_key" not in row for row in ledger.load_product(root))
    assert live._git(root, "status", "--porcelain").stdout == before
    if outcome != "pass":
        assert rec["delivery_plan"]["ready"] is False


@pytest.mark.parametrize("failure", ["corrupt", "receipt"])
def test_artifact_failure_keeps_last_source_and_blocks_delivery(tmp_path, monkeypatch, failure):
    from ai_ops_kit.engine import parallel_live as live, execution_pipeline
    from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    paths, external = [], []
    original = lifecycle_store.durable_write_json
    def durable(path, *args, **kwargs):
        if failure == "receipt" and Path(path).name == "package-receipt.json":
            return {"ok": False, "error": "controlled fault"}
        return original(path, *args, **kwargs)
    monkeypatch.setattr(lifecycle_store, "durable_write_json", durable)
    monkeypatch.setattr(execution_pipeline, "_deliver_pr", lambda *a, **k: external.append("PR"))
    def run(task, signals, clone, **options):
        paths.append(clone)
        ledger.append(clone, options["feature"], [{"role": "implementation", "usage_status": "measured",
            "input_tokens": 2, "output_tokens": 1, "cost": None, "cost_status": "unavailable"}])
        if failure == "corrupt":
            (clone / ".ai/usage/product-ledger.jsonl").write_text("corrupt\n")
        return _real_commit(task, signals, clone, **options)
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", open_pr=True, run_fn=run)
    assert rec["package_artifacts"]["status"] == "blocked" and dsp.exit_code(rec) != 0
    assert rec["delivery_plan"]["ready"] is False and external == []
    assert len(paths) == 2 and all((path / ".ai/usage/product-ledger.jsonl").exists() for path in paths)
    assert all(path.exists() for path in paths), "last owned source must survive failed durability"


def test_retained_sources_retry_uses_durable_baseline_without_double_count(tmp_path, monkeypatch):
    from ai_ops_kit.engine import parallel_live as live
    from ai_ops_kit.shared import usage_ledger as ledger, lifecycle_store
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    row = {"role": "implementation", "usage_status": "measured", "input_tokens": 2,
           "output_tokens": 1, "cost": None, "cost_status": "unavailable"}
    # This history is actually tracked and therefore inherited by git clone.
    ledger.append(root, "old", [row])
    live._git(root, "add", "-f", "features/old/usage-ledger.jsonl")
    live._git(root, "commit", "-qm", "tracked history")
    base = live._git(root, "rev-parse", "HEAD").stdout.strip()
    original = lifecycle_store.durable_write_json
    paths = {}
    def fault(path, *args, **kwargs):
        return {"ok": False} if Path(path).name == "package-receipt.json" else original(path, *args, **kwargs)
    def run(task, signals, clone, **options):
        paths[options["feature"]] = {"path": str(clone)}
        ledger.append(clone, options["feature"], [row, row])
        return _real_commit(task, signals, clone, **options)
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_store, "durable_write_json", fault)
        rec = live.run_live_concurrent(wg, root, base, {"aa": "A", "bb": "B"}, {}, run)
    assert rec["package_artifacts"]["status"] == "blocked"
    assert len(ledger.load_task(root, "old")) == 1, "clone history is not new spend"
    assert len(ledger.load_product(root)) == 5, "one local history + four genuine new calls"
    run_dir = Path(rec["package_artifacts"]["retained_source"])
    proof = live._preserve_package_artifacts(root, base, paths, run_dir, rec["package_results"])
    assert proof["status"] == "preserved" and proof["new_product_calls"] == 0
    assert Path(proof["receipt"]).is_file() and len(ledger.load_product(root)) == 5
    assert len(ledger.load_task(root, "old")) == 1


@pytest.mark.parametrize("failure", ["missing-git", "missing-baseline", "invalid-latency"])
def test_usage_source_validation_never_deletes_last_copy(tmp_path, monkeypatch, failure):
    import hashlib
    import shutil
    from ai_ops_kit.engine import parallel_live as live
    from ai_ops_kit.shared import usage_ledger as ledger
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    sources = []
    def run(task, signals, clone, **options):
        sources.append(clone)
        row = {"role": "implementation", "usage_status": "measured", "input_tokens": 2,
               "output_tokens": 1, "cost": None, "cost_status": "unavailable"}
        if failure == "invalid-latency":
            row["latency"] = {"api_key": "do-not-copy"}
        ledger.append(clone, options["feature"], [row])
        result = _real_commit(task, signals, clone, **options)
        if failure == "missing-git":
            shutil.rmtree(clone / ".git")
        elif failure == "missing-baseline":
            (clone.parent / "_package-baselines" / (hashlib.sha256(options["feature"].encode()).hexdigest() + ".json")).unlink()
        return result
    rec = live.run_live_concurrent(wg, root, base, {"aa": "A", "bb": "B"}, {}, run)
    assert rec["package_artifacts"]["status"] == "blocked" and not rec["delivery_plan"]["ready"]
    assert sources and all((path / ".ai/usage/product-ledger.jsonl").exists() for path in sources)
    assert ledger.load_product(root) == [], "invalid metadata cannot copy secrets or lose source calls"


@pytest.mark.parametrize("stage", ["rmtree", "listing"])
def test_cleanup_io_failure_reports_retained_clones(tmp_path, monkeypatch, stage):
    import shutil
    from ai_ops_kit.engine import parallel_live as live
    root, base, wg = _real_repo(tmp_path, monkeypatch)
    original = shutil.rmtree
    def refuse(path, *args, **kwargs):
        if Path(path).name == "aa":
            raise OSError("controlled cleanup failure")
        return original(path, *args, **kwargs)
    original_list = Path.iterdir
    def refuse_listing(path):
        if path.name.startswith("run-"):
            raise OSError("controlled listing failure")
        return original_list(path)
    if stage == "rmtree":
        monkeypatch.setattr(shutil, "rmtree", refuse)
    else:
        monkeypatch.setattr(Path, "iterdir", refuse_listing)
    rec = live.run_live_concurrent(wg, root, base, {"aa": "A", "bb": "B"}, {}, _real_commit)
    assert rec["package_artifacts"]["status"] == "preserved"
    assert rec["cleanup"]["status"] == "partial" and rec["cleanup"]["retained_paths"]
    assert all(Path(path).exists() for path in rec["cleanup"]["retained_paths"])


@pytest.mark.parametrize("cap", [1, 2])
def test_parallel_packages_share_exact_counter_and_real_commit_proof(tmp_path, monkeypatch, cap):
    from ai_ops_kit.engine import parallel_live as live
    from ai_ops_kit.shared.budget import Budget
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    shared = Budget(max_model_calls=cap)
    before = live._git(root, "rev-parse", "HEAD").stdout
    executed, objects = [], []
    def run(task, signals, clone, **options):
        objects.append(options["budget"])
        options["budget"].charge_call()
        executed.append(options["feature"])
        return _real_commit(task, signals, clone, **options)
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", budget=shared, run_fn=run)
    assert len(executed) == shared.model_calls == cap
    assert len(objects) == 2 and all(obj is shared for obj in objects)
    assert live._git(root, "rev-parse", "HEAD").stdout == before
    assert sum(bool(p.get("sha")) for p in rec["package_results"].values()) == cap
    assert rec["delivery_plan"]["ready"] is (cap == 2)


@pytest.mark.parametrize("limits", [{"max_model_calls": 0}, {"max_cost": 1},
                                    {"max_duration": "1m"}, {"max_physical_calls": 2}])
def test_budget_refusal_precedes_parallel_clones_and_models(tmp_path, monkeypatch, limits):
    from ai_ops_kit.shared.budget import Budget
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    calls = []
    budget = limits if "max_physical_calls" in limits else Budget.from_dict(limits)
    rec = dsp.run_parallel_live("T", {}, root, feature="WG", provider="mock", budget=budget,
        runner=lambda *a, **kw: calls.append("clone"), run_fn=lambda *a, **kw: calls.append("model"))
    assert dsp.exit_code(rec) == 2 and calls == []
    assert not (root / ".git/ai-ops-parallel").exists()


def _saved_auto(root):
    import yaml
    from ai_ops_kit.shared import gitio
    from ai_ops_kit.lifecycle import workitem
    from ai_ops_kit.engine import run_plan
    root.mkdir(exist_ok=True)
    gitio.run(["init", "-q", "-b", "main", str(root)])
    gitio.git(root, "config", "user.email", "test@example.test")
    gitio.git(root, "config", "user.name", "Test")
    signals = {"task_type": "typo", "risk": "low", "size": "small", "execution_budget": {"max_model_calls": 30}}
    cfg = {"session_economy": {"auto_parallel_independent_roots": True}}
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg))
    wg = {"schema_version": 1, "kind": "WorkGraph", "id": "WG-001", "feature": "work",
          "execution_mode": "parallel", "packages": [{"id": x, "write_scope": [f"{x}.txt"], "depends_on": []}
                                                        for x in ("aa", "bb")],
          "integration_order": ["aa", "bb"], "aggregate_verification": ["implementation_verification"]}
    (root / "work-graph.yaml").write_text(yaml.safe_dump(wg))
    for pid in ("work", "aa", "bb"):
        workitem.start(root / "features", pid, f"write {pid}", signals=signals)
        d = root / "features" / pid
        (d / "run-plan.yaml").write_text(yaml.safe_dump(run_plan.build_plan({**signals, "task_text": f"write {pid}"}, pid)))
        (d / "run-settings.yaml").write_text(yaml.safe_dump({"kind": "run-settings", "workitem_id": pid,
                                                           "signals": signals, "policy": {}}))
    gitio.git(root, "add", ".")
    gitio.git(root, "commit", "-qm", "base")
    return signals, wg


@pytest.mark.parametrize("mutation", ["deps", "scope", "feature", "unknown", "ceiling", "budget", "approval", "policy", "aggregate", "legacy-budget", "alias", "config", "mode", "tests-passed", "types", "order", "null-scope"])
def test_saved_auto_refuses_before_dispatch(tmp_path, mutation):
    import yaml
    from ai_ops_kit.cli import ai_ops_cli_commands as cmd
    signals, wg = _saved_auto(tmp_path)
    if mutation == "deps":
        wg["packages"][1]["depends_on"] = ["aa"]
    elif mutation == "scope":
        wg["packages"][1]["write_scope"] = ["../escape"]
    elif mutation == "alias":
        (tmp_path / "aa.txt").symlink_to("bb.txt")
    elif mutation == "types":
        wg["schema_version"] = True
    elif mutation == "order":
        wg["integration_order"] = ["aa"]
    elif mutation == "null-scope":
        wg["packages"][0]["write_scope"] = [None]
    elif mutation == "feature":
        wg["feature"] = "other"
    elif mutation == "unknown":
        wg["packages"][0]["task"] = "invented"
    elif mutation == "ceiling":
        (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump({"session_economy": {
            "auto_parallel_independent_roots": True, "max_subsessions_per_session": 4}}))
    elif mutation == "budget":
        signals["execution_budget"] = {"max_model_calls": 999}
    elif mutation == "config":
        (tmp_path / ".ai-ops.yaml").write_text((tmp_path / ".ai-ops.yaml").read_text() + "# uncommitted config\n")
    elif mutation == "mode":
        (tmp_path / ".ai-ops.yaml").chmod(0o755)
    elif mutation == "tests-passed":
        wg["aggregate_verification"] = ["tests_passed"]
    elif mutation == "aggregate":
        wg["aggregate_verification"] = ["unknown-gate"]
    elif mutation in ("policy", "legacy-budget"):
        p = tmp_path / "features/aa/run-settings.yaml"
        saved = yaml.safe_load(p.read_text())
        saved["policy"]["sandbox"] = mutation == "policy"
        if mutation == "legacy-budget":
            saved["signals"]["budget_contract"] = {"max_cost": 1}
        p.write_text(yaml.safe_dump(saved))
    else:
        p = tmp_path / "features/aa/workitem.yaml"
        wi = yaml.safe_load(p.read_text())
        wi["workflow"] = "CRITICAL"
        p.write_text(yaml.safe_dump(wi))
    (tmp_path / "work-graph.yaml").write_text(yaml.safe_dump(wg))
    with pytest.raises(ValueError):
        cmd._automatic_roots(tmp_path, "work", signals, None)
    assert not (tmp_path / ".git/ai-ops-parallel").exists()


def test_ordinary_do_runs_real_isolated_packages_and_exact_fan_in(tmp_path, monkeypatch):
    """Only the model text transport/external PR acknowledgement are controlled fixtures."""
    import json
    import threading
    import yaml
    from ai_ops_kit.cli import ai_ops_cli
    from ai_ops_kit.providers import orchestrator
    from ai_ops_kit.engine import execution_pipeline, parallel_live
    from ai_ops_kit.delivery import pr_open
    from ai_ops_kit.shared import gitio
    from ai_ops_kit.lifecycle import active_work
    signals, _ = _saved_auto(tmp_path)
    (tmp_path / ".gitignore").write_text("features/\n.ai/\n")
    gitio.git(tmp_path, "rm", "-r", "--cached", "-q", "features")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.1'\n")
    cfg = yaml.safe_load((tmp_path / ".ai-ops.yaml").read_text())
    log = tmp_path.parent / (tmp_path.name + "-checks.log")
    (tmp_path / "check.py").write_text("from pathlib import Path\n"
        "files=[p for p in (Path('aa.txt'),Path('bb.txt')) if p.exists()]\n"
        "assert files and all(p.read_text()=='verified\\n' for p in files)\n"
        f"with open({str(log)!r},'a') as f: f.write(str(Path.cwd())+'|'+','.join(p.name for p in files)+'\\n')\n")
    cfg["verification"] = {"commands": {"test": "python3 check.py"}}
    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg))
    gitio.git(tmp_path, "add", ".")
    gitio.git(tmp_path, "commit", "-qm", "fixture verification")
    gitio.git(tmp_path, "remote", "add", "origin", "https://github.com/example/child.git")
    original = gitio.git(tmp_path, "rev-parse", "HEAD")[1]
    frozen = {str(p): p.read_bytes() for p in tmp_path.rglob("*.yaml") if ".git" not in p.parts}
    barrier, lock, active, maximum, seen = threading.Barrier(2), threading.Lock(), set(), [0], []

    def transport(prompt):
        pid = next((x for x in ("aa", "bb") if f"write {x}" in prompt), None)
        assert pid is not None, prompt[:200]
        context = prompt.split("=== ЗАДАЧА И ЖУРНАЛ УЖЕ ВЫПОЛНЕННЫХ ШАГОВ ===\n", 1)[-1]
        if f"{pid}.txt" not in context:
            with lock:
                active.add(pid)
                maximum[0] = max(maximum[0], len(active))
                seen.append(pid)
            barrier.wait(timeout=30)
            with lock:
                active.remove(pid)
            return json.dumps({"op": "write", "path": f"{pid}.txt", "content": "verified\n"})
        return json.dumps({"done": True, "summary": "fixture rename", "behavior_unchanged": "controlled text-only fixture"})

    monkeypatch.setattr(orchestrator, "make_provider", lambda *a, **k: transport)
    monkeypatch.setattr(execution_pipeline, "_reverify_against_current_target", lambda *a: {
        "stale": False, "verdict": "controlled-external-target"})
    monkeypatch.setattr(pr_open, "open_draft_pr", lambda root, branch, **k: {
        "status": "opened", "head_sha": gitio.git(root, "rev-parse", "HEAD")[1], "number": 7,
        "url": "https://github.com/example/child/pull/7"})
    rc = ai_ops_cli.main(["do", "write work", str(tmp_path), "--feature", "work",
                          "--provider", "mock", "--signals", json.dumps(signals)])
    rec = json.loads((tmp_path / "features/work/parallel-report.json").read_text())
    assert rc == 0, rec
    assert maximum == [2] and sorted(seen) == ["aa", "bb"]
    assert {row["pkg"] for row in rec["trace"]} == {"aa", "bb"}
    assert all(row["runner_started_at"] and row["runner_finished_at"]
               and row["queue_seconds"] >= 0 and row["execution_seconds"] >= 0 for row in rec["trace"])
    assert rec["aggregate"]["tested_revision"] == rec["integration_sha"] and rec["aggregate"]["tree_clean"]
    integration = Path(rec["integration_source"]["integration_clone"])
    assert all((integration / f"{p}.txt").read_text() == "verified\n" for p in ("aa", "bb"))
    assert gitio.git(integration, "rev-parse", "HEAD")[1] != original
    assert any("aa.txt,bb.txt" in line for line in log.read_text().splitlines())
    assert rec["budget"]["model_calls"] == 4
    receipt = json.loads(Path(rec["package_artifacts"]["receipt"]).read_text())
    assert {p["package_id"] for p in receipt["packages"]} == {"aa", "bb"}
    assert all(p["package_sha"] and p["gate_report"]["all_pass"] for p in receipt["packages"])
    assert all(not Path(p["clone"]).exists() for p in rec["package_results"].values())
    entry = active_work.load(active_work.shared_registry_path(tmp_path))["active"][0]
    assert entry["status"] == "done" and entry["auto_admission"]["base_sha"] == original
    assert all(Path(p).read_bytes() == raw for p, raw in frozen.items())
    assert gitio.git(tmp_path, "rev-parse", "HEAD")[1] == original


@pytest.mark.parametrize("reason", ["claim", "stale", "approval", "budget", "input"])
def test_saved_automatic_preflight_launches_no_forbidden_effects(tmp_path, monkeypatch, reason):
    from ai_ops_kit.cli import ai_ops_cli_commands as cmd
    from ai_ops_kit.lifecycle import active_work
    from ai_ops_kit.shared import gitio
    signals, _ = _saved_auto(tmp_path)
    auto = cmd._automatic_roots(tmp_path, "work", signals, None)
    sig = dict(signals, _auto_package_signals=auto.pop("package_signals"))
    if reason == "claim":
        import subprocess
        import sys
        path = active_work.shared_registry_path(tmp_path)
        proc = subprocess.run([sys.executable, "-m", "ai_ops_kit.lifecycle.active_work", "register", str(path),
            "work", "--branch", "ai-ops/work", "--areas", "aa.txt", "--session", "other", "--repo", str(tmp_path)],
            capture_output=True, text=True)
        assert proc.returncode == 0 and active_work.holder_is_gone(active_work.load(path)["active"][0], active_work._machine())
    elif reason == "stale":
        gitio.git(tmp_path, "commit", "--allow-empty", "-qm", "new base")
    elif reason == "input":
        (tmp_path / "features/aa/workitem.yaml").write_text("changed after admission")
    elif reason == "approval":
        sig["_auto_package_signals"]["aa"]["secret_boundary"] = True
    else:
        for _ in range(30):
            auto["budget"].charge_call()
    rec = dsp.run_parallel_live("write work", sig, tmp_path, feature="work", provider="mock",
                                runner=lambda *a, **k: pytest.fail("clone/model runner was reached"), **auto)
    assert rec["stage"] == "preflight" and rec["proceed"] is False
    assert not (tmp_path / ".git/ai-ops-parallel").exists()


def test_explicit_sequential_never_enters_automatic_admission(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from ai_ops_kit.cli import ai_ops_cli_commands as cmd
    monkeypatch.setattr(cmd, "_automatic_roots", lambda *a, **k: pytest.fail("auto admission reached"))
    assert cmd._dispatch_parallel("T", {}, tmp_path, SimpleNamespace(parallel=False, sequential=True),
                                  {}, "do", "mock") is None


def test_actual_cli_task_drift_refuses_before_runner(tmp_path, monkeypatch):
    import json
    from ai_ops_kit.cli import ai_ops_cli
    signals, _ = _saved_auto(tmp_path)
    monkeypatch.setattr(dsp.parallel_live, "run_live_concurrent", lambda *a, **k: pytest.fail("runner reached"))
    assert ai_ops_cli.main(["do", "DIFFERENT REQUESTED TASK", str(tmp_path), "--feature", "work",
                           "--provider", "mock", "--signals", json.dumps(signals)]) == 2
    assert not (tmp_path / ".git/ai-ops-parallel").exists()


@pytest.mark.parametrize('mode', ['missing', 'not-executable'])
def test_missing_local_cli_blocks_before_parallel_dispatch(tmp_path, monkeypatch, mode):
    from ai_ops_kit.providers import orchestrator_providers as providers
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'fixture-claude'
    if mode == 'not-executable':
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o644)
        assert binary.is_file()
    else:
        assert not binary.exists()
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    assert providers.claude_binary() is None
    dispatch_marker = tmp_path / 'dispatch-started'
    calls = []

    def dispatch(*args, **kwargs):
        dispatch_marker.write_text('actual dispatch reached\n')
        return {'proceed': False}

    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider='claude-cli',
                               runner=dispatch, run_fn=lambda *a, **k: calls.append('model'))
    assert not dispatch_marker.exists()
    assert rec['stage'] == 'preflight' and 'provider unavailable' in rec['reason']
    assert dsp.exit_code(rec) == 2 and calls == []
    assert not (root / '.git/ai-ops-parallel').exists()


def test_executable_local_cli_reaches_real_isolated_execution_without_native_call(tmp_path, monkeypatch):
    from ai_ops_kit.providers import orchestrator_providers as providers
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'fixture-claude'
    native_marker = tmp_path / 'native-was-called'
    binary.write_text(f'#!/bin/sh\nprintf called > "{native_marker}"\nexit 77\n')
    binary.chmod(0o755)
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    assert providers.claude_binary() == str(binary)
    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider='claude-cli',
                               run_fn=_real_commit)
    assert rec['integration_sha'] and rec['aggregate']['all_pass']
    assert set(rec['package_results']) == {'aa', 'bb'}
    assert all(row['sha'] for row in rec['package_results'].values())
    assert not native_marker.exists()


def test_missing_cli_refuses_before_durable_admission_validation(tmp_path, monkeypatch):
    from ai_ops_kit.lifecycle import active_work
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'absent-claude'
    assert not binary.exists()
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    validation_calls = []

    def validate(*args, **kwargs):
        validation_calls.append('admission')
        raise active_work.ActiveWorkCorrupt('fixture: later admission reached')

    monkeypatch.setattr(active_work, 'validate_admission', validate)
    rec = dsp.run_parallel_live('T', {}, root, feature='WG', provider='claude-cli',
                               admission={'identity': 'fixture'}, run_fn=lambda *a, **k: None)
    assert validation_calls == []
    assert rec['stage'] == 'preflight' and 'provider unavailable' in rec['reason']


def test_retry_after_local_cli_restore_starts_each_package_once(tmp_path, monkeypatch):
    root, _, _ = _real_repo(tmp_path, monkeypatch)
    binary = tmp_path / 'restored-claude'
    monkeypatch.setenv('AI_OPS_CLAUDE_BIN', str(binary))
    starts = []

    def run(*args, **kwargs):
        starts.append(kwargs['feature'])
        return _real_commit(*args, **kwargs)

    blocked = dsp.run_parallel_live('T', {}, root, feature='WG', provider='claude-cli', run_fn=run)
    assert blocked['stage'] == 'preflight' and 'provider unavailable' in blocked['reason']
    assert starts == [] and not (root / '.git/ai-ops-parallel').exists()
    native_marker = tmp_path / 'native-called'
    binary.write_text(f'#!/bin/sh\nprintf called > "{native_marker}"\nexit 77\n')
    binary.chmod(0o755)
    assert binary.is_file()
    resumed = dsp.run_parallel_live('T', {}, root, feature='WG', provider='claude-cli', run_fn=run)
    assert resumed['aggregate']['all_pass'] and resumed['integration_sha']
    assert sorted(starts) == ['aa', 'bb']
    assert not native_marker.exists()
