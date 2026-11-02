"""Real temporary writes prove feature containment and policy-load refusal."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates import spec_levels
from ai_ops_kit.lifecycle import workitem


@pytest.mark.parametrize("intent", ["new", "specify"])
@pytest.mark.parametrize("feature", ["../../escaped", "/absolute", "../escape", "valid\n", "нет-такого"])
def test_cli_rejects_feature_before_any_project_write(tmp_path, intent, feature, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    if feature == "/absolute":
        feature = str(tmp_path / "absolute")
    assert ai_ops_cli.main([intent, "Добавь выгрузку CSV", str(root),
                            "--feature", feature, "--json"]) == 2
    assert list(root.iterdir()) == []
    assert not (tmp_path / "escaped").exists()
    assert "workitem_id" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["workitem", "spec"])
@pytest.mark.parametrize("feature", ["../../escaped", "/absolute", "../escape"])
def test_artifact_api_rejects_invalid_id_without_write(tmp_path, kind, feature):
    root = tmp_path / "repo"
    root.mkdir()
    if feature == "/absolute":
        feature = str(tmp_path / "absolute")
    with pytest.raises(ValueError, match="workitem_id"):
        if kind == "workitem":
            workitem.start(root / "features", feature, "fixture")
        else:
            spec_levels.create_spec(root, feature, {"task_type": "QUICK"})
    assert list(root.iterdir()) == []
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("kind", ["workitem", "spec"])
@pytest.mark.parametrize("link_at", ["features", "feature", "artifact"])
def test_artifact_api_rejects_existing_symlink_escape(tmp_path, kind, link_at):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    name = "workitem.yaml" if kind == "workitem" else "spec.yaml"
    target = outside / name
    target.write_text("original outside bytes\n")
    features = root / "features"
    if link_at == "features":
        features.symlink_to(outside, target_is_directory=True)
    else:
        features.mkdir()
        if link_at == "feature":
            (features / "safe-id").symlink_to(outside, target_is_directory=True)
        else:
            (features / "safe-id").mkdir()
            (features / "safe-id" / name).symlink_to(target)
    before = sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*"))
    with pytest.raises(ValueError, match="предел"):
        if kind == "workitem":
            workitem.start(features, "safe-id", "fixture")
        else:
            spec_levels.create_spec(root, "safe-id", {"task_type": "QUICK"}, overwrite=True)
    assert target.read_text() == "original outside bytes\n"
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")) == before


def test_valid_artifacts_really_write_inside_selected_project(tmp_path):
    workitem.start(tmp_path / "features", "safe-id", "fixture")
    path, created, _ = spec_levels.create_spec(tmp_path, "safe-id", {"task_type": "QUICK"})
    assert created and path.is_file()
    assert workitem.wi_path(tmp_path / "features", "safe-id").is_file()
    assert path.resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("intent", ["new", "specify"])
def test_cli_rejects_feature_symlink_before_process_trace(tmp_path, intent, capsys):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    (root / "features").mkdir(parents=True)
    outside.mkdir()
    (root / "features/safe-id").symlink_to(outside, target_is_directory=True)
    assert ai_ops_cli.main([intent, "Добавь выгрузку CSV", str(root),
                            "--feature", "safe-id", "--json"]) == 2
    assert list(outside.iterdir()) == []
    assert "предел" in capsys.readouterr().err


@pytest.mark.parametrize("intent,filename", [("specify", "short-path.yaml"),
                                            ("discuss", "discovery-draft.md"),
                                            ("new", "workitem.yaml"),
                                            ("plan", "run-plan.yaml")])
def test_cli_rejects_sibling_artifact_link_before_any_write(tmp_path, intent, filename):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    feature = root / "features/safe-id"
    feature.mkdir(parents=True)
    outside.mkdir()
    target = outside / "sentinel"
    (feature / filename).symlink_to(target)  # Includes a dangling output link.
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert ai_ops_cli.main([intent, "уже описано", str(root), "--feature", "safe-id",
                            "--json"]) == 2
    assert not target.exists()
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


@pytest.mark.parametrize("escape", ["traversal", "symlink"])
def test_answers_api_preserves_external_spec(tmp_path, escape):
    from ai_ops_kit.shared import spec_answers

    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "spec.yaml"
    target.write_text("sections: {}\n")
    if escape == "traversal":
        wid = "../../outside"
    else:
        wid = "safe-id"
        feature = root / "features" / wid
        feature.mkdir(parents=True)
        (feature / "spec.yaml").symlink_to(target)
    result = spec_answers.apply_answers(root, wid, "зачем=new")
    assert result["error"] and result["applied"] == []
    assert target.read_text() == "sections: {}\n"


def test_trace_checks_record_link_before_creating_spec(tmp_path):
    from ai_ops_kit.planning import short_path

    root, outside = tmp_path / "repo", tmp_path / "outside"
    feature = root / "features/safe-id"
    feature.mkdir(parents=True)
    outside.mkdir()
    target = outside / "record.yaml"
    target.write_text("outside bytes\n")
    (feature / "short-path.yaml").symlink_to(target)
    with pytest.raises(ValueError, match="предел"):
        short_path.trace(root, "safe-id", {"task_type": "QUICK"}, {})
    assert target.read_text() == "outside bytes\n"
    assert not (feature / "spec.yaml").exists()


@pytest.mark.parametrize("rel", [".ai-ops.yaml", "config/protected-paths.yaml"])
@pytest.mark.parametrize("content", ["protected_paths: [", "- not-a-map", "protected_paths: private/",
                                     "protected_paths: [null]", "protected_paths: [{path: 4}]"])
def test_invalid_existing_policy_refuses_before_execution(tmp_path, rel, content):
    source = tmp_path / rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="policy"):
        tool_broker.Policy(level="controlled-write", write_scope=["private/"], child_root=tmp_path)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_unreadable_policy_does_not_become_missing(tmp_path, monkeypatch):
    source = tmp_path / "config/protected-paths.yaml"
    source.parent.mkdir()
    source.write_text("protected_paths: [private/]\n")
    read = Path.read_text

    def refused(path, *args, **kwargs):
        if path == source:
            raise PermissionError("fixture content must not appear in diagnostics")
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refused)
    with pytest.raises(ValueError, match="policy") as caught:
        tool_broker.Policy(child_root=tmp_path)
    assert "fixture content" not in str(caught.value)
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize("rel", [".ai-ops.yaml", "config/protected-paths.yaml"])
def test_invalid_encoding_and_broken_policy_link_refuse(tmp_path, rel):
    source = tmp_path / rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="policy"):
        tool_broker.Policy(child_root=tmp_path)
    source.unlink()
    source.symlink_to(tmp_path / "absent-policy")
    with pytest.raises(ValueError, match="policy"):
        tool_broker.Policy(child_root=tmp_path)
    assert not (tmp_path / "absent-policy").exists()


def test_missing_optional_policy_allows_real_scoped_write(tmp_path):
    policy = tool_broker.Policy(level="controlled-write", write_scope=["private/"], child_root=tmp_path)
    result = tool_broker.execute({"op": "write", "path": "private/probe.txt", "content": "fixture"},
                                 tmp_path, policy)
    assert result["allowed"] and result["ok"]
    assert (tmp_path / "private/probe.txt").read_text() == "fixture"


@pytest.mark.parametrize("entry", ["private/", {"path": "private/", "approval": "required"}])
def test_valid_policy_still_merges_default_and_child_protection(tmp_path, entry):
    import yaml

    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump({"protected_paths": [entry]}))
    policy = tool_broker.Policy(level="controlled-write", write_scope=["private/", "security/"],
                                child_root=tmp_path)
    for path in ["private/probe.txt", "security/probe.txt"]:
        result = tool_broker.execute({"op": "write", "path": path, "content": "fixture"}, tmp_path, policy)
        assert not result["allowed"] and not result["ok"]
        assert not (tmp_path / path).exists()
