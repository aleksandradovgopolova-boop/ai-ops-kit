"""Структурные кандидаты garden на настоящих файлах, без модели и записи."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import garden

pytestmark = pytest.mark.unit


def _yaml(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def inventory_root(tmp_path):
    root = tmp_path / "kit"
    for name in ("skills", "workflows", "rules"):
        (root / name).mkdir(parents=True)
    _yaml(root, "registry/agents.yaml", {"agents": [
        {"id": "used", "file": "agents/used.md"},
        {"id": "manual", "file": "agents/manual.md"}]})
    _yaml(root, "registry/workflows.yaml", {"workflows": {
        "QUICK": {"stages": [{"owner": "used", "writer": "used"}]}}})
    _yaml(root, "registry/routing-policy.yaml", {})
    _yaml(root, "quality/gates.yaml", {"required_checks_lifecycle": {"docs / build": {
        "responsible_role": "used", "retirement_condition": "Документацию проверяет эквивалентная замена."}},
        "gates": {"g1": {
        "id": "g1", "validator": "validate-x", "blocking": True,
        "responsible_role": "used", "retirement_condition": "Область проверки снята решением.",
        "stage": "build", "applicability": ["QUICK"], "required_evidence": ["proof"],
        "prevents": "missing-proof"}}})
    (root / "quality/premerge-checks.json").write_text(json.dumps({"docs.yml": ["build"]}))
    _yaml(root, "quality/required-contexts.yaml", {"contexts": ["docs / build"]})
    _yaml(root, ".github/workflows/docs.yml", {"jobs": {"build": {}, "new": {}}})
    _yaml(root, "standards/architecture/rules.yaml", {"rules": [
        {"id": "R-1", "level": "MUST", "gate": "validate-x", "enforced_in": "parent"}]})
    _yaml(root, "decisions/registry.yaml", {"principles": [{"id": "p-old", "status": "ratified"}],
                                            "episodes": []})
    for name in ("used", "manual"):
        p = root / f"agents/{name}.md"
        p.parent.mkdir(exist_ok=True)
        p.write_text(f"# {name}\n", encoding="utf-8")
    return root


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def test_exact_skill_and_workflow_copies_have_source_links(inventory_root):
    root = inventory_root
    for rel in ("skills/a/SKILL.md", "skills/b/SKILL.md", "workflows/a.md", "workflows/b.md"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# Shared\n\nA real instruction.\n", encoding="utf-8")
    groups = garden.inventory_signals(root)["duplicate_documents"]
    assert len(groups) == 1
    assert {x["path"] for x in groups[0]["sources"]} == {
        "skills/a/SKILL.md", "skills/b/SKILL.md", "workflows/a.md", "workflows/b.md"}
    assert all(x["line"] >= 1 and (root / x["path"]).is_file() for x in groups[0]["sources"])


def test_document_copy_changes_finding_but_inventory_never_writes(inventory_root):
    root = inventory_root
    first = root / "skills/a/SKILL.md"
    first.parent.mkdir(parents=True)
    first.write_text("# Action\n\nDo the task.\n", encoding="utf-8")
    assert garden.inventory_signals(root)["duplicate_documents"] == []
    second = root / "skills/b/SKILL.md"
    second.parent.mkdir(parents=True)
    second.write_bytes(first.read_bytes())
    assert second.is_file() and first.read_bytes() == second.read_bytes()
    before = _snapshot(root)
    assert garden.inventory_signals(root)["duplicate_documents"]
    assert before == _snapshot(root)
    second.unlink()
    assert garden.inventory_signals(root)["duplicate_documents"] == []


def test_indentation_and_empty_documents_are_not_false_duplicates(inventory_root):
    root = inventory_root
    for name, content in (("a", "```python\nif ok:\n    run()\n```\n"),
                          ("b", "```python\nif ok:\nrun()\n```\n"), ("c", ""), ("d", "\n")):
        p = root / f"skills/{name}/SKILL.md"
        p.parent.mkdir(parents=True)
        p.write_text(content)
    assert garden.inventory_signals(root)["duplicate_documents"] == []


def test_agent_declaration_is_not_its_own_consumer(inventory_root):
    root = inventory_root
    rows = garden.inventory_signals(root)["unreferenced_agents"]
    assert [r["id"] for r in rows] == ["manual"]
    assert rows[0]["sources"][0]["path"] == "agents/manual.md"
    _yaml(root, "rules/quality/manual.yaml", {"id": "manual-review", "used_by": ["manual"]})
    assert garden.inventory_signals(root)["unreferenced_agents"] == []


def test_same_validator_in_different_scopes_is_not_a_duplicate(inventory_root):
    root = inventory_root
    p = root / "quality/gates.yaml"
    doc = yaml.safe_load(p.read_text())
    doc["gates"]["g2"] = {**doc["gates"]["g1"], "id": "g2", "applicability": ["OTHER"]}
    _yaml(root, "quality/gates.yaml", doc)
    assert garden.inventory_signals(root)["duplicate_checks"] == []
    doc["gates"]["g2"]["applicability"] = ["QUICK"]
    _yaml(root, "quality/gates.yaml", doc)
    assert garden.inventory_signals(root)["duplicate_checks"][0]["ids"] == ["g1", "g2"]


@pytest.mark.parametrize("field", ["required_when", "applies_when", "skip_when"])
def test_gate_conditions_are_part_of_duplicate_identity(inventory_root, field):
    root = inventory_root
    doc = yaml.safe_load((root / "quality/gates.yaml").read_text())
    doc["gates"]["g2"] = {**doc["gates"]["g1"], "id": "g2", field: "has-api"}
    doc["gates"]["g1"][field] = "has-ui"
    _yaml(root, "quality/gates.yaml", doc)
    assert garden.inventory_signals(root)["duplicate_checks"] == []


def test_retired_and_replaced_rules_are_explicit_not_age_guesses(inventory_root):
    root = inventory_root
    _yaml(root, "decisions/registry.yaml", {"principles": [
        {"id": "p-old", "status": "ratified"},
        {"id": "p-new", "status": "ratified", "supersedes": "p-old"},
        {"id": "p-retired", "status": "retired"},
        {"id": "p-active", "status": "ratified", "date": "1990-01-01"}], "episodes": []})
    rows = garden.inventory_signals(root)["stale_rules"]
    assert {r["id"] for r in rows} == {"p-old", "p-retired"}
    assert all(r["sources"][0]["path"] == "decisions/registry.yaml" for r in rows)


def test_same_rule_id_with_opposite_declarations_is_named(inventory_root):
    _yaml(inventory_root, "standards/architecture/rules.yaml", {"rules": [
        {"id": "R-1", "level": "MUST", "gate": "validate-x"},
        {"id": "R-1", "level": "MUST_NOT", "gate": "none"}]})
    rows = garden.inventory_signals(inventory_root)["conflicting_declarations"]
    assert rows[0]["id"] == "R-1"
    assert rows[0]["sources"][0]["path"] == "standards/architecture/rules.yaml"


def test_same_rule_id_in_two_files_preserves_both_sources(inventory_root):
    _yaml(inventory_root, "rules/a.yaml", {"id": "same", "level": "MUST"})
    _yaml(inventory_root, "rules/b.yaml", {"id": "same", "level": "MUST_NOT"})
    rows = garden.inventory_signals(inventory_root)["conflicting_declarations"]
    assert {s["path"] for s in rows[0]["sources"]} == {"rules/a.yaml", "rules/b.yaml"}


def test_retirement_gaps_and_limits_are_visible(inventory_root):
    p = inventory_root / "quality/gates.yaml"
    doc = yaml.safe_load(p.read_text())
    doc["gates"]["g1"].pop("responsible_role")
    doc["gates"]["g1"].pop("retirement_condition")
    _yaml(inventory_root, "quality/gates.yaml", doc)
    report = garden.inventory_signals(inventory_root)
    assert report["retirement_gaps"][0]["missing"] == ["responsible_role", "retirement_condition"]
    assert report["limits"] and "семантик" in " ".join(report["limits"]).lower()
    assert json.loads(json.dumps(report, ensure_ascii=False)) == report


def test_broken_registry_is_not_a_clean_inventory(inventory_root):
    (inventory_root / "registry/agents.yaml").write_text("agents: [broken\n")
    with pytest.raises((ValueError, yaml.YAMLError)):
        garden.inventory_signals(inventory_root)


def test_missing_source_is_not_presented_as_a_working_link(inventory_root):
    (inventory_root / "agents/manual.md").unlink()
    with pytest.raises(ValueError, match="не файл"):
        garden.inventory_signals(inventory_root)


@pytest.mark.parametrize("rel,doc", [
    ("registry/agents.yaml", {"agents": [{"id": None}]}),
    ("registry/workflows.yaml", {"workflows": {"QUICK": "broken"}}),
    ("quality/gates.yaml", {"gates": ["g1"]}),
])
def test_wrong_registry_shape_does_not_become_empty_success(inventory_root, rel, doc):
    _yaml(inventory_root, rel, doc)
    with pytest.raises(ValueError):
        garden.inventory_signals(inventory_root)


@pytest.mark.parametrize("directory", ["skills", "workflows", "rules"])
def test_missing_inventory_directory_is_not_clean(inventory_root, directory):
    (inventory_root / directory).rmdir()
    with pytest.raises(ValueError, match="каталога"):
        garden.inventory_signals(inventory_root)


def test_missing_agents_key_is_not_an_empty_registry(inventory_root):
    _yaml(inventory_root, "registry/agents.yaml", {})
    with pytest.raises(ValueError):
        garden.inventory_signals(inventory_root)


def test_required_ci_check_without_lifecycle_is_a_visible_gap(inventory_root):
    (inventory_root / "quality/premerge-checks.json").write_text(json.dumps({"docs.yml": ["build", "new"]}))
    rows = garden.inventory_signals(inventory_root)["retirement_gaps"]
    assert rows[0]["id"] == "docs / new"
    assert rows[0]["missing"] == ["responsible_role", "retirement_condition"]


def test_required_context_only_check_has_same_gap_and_is_not_stale_when_owned(inventory_root):
    root = inventory_root
    _yaml(root, "quality/required-contexts.yaml", {"contexts": ["docs / build", "docs / new"]})
    report = garden.inventory_signals(root)
    assert report["retirement_gaps"][0]["id"] == "docs / new"
    doc = yaml.safe_load((root / "quality/gates.yaml").read_text())
    doc["required_checks_lifecycle"]["docs / new"] = doc["required_checks_lifecycle"]["docs / build"].copy()
    _yaml(root, "quality/gates.yaml", doc)
    report = garden.inventory_signals(root)
    assert report["retirement_gaps"] == []
    assert not any(r["id"] == "docs / new" for r in report["stale_rules"])


def test_symlink_outside_root_is_rejected_before_reading(inventory_root, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    p = inventory_root / "skills/x/SKILL.md"
    p.parent.mkdir(parents=True)
    p.symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(ValueError, match="корень"):
        garden.inventory_signals(inventory_root)
    assert outside.read_bytes() == before
