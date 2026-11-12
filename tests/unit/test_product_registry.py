"""Product Registry — реестр нескольких продуктов и сводный флит-вид (Product Contract, срез 2).

Инвариант: реестр НЕ считает состояние сам — он перечисляет продукты и для каждого зовёт
`product_contract.validate`; ошибка одного продукта становится его строкой `status=error`, а не
падением всего флота (иначе один битый путь скрывал бы состояние остальных девяти).

  * форма       — validate_registry ловит пустой список, дубли id, отсутствие path;
  * агрегация    — вердикт продукта во флоте == product_contract.validate того же пути;
  * fail-soft    — несуществующий каталог продукта -> строка error, остальные посчитаны;
  * health       — впрыснутый сверху health доезжает до строки продукта.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import product_contract, product_registry

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_preg", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bootstrapped(installer, root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Демо\n\nсервис.\n", encoding="utf-8")
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    installer._child_scaffolding()._seed_product_layer(root)
    return root


def _registry_file(tmp_path, products):
    f = tmp_path / "products.yaml"
    f.write_text(yaml.safe_dump({"schema_version": 1, "kind": "product-registry",
                                 "products": products}, allow_unicode=True), encoding="utf-8")
    return f


# ── форма ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validate_registry_catches_shape():
    assert product_registry.validate_registry({}) == ["реестр продуктов не объект"] or \
        product_registry.validate_registry({"schema_version": 1, "kind": "product-registry",
                                            "products": []})
    dup = {"schema_version": 1, "kind": "product-registry",
           "products": [{"id": "a", "path": "/x"}, {"id": "a", "path": "/y"}]}
    assert any("дубликат id" in e for e in product_registry.validate_registry(dup))
    nopath = {"schema_version": 1, "kind": "product-registry", "products": [{"id": "a"}]}
    assert any("нет path" in e for e in product_registry.validate_registry(nopath))


@pytest.mark.unit
def test_valid_registry_has_no_errors(tmp_path):
    good = {"schema_version": 1, "kind": "product-registry",
            "products": [{"id": "a", "name": "A", "path": str(tmp_path)}]}
    assert product_registry.validate_registry(good) == []


# ── агрегация + fail-soft ────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_fleet_aggregates_per_product_verdict(installer, tmp_path):
    p_valid = _bootstrapped(installer, tmp_path / "valid_prod")
    p_empty = tmp_path / "empty_prod"
    p_empty.mkdir()
    reg = _registry_file(tmp_path, [
        {"id": "v", "name": "Valid", "path": str(p_valid)},
        {"id": "e", "name": "Empty", "path": str(p_empty)},
        {"id": "ghost", "name": "Ghost", "path": str(tmp_path / "does_not_exist")},
    ])
    rep = product_registry.fleet(reg)
    assert rep["kind"] == "product-fleet"
    rows = {r["id"]: r for r in rep["products"]}
    # вердикт во флоте совпадает с прямым product_contract.validate — реестр не вторая правда
    assert rows["v"]["verdict"] == product_contract.validate(p_valid)["verdict"]
    assert rows["e"]["verdict"] == product_contract.validate(p_empty)["verdict"]
    # несуществующий продукт -> error, но остальные ПОСЧИТАНЫ
    assert rows["ghost"]["status"] == "error"
    assert rows["v"]["status"] == "ok" and rows["e"]["status"] == "ok"


@pytest.mark.unit
def test_broken_product_does_not_sink_the_fleet(tmp_path):
    reg = _registry_file(tmp_path, [{"id": "ghost", "name": "G", "path": "/nope/nowhere"}])
    rep = product_registry.fleet(reg)  # не должно бросить
    assert rep["products"][0]["status"] == "error"
    assert "counts" in rep


# ── health впрыскивается сверху ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_injected_health_reaches_the_row(installer, tmp_path):
    p = _bootstrapped(installer, tmp_path / "prod")
    reg = _registry_file(tmp_path, [{"id": "p", "name": "P", "path": str(p)}])
    rep = product_registry.fleet(reg, health_map={"p": {"band": "red", "reasons": ["прод горит"]}})
    row = rep["products"][0]
    assert row["health_band"] == "red"
    assert row["verdict"] == "not_ready"  # красное здоровье роняет вердикт даже при валидной форме


# ── register: создать/добавить/обновить (upsert) ─────────────────────────────────────────────────

@pytest.mark.unit
def test_register_creates_registry_and_adds_product(installer, tmp_path):
    prod = _bootstrapped(installer, tmp_path / "niti")
    reg = tmp_path / "products.yaml"
    res = product_registry.register(reg, prod)
    assert res["status"] == "created"
    assert res["product"]["id"] == "niti"
    assert reg.is_file()
    # записанное читается обратно валидным реестром
    data = product_registry.load(reg)
    assert product_registry.validate_registry(data) == []
    assert any(p["id"] == "niti" for p in data["products"])


@pytest.mark.unit
def test_register_is_upsert_by_id(installer, tmp_path):
    prod1 = _bootstrapped(installer, tmp_path / "niti")
    reg = tmp_path / "products.yaml"
    product_registry.register(reg, prod1)
    # тот же id, другой путь -> updated, дубля не появляется
    prod2 = _bootstrapped(installer, tmp_path / "niti_moved")
    res = product_registry.register(reg, prod2, pid="niti", name="Niti")
    assert res["status"] == "updated"
    data = product_registry.load(reg)
    niti = [p for p in data["products"] if p["id"] == "niti"]
    assert len(niti) == 1 and niti[0]["path"] == str(prod2)


@pytest.mark.unit
def test_register_writes_managed_header(installer, tmp_path):
    prod = _bootstrapped(installer, tmp_path / "niti")
    reg = tmp_path / "products.yaml"
    product_registry.register(reg, prod)
    assert "Управляется командой `ai-ops products register`" in reg.read_text(encoding="utf-8")


# ── inspect: карточка одного по id ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_inspect_returns_contract_for_known_id(installer, tmp_path):
    prod = _bootstrapped(installer, tmp_path / "niti")
    reg = _registry_file(tmp_path, [{"id": "niti", "name": "Niti", "path": str(prod)}])
    res = product_registry.inspect(reg, "niti")
    assert res["status"] == "ok"
    assert res["contract"]["kind"] == "product-contract"
    assert res["verdict"]["verdict"] == product_contract.validate(prod)["verdict"]


@pytest.mark.unit
def test_inspect_unknown_id_names_the_known(tmp_path):
    reg = _registry_file(tmp_path, [{"id": "a", "name": "A", "path": str(tmp_path)}])
    res = product_registry.inspect(reg, "ghost")
    assert res["status"] == "not_found"
    assert res["known"] == ["a"]


@pytest.mark.unit
def test_product_path_and_inspect_injects_health_and_risks(installer, tmp_path):
    prod = _bootstrapped(installer, tmp_path / "niti")
    reg = _registry_file(tmp_path, [{"id": "niti", "name": "Niti", "path": str(prod)}])
    assert product_registry.product_path(reg, "niti") == prod
    assert product_registry.product_path(reg, "ghost") is None
    res = product_registry.inspect(reg, "niti", health={"band": "red", "reasons": ["горит"]},
                                   risks={"count_by_severity": {"high": 2, "medium": 0}})
    assert res["contract"]["health"]["band"] == "red"
    assert res["contract"]["risks"]["count_by_severity"]["high"] == 2
    assert res["verdict"]["verdict"] == "not_ready"  # красное здоровье роняет вердикт


def test_fleet_shows_version_observed_workflows_and_owner_overrides(tmp_path):
    import hashlib
    import json

    root = tmp_path / "product"
    managed = root / ".ai/managed"
    managed.mkdir(parents=True)
    (root / ".ai-ops.yaml").write_text("parent: {installed_version: 4.13.1, update_policy: pr}\n")
    version = managed / "VERSION"
    version.write_text("4.13.1\n")
    (managed / ".checksums.json").write_text(json.dumps({"schema_version": 1, "algorithm": "sha256",
        "managed_root": "managed", "files": {"VERSION": hashlib.sha256(version.read_bytes()).hexdigest()}}))
    (managed / ".provenance.json").write_text(json.dumps({"schema_version": 1, "package": "ai-first-system",
        "installed_version": "4.13.1", "managed_root": ".ai/managed", "checksums_file": ".checksums.json"}))
    custom = root / ".ai/custom"
    custom.mkdir()
    (custom / "owner.md").write_text("owner rules")
    for name, workflow, provider, calls in (("real", "ENGINEERING", "openai", 2),
                                           ("preview", "PRODUCT", "openai", 0),
                                           ("mock", "QUICK", "mock", 1)):
        path = root / "features" / name / "run-report.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 1, "kind": "execution-pipeline", "provider": provider,
                                    "base_workflow": workflow, "cost": {"calls": calls}}))
    broken = root / "features/broken/run-report.json"
    broken.parent.mkdir()
    broken.write_text(json.dumps({"schema_version": 9, "kind": "execution-pipeline", "provider": False,
                                  "base_workflow": "made_up", "cost": {"calls": 1}}))
    registry = _registry_file(tmp_path, [{"id": "product", "path": str(root)}])
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    row = product_registry.fleet(registry)["products"][0]["kit"]
    assert row["installed_version"] == "4.13.1"
    assert row["drift"] == {"managed": "clean", "owner_overrides": "observed", "override_root": ".ai/custom"}
    assert row["capabilities_used"]["workflows"] == ["ENGINEERING"]
    assert row["capabilities_used"]["invalid_reports"] == 1
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    version.write_text("4.13.0\n")
    assert before[version] != version.read_bytes()
    row = product_registry.fleet(registry)["products"][0]["kit"]
    assert row["version_state"] == "conflict" and row["installed_version"] is None
    assert row["drift"]["managed"] == "unknown"  # provenance расходится, нельзя заявить полноту проверки
    version.write_text("4.13.1\n")
    (managed / "extra.txt").write_text("unexpected managed file")
    assert product_registry.kit_state(root)["drift"]["managed"] == "detected"
