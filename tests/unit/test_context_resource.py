"""#1403: настоящие файлы/payload, честная разметка и запрет исполнения до writer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from ai_ops_kit.context import context_compiler as compiler, context_cost as resource
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


@pytest.mark.parametrize("required_source", ["needed.md", "required-alias.md", "NEEDED.MD"])
def test_hybrid_feeds_allowed_addition_without_reading_forbidden(tmp_path, monkeypatch, required_source):
    from ai_ops_kit.engine.ai_ops_run_reporting import _compile_context_artifacts
    from _ai_ops_run_helpers import _git_init_commit
    (tmp_path / "src").mkdir()
    denied = tmp_path / "src/denied.py"
    denied.write_text("# ticketlookup HYBRID_DENIED_MARKER\n")
    (tmp_path / "src/allowed.py").write_text("# ticketlookup HYBRID_ALLOWED_MARKER\n")
    (tmp_path / "needed.md").write_text("ticketlookup REQUIRED_SOURCE_MARKER\n")
    (tmp_path / ".gitignore").write_text("features/\n.ai/runtime/\n.ai/worktrees/\n__pycache__/\n")
    if required_source == "required-alias.md":
        (tmp_path / required_source).symlink_to("needed.md")
    if not (tmp_path / required_source).is_file():
        pytest.skip("native case alias unavailable on this FS")
    config(tmp_path, required=[required_source], forbidden=["src/denied.py", "rules/", "skills"])
    policies = tmp_path / ".ai/policies"
    policies.mkdir(parents=True)
    (policies / "access-filter.yaml").write_text(yaml.safe_dump({"id":"test-afp", "rules":[
        {"role":"executor", "allowed_classes":["public", "internal"]}]}))
    (policies / "data-classification.yaml").write_text(yaml.safe_dump(
        {"id":"test-dcp", "default_class":"internal", "rules":[]}))
    _git_init_commit(tmp_path)
    sha = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    features = tmp_path / "features"
    (features / "demo").mkdir(parents=True)
    read = Path.read_text
    calls = []

    def guarded(path, *args, **kwargs):
        if path == denied:
            calls.append(str(path))
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    signals = {**SIGNALS, "task_text":"ticketlookup"}
    result = _compile_context_artifacts(signals, tmp_path, features, "demo",
        build_plan(signals, workitem_id="demo"), None, True, {"base_sha":sha}, signals["task_text"])
    errors, _, pay, prelude, hybrid = result[:5]
    assert calls == [] and not errors
    assert "HYBRID_ALLOWED_MARKER" in prelude
    assert "REQUIRED_SOURCE_MARKER" in prelude and "HYBRID_DENIED_MARKER" not in prelude
    assert hybrid["mode"] == "hybrid" and hybrid["fed_to_model"]
    assert hybrid["exact_snapshot"] and hybrid["snapshot_verified"] and hybrid["promotion_ready"]
    assert "context:" in hybrid["cache_key"]
    assert hybrid["fed_additions"] == ["src/allowed.py"]
    assert pay["metrics"]["status"] == "unknown"
    assert sum(i["source"] == required_source for i in pay["included_items"]) == 1
    assert prelude.count("REQUIRED_SOURCE_MARKER") == 1
    stored = yaml.safe_load((features / "demo/context-payload.yaml").read_text())
    assert stored["included_items"] == pay["included_items"]


def test_native_case_alias_cannot_bypass_forbidden(tmp_path, monkeypatch):
    denied = tmp_path / "secret.py"
    denied.write_text("CASE_ALIAS_PRIVATE_MARKER")
    alias = tmp_path / "alias.py"
    alias.symlink_to("SECRET.PY")
    if not alias.exists():
        pytest.skip("FS is case-sensitive; native case-alias is unavailable")
    assert alias.read_text() == "CASE_ALIAS_PRIVATE_MARKER"
    config(tmp_path, optional=["alias.py"], forbidden=["secret.py"])
    assert resource.forbidden(resource.load_policy(tmp_path), "alias.py", tmp_path)
    read = Path.read_text
    calls = []

    def guarded(path, *args, **kwargs):
        if path.is_file() and path.samefile(denied):
            calls.append(str(path))
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = payload(tmp_path)
    assert calls == [] and "CASE_ALIAS_PRIVATE_MARKER" not in result["text"]


def test_native_case_matching_preserves_distinct_files(tmp_path):
    upper, lower = tmp_path / "SECRET.py", tmp_path / "secret.py"
    upper.write_text("UPPER")
    lower.write_text("lower")
    if upper.samefile(lower):
        pytest.skip("FS is case-insensitive; distinct case-only files are unavailable")
    assert upper.read_text() != lower.read_text()
    config(tmp_path, optional=["SECRET.py"], forbidden=["secret.py"])
    assert not resource.forbidden(resource.load_policy(tmp_path), "SECRET.py", tmp_path)
    assert "UPPER" in payload(tmp_path)["text"]


def test_possible_case_alias_is_denied_when_native_metadata_unavailable(tmp_path, monkeypatch):
    source = tmp_path / 'SECRET.py'
    source.write_text('SOURCE_BODY')
    assert source.read_text() == 'SOURCE_BODY'
    iterdir = Path.iterdir

    def denied_directory(path):
        if path == tmp_path.resolve():
            raise PermissionError('controlled directory metadata failure')
        return iterdir(path)

    monkeypatch.setattr(Path, 'iterdir', denied_directory)
    assert resource.forbidden({'forbidden':['secret.py']}, 'SECRET.py', tmp_path)


@pytest.mark.parametrize('real_name,target', [
    ('sécret.py','SE\u0301CRET.PY'), ('se\u0301cret.py','SÉCRET.PY')])
def test_unicode_normalization_case_alias_is_forbidden(tmp_path, real_name, target):
    real = tmp_path / real_name
    real.write_text('UNICODE_PRIVATE_MARKER')
    alias = tmp_path / 'alias.py'
    alias.symlink_to(target)
    if not alias.exists():
        pytest.skip('FS does not support this normalization/case alias')
    assert alias.read_text() == 'UNICODE_PRIVATE_MARKER'
    config(tmp_path, optional=['alias.py'], forbidden=['sécret.py'])
    assert resource.forbidden(resource.load_policy(tmp_path), 'alias.py', tmp_path)
    assert 'UNICODE_PRIVATE_MARKER' not in payload(tmp_path)['text']


def test_normalization_does_not_merge_distinct_linux_names(tmp_path):
    nfc, nfd = tmp_path / 'sécret.py', tmp_path / 'se\u0301cret.py'
    nfc.write_text('NFC')
    nfd.write_text('ALLOWED_NFD_MARKER')
    if nfc.samefile(nfd):
        pytest.skip('FS normalizes these names to one file')
    assert nfc.read_text() != nfd.read_text()
    config(tmp_path, optional=[nfd.name], forbidden=[nfc.name])
    assert not resource.forbidden(resource.load_policy(tmp_path), nfd.name, tmp_path)
    assert 'ALLOWED_NFD_MARKER' in payload(tmp_path)['text']
