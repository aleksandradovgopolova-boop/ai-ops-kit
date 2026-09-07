"""SR-9..13: архитектурные инварианты дочки как ДАННЫЕ, проверяемые advisory (срез 3).

Проверяется КОНТРАКТ инварианта (данные с id/правилом/причиной/силой), ОДИН резолвер путь->зона,
адрес у нарушения (файл:строка -> ребро), not_checked вместо pass на непроверяемом, и новая
зависимость без ADR как находка. Логика проверки — та же форма, что у validate_layering.check
(зоны, запреты, поимённые исключения, реестр только-вниз): демонстрируется на объявлении дочки И
на объявлении кит-образной формы одним и тем же check().
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import architecture_invariants as A
from ai_ops_kit.planning import governance_report as G

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
SCHEMA = json.loads((PKG / "schemas" / "architecture-invariants.schema.json").read_text(encoding="utf-8"))

# Объявление дочки: фронтенд не ходит в базу напрямую (типовой инвариант из §4/SR-11).
DECL = {
    "kind": "architecture-invariants",
    "schema_version": 1,
    "zones": {
        "frontend": ["src/features/**", "src/app/**"],
        "data": ["src/db/**"],
    },
    "aliases": {"@/": "src/"},
    "rules": [
        {"id": "frontend-not-to-db", "forbid": {"from": "frontend", "to": "data"},
         "reason": "фронтенд не обращается к базе напрямую — только через сервисный слой"},
    ],
}


def _child(tmp_path, decl=DECL, files=None) -> Path:
    """Дочка с объявлением инварианта в architecture-invariants.yaml и заданными исходниками."""
    if decl is not None:
        (tmp_path / "architecture-invariants.yaml").write_text(
            yaml.safe_dump(decl, allow_unicode=True), encoding="utf-8")
    for rel, text in (files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── SR-9: инвариант — данные с id, правилом, причиной и силой ──

@pytest.mark.unit
def test_declaration_carries_id_rule_reason_strength():
    """Правило несёт идентификатор, запрет-ребро и причину; сила блока — advisory (§5.2)."""
    rep = A.report(_child_from_dict(DECL), deps=None)
    assert rep["strength"] == "advisory"
    rule = DECL["rules"][0]
    assert rule["id"] and rule["forbid"] and rule["reason"], "инвариант обязан нести id/правило/причину"


@pytest.mark.unit
def test_same_check_logic_serves_kit_shaped_and_child_declarations():
    """SR-9: ТОТ ЖЕ check() ловит нарушение и на объявлении дочки, и на кит-образной форме."""
    child_edges = [{"from_file": "src/features/x.ts", "line": 3, "import": "@/db/client",
                    "from_zone": "frontend", "to_zone": "data"}]
    child_findings = A.check(DECL, child_edges)
    assert len(child_findings) == 1 and child_findings[0]["status"] == "violated"

    # Кит-образная форма (пакеты как зоны) — то же объявление-данные, тот же вызов.
    kit_decl = {"zones": {"gates": ["gates/**"], "engops": ["engops/**"]},
                "rules": [{"id": "kernel-boundary", "forbid": {"from": "gates", "to": "engops"},
                           "reason": "ядро не импортирует спутники"}]}
    kit_edges = [{"from_file": "gates/a.py", "line": 1, "import": "engops.b",
                  "from_zone": "gates", "to_zone": "engops"}]
    assert len(A.check(kit_decl, kit_edges)) == 1


# ── SR-10: зона объявлена глобами и читается из одного места ──

@pytest.mark.unit
def test_zone_of_is_the_single_resolver_over_globs():
    zones = DECL["zones"]
    assert A.zone_of("src/features/users/api.ts", zones) == "frontend"
    assert A.zone_of("src/db/client.ts", zones) == "data"
    assert A.zone_of("src/shared/util.ts", zones) is None, "путь вне зон -> None, не выдумка"


@pytest.mark.unit
def test_alias_and_relative_imports_resolve_to_zones():
    root = _child(_fresh(), files={
        "src/features/users/api.ts": "import { db } from '@/db/client';\n",
        "src/app/page.tsx": "import x from '../db/client';\n",  # относительный из app -> data
        "src/db/client.ts": "export const db = 1;\n",
    })
    edges = A.build_import_graph(root, DECL["zones"], DECL["aliases"])
    pairs = {(e["from_zone"], e["to_zone"]) for e in edges}
    assert ("frontend", "data") in pairs


# ── SR-11: нарушение называет адрес, а не факт ──

@pytest.mark.unit
def test_violation_names_file_line_and_edge():
    root = _child(_fresh(), files={
        "src/features/users/api.ts": "//头\nimport { db } from '@/db/client';\n",
        "src/db/client.ts": "export const db = 1;\n",
    })
    rep = A.report(root, deps=None)
    viol = [r for r in rep["rows"] if r["status"] == "violated"]
    assert viol, "нарушение обязано найтись"
    addr = viol[0]["address"]
    assert "src/features/users/api.ts:2" in addr, f"адрес без файла:строки: {addr}"
    assert "@/db/client" in addr, "адрес обязан назвать ребро (импорт)"


# ── SR-12: непроверяемое — not_checked с причиной, а не pass ──

@pytest.mark.unit
def test_no_zones_declared_is_not_checked_not_pass():
    root = _child(_fresh(), decl=None)                      # нет объявления вовсе
    rep = A.report(root, deps=None)
    zone_rows = [r for r in rep["rows"] if r["requirement"] == "architecture::zones"]
    assert zone_rows and zone_rows[0]["status"] == "not_checked"
    assert zone_rows[0].get("reason"), "not_checked обязан нести причину"
    assert all(r["status"] != "pass" for r in zone_rows)


@pytest.mark.unit
def test_declared_but_clean_repo_is_pass():
    root = _child(_fresh(), files={
        "src/features/users/api.ts": "import { svc } from '@/app/service';\n",  # frontend->frontend
        "src/app/service.ts": "export const svc = 1;\n",
    })
    rep = A.report(root, deps=None)
    assert rep["counts"]["violated"] == 0
    assert any(r["status"] == "pass" for r in rep["rows"])


# ── SR-9: known_violations — реестр только-вниз ──

@pytest.mark.unit
def test_frozen_violation_is_suppressed_and_stale_freeze_is_a_finding():
    frozen = dict(DECL, known_violations=["frontend -> data: legacy, выносим в сервис"])
    edges = [{"from_file": "src/features/x.ts", "line": 1, "import": "@/db/c",
              "from_zone": "frontend", "to_zone": "data"}]
    assert A.check(frozen, edges) == [], "замороженное ребро не краснеет повторно"
    # Заморозка есть, а ребра в коде нет -> находка «снять из реестра».
    stale = A.check(frozen, [])
    assert len(stale) == 1 and "исчезла из кода" in stale[0]["detail"]


@pytest.mark.unit
def test_named_exception_suppresses_one_address():
    exc = dict(DECL, exceptions=["src/features/legacy.ts -> data"])
    edges = [{"from_file": "src/features/legacy.ts", "line": 1, "import": "@/db/c",
              "from_zone": "frontend", "to_zone": "data"}]
    assert A.check(exc, edges) == [], "поимённое исключение снимает находку с этого файла"


# ── SR-13: новая зависимость без ADR — находка с адресом ──

@pytest.mark.unit
def test_new_dependency_without_adr_is_a_finding():
    root = _fresh()
    before = {"package.json": json.dumps({"dependencies": {"react": "18"}})}
    after = {"package.json": json.dumps({"dependencies": {"react": "18", "left-pad": "1"}})}
    findings = A.dependency_findings(root, before, after)
    assert len(findings) == 1
    assert "left-pad" in findings[0]["address"]
    assert findings[0]["status"] == "violated"


@pytest.mark.unit
def test_new_dependency_with_adr_is_silent():
    root = _child(_fresh(), decl=None)
    (root / "decisions").mkdir()
    (root / "decisions" / "ADR-005-left-pad.md").write_text(
        "# Решение: вводим left-pad для выравнивания\n", encoding="utf-8")
    before = {"package.json": json.dumps({"dependencies": {}})}
    after = {"package.json": json.dumps({"dependencies": {"left-pad": "1"}})}
    assert A.dependency_findings(root, before, after) == [], "названная в ADR зависимость тиха"


@pytest.mark.unit
def test_deps_none_reports_not_checked_not_pass():
    rep = A.report(_child_from_dict(DECL), deps=None)
    dep_rows = [r for r in rep["rows"] if r["requirement"].startswith("architecture::new-dependency")]
    assert dep_rows and dep_rows[0]["status"] == "not_checked"
    assert dep_rows[0].get("reason")


# ── Проводка в governance-отчёт: отдельный advisory-блок, не свёрнут в четыре числа ──

@pytest.mark.unit
def test_governance_report_carries_architecture_block(tmp_path):
    cfg = {"schema_version": 1, "kind": "ai-ops-child-config",
           "parent": {"source": "git+x", "installed_version": "1.0.0",
                      "update_channel": "qualification", "update_policy": "pr"},
           "standard": {"version": 1, "profile": "ai-product"}}
    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    rep = G.build(tmp_path)
    arch = rep["architecture"]
    assert arch["kind"] == "architecture-invariants" and arch["strength"] == "advisory"
    # Четыре числа секций §3.2 не тронуты архитектурным блоком.
    c = rep["counts"]
    assert c["pass"] + c["violated"] + c["not_applicable"] + c["not_checked"] == c["total"]
    assert c["total"] == len(rep["rows"])


@pytest.mark.unit
def test_architecture_block_matches_schema_shape():
    rep = A.report(_child_from_dict(DECL), deps=None)
    for k in ("kind", "strength", "counts", "rows"):
        assert k in rep
    status_enum = set(SCHEMA["properties"]["rules"]["items"]["required"])
    assert {"id", "forbid", "reason"} <= status_enum, "схема требует id/forbid/reason у правила"
    for r in rep["rows"]:
        assert r["strength"] == "advisory"
        assert r["closed_by"] in ("validator", "judge", "writer", "human")


# ── вспомогательные ──

def _fresh() -> Path:
    import tempfile
    return Path(tempfile.mkdtemp())


def _child_from_dict(decl) -> Path:
    return _child(_fresh(), decl=decl)
