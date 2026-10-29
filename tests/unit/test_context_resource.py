"""#1403: настоящие файлы/payload, честная разметка и запрет исполнения до writer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from ai_ops_kit.context import context_compiler as compiler, context_resource as resource
from ai_ops_kit.engine.run_plan import build_plan
from ai_ops_kit.gates import preflight

pytestmark = pytest.mark.unit
SIGNALS = {"task_text": "read needed", "task_type": "QUICK", "size": "small", "risk": "low"}


def config(root, **policy):
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump({"context": policy}), encoding="utf-8")


def payload(root, **kwargs):
    return compiler.build_payload(SIGNALS, root, build_plan=build_plan, **kwargs)


def test_required_real_file_is_fed_whole_with_hash(tmp_path):
    text = "НУЖНОЕ " * 2000
    (tmp_path / "needed.md").write_text(text)
    config(tmp_path, required=["needed.md"])
    result = payload(tmp_path)
    item = next(i for i in result["included_items"] if i["source"] == "needed.md")
    assert text in result["text"] and item["truncated"] is False
    assert item["hash"] == hashlib.sha256(text.encode()).hexdigest()[:12]
    assert result["resource_check"]["ok"]
    assert result["metrics"]["time_to_context_ms"] >= 0


def test_forbidden_selected_spec_exists_but_is_never_read(tmp_path, monkeypatch):
    feature = tmp_path / "features/demo"
    feature.mkdir(parents=True)
    forbidden = feature / "requirements.md"
    forbidden.write_text("DO_NOT_FEED_1403")
    plan = build_plan(SIGNALS, workitem_id="demo")
    baseline = compiler.compile_bundle(SIGNALS, tmp_path, plan=plan)
    assert "features/demo/requirements.md" in baseline["included"]["specifications"]
    assert forbidden.is_file() and "DO_NOT_FEED_1403" in forbidden.read_text()
    config(tmp_path, forbidden=["features/demo/**"])
    read = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path != forbidden, "forbidden source was read"
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = compiler.build_payload(SIGNALS, tmp_path, plan=plan, bundle=baseline)
    assert "DO_NOT_FEED_1403" not in result["text"]
    assert not compiler.compile_bundle(SIGNALS, tmp_path, plan=plan)["included"]["specifications"]
    assert result["excluded_for_policy"][0]["source"] == "features/demo/requirements.md"


def test_forbidden_symlink_alias_is_not_loaded(tmp_path):
    (tmp_path / "secret.md").write_text("PRIVATE_MARKER")
    (tmp_path / "alias.md").symlink_to("secret.md")
    config(tmp_path, optional=["alias.md"], forbidden=["secret.md"])
    assert "PRIVATE_MARKER" not in payload(tmp_path)["text"]


def test_symlink_outside_repository_fails_closed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "outside.md").write_text("EXTERNAL_MARKER")
    (root / "alias.md").symlink_to(tmp_path / "outside.md")
    config(root, required=["alias.md"])
    with pytest.raises(ValueError, match="выходит за репозиторий"):
        payload(root)


@pytest.mark.parametrize("policy", [{"required": ["../secret"]}, {"required": "a.md"},
    {"forbidden": None}, {"required": ["a.md"], "forbidden": ["a.md"]}, {"other": []}])
def test_invalid_policy_blocks_quick_even_without_payload(tmp_path, policy):
    config(tmp_path, **policy)
    result = preflight.assess(SIGNALS, tmp_path, "demo")
    assert result["blocked"] and not result["checks"]["context_resource"]["ok"]


def test_required_missing_blocks_quick_preflight(tmp_path):
    config(tmp_path, required=["missing.md"])
    result = payload(tmp_path)
    assert result["resource_check"]["missing_required"] == ["missing.md"]
    pf = preflight.assess(SIGNALS, tmp_path, "demo", payload=result)
    assert pf["blocked"] and any("required" in r for r in pf["reasons"])


def test_required_over_budget_is_not_silently_truncated(tmp_path):
    (tmp_path / "large.md").write_text("R" * 10000)
    config(tmp_path, required=["large.md"])
    result = payload(tmp_path, context_budget=1000)
    assert "large.md" in result["resource_check"]["missing_required"]
    assert any(i["source"] == "large.md" for i in result["excluded_for_budget"])
    assert preflight.assess(SIGNALS, tmp_path, "demo", payload=result)["blocked"]


def test_overflow_counts_full_text_with_headers(tmp_path):
    result = payload(tmp_path, context_budget=20)
    assert result["compiled_text_tokens_estimate"] > result["payload_budget"]
    assert not result["resource_check"]["within_budget"]
    assert preflight.assess(SIGNALS, tmp_path, "demo", payload=result)["blocked"]


def test_configured_budget_is_used_without_cli_override(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("context_budget:\n  run_tokens: 20\n")
    result = payload(tmp_path)
    assert result["context_budget"] == 20
    assert not result["resource_check"]["ok"]


def test_payload_config_budget_does_not_restrict_legacy_bundle_inventory(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("context_budget:\n  run_tokens: 1000\n")
    bundle = compiler.compile_bundle(SIGNALS, tmp_path, build_plan=build_plan)
    result = payload(tmp_path, bundle=bundle)
    assert bundle["estimated_tokens"] > result["context_budget"]
    assert result["resource_check"]["ok"] and not bundle["overflow"]
    assert not preflight.assess(SIGNALS, tmp_path, "demo", bundle=bundle, payload=result)["blocked"]


def test_no_labels_means_unknown_even_with_required(tmp_path):
    (tmp_path / "a.md").write_text("A")
    config(tmp_path, required=["a.md"])
    metrics = payload(tmp_path)["metrics"]
    assert metrics["status"] == "unknown"
    assert metrics["precision"] is metrics["waste"] is metrics["miss"] is None


def test_metrics_use_explicit_labels_and_estimated_source_tokens():
    items = [{"source": "task", "tokens": 10}, {"source": "needed", "tokens": 30},
             {"source": "noise", "tokens": 60}]
    result = resource.relevance_metrics(items, {"relevant": ["task", "needed", "missed"],
        "irrelevant": ["noise"], "evidence": "ручная разметка fixture до прогона"})
    assert result["status"] == "measured" and result["precision"] == pytest.approx(2 / 3)
    assert result["waste"] == 0.6 and result["miss"] == pytest.approx(1 / 3)
    assert result["missing_relevant"] == ["missed"]


def test_partial_labels_do_not_inflate_precision():
    result = resource.relevance_metrics([{"source": "unknown", "tokens": 10}],
        {"relevant": ["needed"], "irrelevant": [], "evidence": "fixture"})
    assert result["status"] == "incomplete_labels"
    assert result["precision"] is result["waste"] is result["miss"] is None


@pytest.mark.parametrize("labels", [{"relevant": [], "irrelevant": []},
    {"relevant": ["a"], "irrelevant": ["a"], "evidence": "fixture"}])
def test_invalid_labels_fail_closed(labels):
    with pytest.raises(ValueError):
        resource.relevance_metrics([], labels)


def test_cli_payload_strict_reports_budget_before_execution(tmp_path):
    config(tmp_path, required=["missing.md"])
    result = subprocess.run([sys.executable, "-m", "ai_ops_kit.devtools.context_compile_cli",
        str(tmp_path), "--signals", json.dumps(SIGNALS), "--payload", "--json", "--strict"],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert json.loads(result.stdout)["resource_check"]["missing_required"] == ["missing.md"]


def test_real_pipeline_writes_only_after_context_check(tmp_path):
    from ai_ops_kit.engine import ai_ops_run
    from _ai_ops_run_helpers import _git_init_commit
    _git_init_commit(tmp_path)
    (tmp_path / "needed.md").write_text("REAL_SOURCE_1403")
    config(tmp_path, required=["needed.md"], forbidden=["rules/", "skills"])
    seen = []
    actions = iter([{"op": "write", "path": "src/observed.txt", "content": "REAL_SOURCE_1403"}, {"done": True}])

    def proposer(context):
        seen.append(str(context))
        assert "REAL_SOURCE_1403" in str(context)
        return next(actions)

    report = ai_ops_run.run(SIGNALS["task_text"], SIGNALS, tmp_path, execute=True,
                            proposer=proposer, feature="measured")
    assert seen and report["loop"]["applied_writes"] == 1
    assert (tmp_path / ".ai/worktrees/measured/src/observed.txt").read_text() == "REAL_SOURCE_1403"
    stored = yaml.safe_load((tmp_path / "features/measured/context-payload.yaml").read_text())
    assert stored["resource_check"]["ok"] and stored["metrics"]["status"] == "unknown"
    assert report["context_payload"]["metrics"] == stored["metrics"]


@pytest.mark.parametrize("policy", [{"required": ["missing.md"]}, {"required": ["needed.md"], "forbidden": ["needed.md"]}])
def test_real_pipeline_context_failure_never_calls_writer(tmp_path, policy):
    from ai_ops_kit.engine import ai_ops_run
    from _ai_ops_run_helpers import _git_init_commit
    _git_init_commit(tmp_path)
    (tmp_path / "needed.md").write_text("REAL_SOURCE_1403")
    config(tmp_path, **policy)
    calls = []

    def proposer(context):
        calls.append(context)
        return {"op": "write", "path": "src/should-not-exist", "content": "bad"}

    report = ai_ops_run.run(SIGNALS["task_text"], SIGNALS, tmp_path, execute=True,
                            proposer=proposer, feature="blocked")
    assert report["overall_status"] == "blocked-preflight" and calls == []
    assert not (tmp_path / "src/should-not-exist").exists()
    assert report["commit"]["sha"] is None


def test_hybrid_cannot_feed_forbidden_addition(tmp_path, monkeypatch):
    from ai_ops_kit.context import context_hybrid
    from ai_ops_kit.engine.ai_ops_run_reporting import _compile_context_artifacts
    (tmp_path / "denied.md").write_text("HYBRID_DENIED_MARKER")
    (tmp_path / "allowed.md").write_text("HYBRID_ALLOWED_MARKER")
    config(tmp_path, forbidden=["denied.md"])
    features = tmp_path / "features"
    (features / "demo").mkdir(parents=True)
    def forbidden_retrieval(*args, **kwargs):
        pytest.fail("hybrid retrieval не должен читать файлы при непустом forbidden")

    monkeypatch.setattr(context_hybrid, "build_hybrid_from_child", forbidden_retrieval)
    result = _compile_context_artifacts(SIGNALS, tmp_path, features, "demo",
        build_plan(SIGNALS, workitem_id="demo"), None, True, {}, SIGNALS["task_text"])
    prelude, hybrid = result[3:5]
    assert "HYBRID_ALLOWED_MARKER" not in prelude
    assert "HYBRID_DENIED_MARKER" not in prelude
    assert hybrid["fed_additions"] == []
    assert hybrid["mode"] == "v1-only" and "context.forbidden" in hybrid["reason"]
