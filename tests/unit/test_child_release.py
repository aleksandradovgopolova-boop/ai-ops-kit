"""#1548: дочка выпускает версию сама — после своих проверок, с описанием и «выпуск готов» до тега."""
import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import child_release as cr
from ai_ops_kit.devtools import release_bump

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/ci/ai-ops-release.yml"


def _child(tmp_path, release=None, **files):
    doc = {"parent": {"source": "x", "installed_version": "4.14.0"}}
    if release is not None:
        doc["release"] = release
    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump(doc))
    for name, text in files.items():
        (tmp_path / name.replace("__", ".")).write_text(text)
    return tmp_path


def test_release_is_off_until_owner_enables_it(tmp_path):
    root = _child(tmp_path, VERSION="1.2.0\n")
    assert cr.plan(root, tag_exists=False) == {
        "stage": "off", "needed": False, "reason": "включите release.enabled: true в .ai-ops.yaml"}


@pytest.mark.parametrize(("files", "version", "source"), [
    ({"VERSION": "1.2.0\n"}, "1.2.0", "VERSION"),
    ({"package__json": json.dumps({"version": "2.0.1"})}, "2.0.1", "package.json"),
    ({"pyproject__toml": '[project]\nname = "x"\nversion = "0.3.0"\n'}, "0.3.0", "pyproject.toml"),
    ({"Cargo__toml": '[package]\nname = "x"\nversion = "1.0.0-rc.1"\n'}, "1.0.0-rc.1", "Cargo.toml"),
])
def test_version_is_read_from_the_stack_manifest(tmp_path, files, version, source):
    root = _child(tmp_path, {"enabled": True}, **files)
    p = cr.plan(root, tag_exists=False)
    assert p["needed"] and p["version"] == version and p["tag"] == f"v{version}" and p["version_source"] == source
    assert not cr.plan(root, tag_exists=True)["needed"]


def test_no_version_refuses_with_reason(tmp_path):
    root = _child(tmp_path, {"enabled": True})
    p = cr.plan(root, tag_exists=False)
    assert p["stage"] == "refused" and "версия не найдена" in p["reason"]


def _profile(test="pytest", **extra):
    return {"stacks": [{"language": "python", "commands": {"test": test, "build": None}, **extra}]}


def test_failed_check_blocks_release(tmp_path):
    root = _child(tmp_path, {"enabled": True})
    res = cr.run_checks(root, _profile(test="false"))
    assert not res["ok"] and "не прошла: false" in res["reason"]
    assert cr.run_checks(root, _profile(test="true"))["ok"]


def test_unchecked_is_not_passed_unless_owner_allows(tmp_path):
    root = _child(tmp_path, {"enabled": True})
    res = cr.run_checks(root, {"stacks": []})
    assert not res["ok"] and res["reason"].startswith("не проверено")
    res = cr.run_checks(root, {"stacks": [{"language": "go", "commands": {"test": None, "build": "true"}}]})
    assert not res["ok"] and "нет команды тестов" in res["reason"]
    allowed = _child(tmp_path, {"enabled": True, "allow_unchecked": True})
    assert cr.run_checks(allowed, {"stacks": [{"language": "go", "commands": {"build": "true"}}]})["ok"]


def test_owner_declared_checks_win_over_profile(tmp_path):
    root = _child(tmp_path, {"enabled": True, "checks": ["true", "true"]})
    res = cr.run_checks(root, {"stacks": []})
    assert res["ok"] and [r["command"] for r in res["results"]] == ["true", "true"]


def test_notes_need_a_changelog_section(tmp_path):
    root = _child(tmp_path, {"enabled": True}, CHANGELOG__md="# Changelog\n\n## [1.1.0]\n\n- old\n")
    assert not cr.notes(root, "1.2.0")["ok"]
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.0 — 2026-11-16\n\n- новое\n\n## 1.1.0\n\n- old\n")
    res = cr.notes(root, "1.2.0")
    assert res["ok"] and "новое" in res["body"] and "old" not in res["body"]
    assert not res["owner_layer_checked"] and "не применялась" in res["reason"]


def test_marked_owner_layer_is_checked_by_kit_rules(tmp_path, monkeypatch):
    layer = "Что меняется для вас: быстрее вход."
    root = _child(tmp_path, {"enabled": True}, CHANGELOG__md=(
        f"## [1.2.0]\n\n{release_bump.OWNER_START}\n{layer}\n{release_bump.OWNER_END}\n\n- служебное\n"))
    monkeypatch.setattr(release_bump, "release_rules", lambda root: {})
    monkeypatch.setattr(release_bump, "check_owner_layer", lambda inner, rules: [])
    res = cr.notes(root, "1.2.0", "https://x/CHANGELOG.md")
    assert res["ok"] and res["owner_layer_checked"] and res["body"].startswith(layer)
    assert "служебное" not in res["body"]
    monkeypatch.setattr(release_bump, "check_owner_layer", lambda inner, rules: ["строка 1 — жаргон"])
    bad = cr.notes(root, "1.2.0")
    assert not bad["ok"] and "жаргон" in bad["reason"]


def test_workflow_is_delivered_and_tags_only_after_checks_and_ready():
    from installer import asset_ops
    assert "ai-ops-release.yml" in asset_ops.CI_TEMPLATES
    assert "ai-ops-release.yml" not in asset_ops.CONDITIONAL_CI_TEMPLATES
    wf = yaml.safe_load(TEMPLATE.read_text())
    assert wf["permissions"] == {"contents": "write"}
    steps = wf["jobs"]["release"]["steps"]
    order = [next(i for i, s in enumerate(steps) if key in s.get("run", "")) for key in
             ("child_release.py checks", "child_release.py notes", "--stage ready", "gh release create")]
    assert order == sorted(order)
    for i in order:
        assert steps[i]["if"] == "${{ steps.plan.outputs.needed == 'true' }}"
    for s in steps:
        for path in __import__("re").findall(r"RUNNER_TEMP\"?/ai-ops-kit/([\w./-]+\.py)", s.get("run", "")):
            assert (ROOT / path).is_file(), path
