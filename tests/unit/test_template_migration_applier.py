"""Применение миграции версии шаблона к экземпляру в дочке (`migrate_instance`).

НЕДОСТАЮЩАЯ ПОЛОВИНА механизма: `state_of` ставил диагноз OUTDATED, а миграцию НИКТО не применял.
Здесь доказывается, что applier РЕАЛЬНО проводит устаревший экземпляр до актуальной версии, выполняя
`up.py`, сохраняя содержимое, — и что успех подтверждается повторным VALID, а не фактом запуска.

Мутация: снять запуск `up.py` из `migrate_instance` -> экземпляр остаётся OUTDATED, тест краснеет.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ai_ops_kit.planning import product_templates as pt

_ARTIFACT = {
    "id": "demo_cfg", "kind": "file", "format": "yaml", "path": ".ai-ops/DEMO.yaml",
    "template": {"version": 2},
    "structure": {"required_fields": ["template_version", "keep"]}, "validation": [],
}


def _child_at_v1(tmp_path: Path) -> Path:
    repo = tmp_path / "child"
    (repo / ".ai-ops").mkdir(parents=True)
    (repo / ".ai-ops" / "DEMO.yaml").write_text(
        "template_version: 1\nkeep: preserve-me\n", encoding="utf-8")
    return repo


def _pkg_with_migration(tmp_path: Path, up_body: str) -> Path:
    pkg = tmp_path / "pkg"
    step = pkg / "migrations" / "product-layer-templates" / "demo_cfg" / "v1-to-v2"
    step.mkdir(parents=True)
    (step / "up.py").write_text(up_body, encoding="utf-8")
    (step / "down.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    return pkg


_GOOD_UP = (
    "import sys, yaml\n"
    "p = sys.argv[1]\n"
    "d = yaml.safe_load(open(p, encoding='utf-8')) or {}\n"
    "d['template_version'] = 2\n"
    "open(p, 'w', encoding='utf-8').write(yaml.safe_dump(d, allow_unicode=True))\n"
)


def test_outdated_instance_is_migrated_to_valid_content_preserved(tmp_path):
    repo = _child_at_v1(tmp_path)
    pkg = _pkg_with_migration(tmp_path, _GOOD_UP)
    reg = {"artifacts": [_ARTIFACT]}
    assert pt.state_of(repo, _ARTIFACT, reg)["state"] == pt.OUTDATED   # до: устарел

    res = pt.migrate_instance(repo, _ARTIFACT, reg, pkg_root=pkg)

    assert res["migrated"] is True, res
    assert (res["from"], res["to"]) == (1, 2)
    assert pt.state_of(repo, _ARTIFACT, reg)["state"] == pt.VALID       # после: актуален
    d = yaml.safe_load((repo / ".ai-ops" / "DEMO.yaml").read_text(encoding="utf-8"))
    assert d["template_version"] == 2
    assert d["keep"] == "preserve-me"                                   # содержимое сохранено


def test_valid_instance_is_not_migrated(tmp_path):
    repo = tmp_path / "child"
    (repo / ".ai-ops").mkdir(parents=True)
    (repo / ".ai-ops" / "DEMO.yaml").write_text(
        "template_version: 2\nkeep: x\n", encoding="utf-8")
    pkg = _pkg_with_migration(tmp_path, _GOOD_UP)
    res = pt.migrate_instance(repo, _ARTIFACT, {"artifacts": [_ARTIFACT]}, pkg_root=pkg)
    assert res["migrated"] is False
    assert res["state_after"] == pt.VALID                              # нечего мигрировать — честно


def test_missing_migration_step_is_fail_closed(tmp_path):
    repo = _child_at_v1(tmp_path)
    pkg = tmp_path / "pkg-empty"          # шага миграции нет
    (pkg / "migrations" / "product-layer-templates").mkdir(parents=True)
    res = pt.migrate_instance(repo, _ARTIFACT, {"artifacts": [_ARTIFACT]}, pkg_root=pkg)
    assert res["migrated"] is False
    assert "нет миграции" in res["reason"]                            # не тихий успех
    assert pt.state_of(repo, _ARTIFACT, {"artifacts": [_ARTIFACT]})["state"] == pt.OUTDATED


def test_failing_up_script_does_not_claim_success(tmp_path):
    repo = _child_at_v1(tmp_path)
    pkg = _pkg_with_migration(tmp_path, "import sys; sys.exit(1)\n")   # up.py падает
    res = pt.migrate_instance(repo, _ARTIFACT, {"artifacts": [_ARTIFACT]}, pkg_root=pkg)
    assert res["migrated"] is False
    assert "упала" in res["reason"]
    assert pt.state_of(repo, _ARTIFACT, {"artifacts": [_ARTIFACT]})["state"] == pt.OUTDATED


_POLICY_V1 = """\
template_version: 1
schema_version: 1

autonomy:
  update_artifacts: prepare
  create_pr: prepare
  merge: require_approval
  change_policy: require_approval

protected_paths:
  - ".ai-ops/POLICY.yaml"    # комментарий владельца — должен уцелеть

approvals:
  required_for:
    - удаление данных
"""


def test_real_policy_v1_to_v2_migration_on_a_child(tmp_path):
    """СКВОЗНОЙ НА РЕАЛЬНОМ АРТЕФАКТЕ: устаревший POLICY.yaml (v1) в дочке проведён до v2 РЕАЛЬНОЙ
    миграцией policy/v1-to-v2 через applier — не только диагноз «устарел». Это и есть исход
    templates_have_versions_and_migrations, показанный на живом артефакте.

    Использует НАСТОЯЩИЙ реестр (policy=v2) и НАСТОЯЩУЮ миграцию (pkg_root по умолчанию)."""
    from ai_ops_kit.planning import artifact_registry as AR
    reg = AR.load()
    policy = next(a for a in AR.artifacts(reg) if a["id"] == "policy")
    assert (policy.get("template") or {}).get("version") == 2, "реестр должен объявлять policy v2"

    repo = tmp_path / "child"
    (repo / ".ai-ops").mkdir(parents=True)
    inst = repo / ".ai-ops" / "POLICY.yaml"
    inst.write_text(_POLICY_V1, encoding="utf-8")
    assert pt.state_of(repo, policy, reg)["state"] == pt.OUTDATED       # до: устарел (v1 < v2)

    res = pt.migrate_instance(repo, policy, reg)                        # РЕАЛЬНАЯ миграция

    assert res["migrated"] is True, res
    assert pt.state_of(repo, policy, reg)["state"] == pt.VALID          # после: актуален
    text = inst.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["template_version"] == 2
    assert data["enforcement"] == "observe"                            # поле v2 добавлено
    assert data["autonomy"]["merge"] == "require_approval"             # содержимое сохранено
    assert "комментарий владельца" in text                            # комментарии уцелели
