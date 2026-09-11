"""Реестр артефактов Product Operating Layer как данные (PR-4).

Главный инвариант среза — расхождение реестра с реальностью КРАСНЕЕТ, а не молчит. Способ его
подделать — ослабить проверку так, что реестр разъезжается с моделью контуров или с файлами
шаблонов, а тест остаётся зелёным. Три теста на capability:

  * positive     — реальный реестр читается, проходит инварианты и не расходится (нет major) с
                   шаблонами репозитория; обязательный состав PR-3 на месте;
  * fail-closed  — порча реестра (нет artifacts, битый YAML, дубль id, чужая роль/контур, кривой
                   autonomy, отсутствие версии шаблона) называется ошибкой, а load — исключением;
  * side-effect  — divergence РЕАЛЬНО читает файл шаблона: несовпадение версии в файле и в реестре
                   даёт major-находку, а не читается как «всё в порядке».
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import artifact_registry as AR

REG = AR.load()


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_real_registry_loads_and_is_read_by_code():
    """Реестр читается кодом: артефакты и обязательный состав доступны как данные."""
    ids = AR.artifact_ids(REG)
    assert "product_passport" in ids and "delivery" in ids and "policy" in ids
    # SR-2: roadmap СНЯТ из этого слоя — его канонический дом product-operating-model.yaml (корень).
    assert "roadmap" not in ids, "roadmap не должен дублироваться в слое .ai-ops/ (SR-2)"
    passport = AR.artifact(REG, "product_passport")
    assert passport["owner_role"] == "product"
    assert passport["template"]["version"] == 1
    assert AR.required_artifacts(REG), "у слоя обязан быть обязательный состав (PR-3)"


def test_real_registry_passes_invariants():
    """Инварианты и ссылочная целостность к модели контуров сходятся на реальном реестре."""
    assert AR.check(REG) == []


def test_real_registry_matches_repository():
    """Расхождение реестра с файлами репозитория не содержит major (шаблоны либо есть и совпадают,
    либо честно `template_pending` до работы product-layer-templates-versioned)."""
    findings = AR.divergence(REG)
    assert not AR.has_major(findings), findings


def test_lifecycle_has_four_states_in_order():
    """PR-5: Missing -> Invalid -> Outdated -> Valid — четыре состояния, не два."""
    states = [s["id"] for s in AR.lifecycle_states(REG)]
    assert states == ["missing", "invalid", "outdated", "valid"]


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

def test_load_missing_file_raises(tmp_path):
    with pytest.raises(AR.RegistryCorrupt):
        AR.load(tmp_path / "нет.yaml")


def test_load_malformed_yaml_raises(tmp_path):
    p = tmp_path / "artifact-registry.yaml"
    p.write_text("artifacts: [unterminated\n", encoding="utf-8")
    with pytest.raises(AR.RegistryCorrupt):
        AR.load(p)


def test_load_empty_registry_raises(tmp_path):
    """Пустой реестр — исключение, а НЕ пустой список: иначе слой «не описан» молча."""
    p = tmp_path / "artifact-registry.yaml"
    p.write_text("registry_type: artifact-registry\nartifacts: []\n", encoding="utf-8")
    with pytest.raises(AR.RegistryCorrupt):
        AR.load(p)


def test_check_catches_duplicate_ids():
    reg = {"registry_type": "artifact-registry", "layer_root": ".ai-ops/",
           "autonomy_levels": list(AR.AUTONOMY),
           "lifecycle_states": [{"id": s, "order": i, "means": s} for i, s in enumerate(AR.LIFECYCLE)],
           "artifacts": [
               {"id": "x", "title": "t", "purpose": "p", "required": True, "kind": "document",
                "format": "markdown", "path": ".ai-ops/A.md", "owner_role": "product",
                "source_contour": "product_strategy", "template": {"path": "t.md", "version": 1}},
               {"id": "x", "title": "t", "purpose": "p", "required": False, "kind": "document",
                "format": "markdown", "path": ".ai-ops/B.md", "owner_role": "product",
                "source_contour": "product_strategy", "template": {"path": "t.md", "version": 1}}]}
    assert any("дубли id" in x for x in AR.check(reg))


def test_check_catches_unknown_role_and_contour():
    """Роль/контур, которых нет в модели контуров, — расхождение реестра с реальностью."""
    reg = {"registry_type": "artifact-registry", "layer_root": ".ai-ops/",
           "autonomy_levels": list(AR.AUTONOMY),
           "lifecycle_states": [{"id": s, "order": i, "means": s} for i, s in enumerate(AR.LIFECYCLE)],
           "artifacts": [
               {"id": "x", "title": "t", "purpose": "p", "required": True, "kind": "document",
                "format": "markdown", "path": ".ai-ops/A.md", "owner_role": "no_such_role",
                "source_contour": "no_such_contour", "template": {"path": "t.md", "version": 1}}]}
    errs = AR.check(reg)
    assert any("owner_role" in x for x in errs) and any("source_contour" in x for x in errs)


def test_check_catches_bad_autonomy_and_missing_template():
    reg = {"registry_type": "artifact-registry", "layer_root": ".ai-ops/",
           "autonomy_levels": list(AR.AUTONOMY),
           "lifecycle_states": [{"id": s, "order": i, "means": s} for i, s in enumerate(AR.LIFECYCLE)],
           "artifacts": [
               {"id": "x", "title": "t", "purpose": "p", "required": True, "kind": "document",
                "format": "markdown", "path": ".ai-ops/A.md", "owner_role": "product",
                "source_contour": "product_strategy",
                "ai_actions": [{"action": "update", "autonomy": "yolo"}]}]}
    errs = AR.check(reg)
    assert any("template" in x for x in errs)          # document без версии шаблона
    assert any("autonomy" in x for x in errs)          # неизвестный уровень автономии


def test_check_catches_format_kind_mismatch():
    reg = {"registry_type": "artifact-registry", "layer_root": ".ai-ops/",
           "autonomy_levels": list(AR.AUTONOMY),
           "lifecycle_states": [{"id": s, "order": i, "means": s} for i, s in enumerate(AR.LIFECYCLE)],
           "artifacts": [
               {"id": "x", "title": "t", "purpose": "p", "required": True, "kind": "config",
                "format": "markdown", "path": ".ai-ops/A.yaml", "owner_role": "engineer",
                "source_contour": "engineering_quality_security",
                "template": {"path": "t.yaml", "version": 1}}]}
    assert any("format" in x for x in AR.check(reg))


# ── side-effect ──────────────────────────────────────────────────────────────────────────────────

def test_divergence_reads_template_and_catches_version_mismatch(tmp_path):
    """divergence РЕАЛЬНО открывает файл шаблона: версия в файле != версии в реестре -> major.

    Это доказательство, что проверка расхождения читает репозиторий, а не только реестр: без чтения
    файла несовпадение версий прошло бы как «всё в порядке»."""
    tpl_dir = tmp_path / "templates" / "product-layer"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "P.md").write_text("<!-- template-version: 7 -->\n# паспорт\n", encoding="utf-8")
    reg = {"registry_type": "artifact-registry", "artifacts": [
        {"id": "product_passport", "template": {"path": "templates/product-layer/P.md", "version": 1}}]}
    findings = AR.divergence(reg, tmp_path)
    assert AR.has_major(findings)
    assert findings[0]["id"] == "template_version_mismatch"


def test_divergence_flags_template_without_version(tmp_path):
    tpl_dir = tmp_path / "templates" / "product-layer"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "P.md").write_text("# паспорт без маркера версии\n", encoding="utf-8")
    reg = {"registry_type": "artifact-registry", "artifacts": [
        {"id": "product_passport", "template": {"path": "templates/product-layer/P.md", "version": 1}}]}
    findings = AR.divergence(reg, tmp_path)
    assert any(f["id"] == "template_version_missing" for f in findings)


def test_divergence_matching_version_is_clean(tmp_path):
    tpl_dir = tmp_path / "templates" / "product-layer"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "P.yaml").write_text("template_version: 3\nschema_version: 1\n", encoding="utf-8")
    reg = {"registry_type": "artifact-registry", "artifacts": [
        {"id": "policy", "template": {"path": "templates/product-layer/P.yaml", "version": 3}}]}
    assert AR.divergence(reg, tmp_path) == []


# ── #609: ярусы обязательности, профили, каталог, ai_check ────────────────────────────────────────

def _min_reg_with_tiers(catalog):
    """Минимальный валидный реестр с таксономией ярусов #609 — для fail-closed проверок."""
    return {"registry_type": "artifact-registry", "layer_root": ".ai-ops/",
            "autonomy_levels": list(AR.AUTONOMY),
            "lifecycle_states": [{"id": s, "order": i, "means": s}
                                 for i, s in enumerate(AR.LIFECYCLE)],
            "obligation_tiers": [
                {"id": "tier1", "title": "Base", "applies_when": "always", "means": "всегда"},
                {"id": "tier2", "title": "Prod", "applies_when": "production", "means": "prod"},
                {"id": "tier3", "title": "AI", "applies_when": "ai_native", "means": "ai"}],
            "profiles": {"ai-product": {"includes_tiers": ["tier1", "tier2", "tier3"]},
                         "library": {"includes_tiers": ["tier1"]}},
            "artifacts": [
                {"id": "policy", "title": "t", "purpose": "p", "required": True, "kind": "config",
                 "format": "yaml", "path": ".ai-ops/POLICY.yaml", "owner_role": "engineer",
                 "source_contour": "engineering_quality_security", "ai_check": "x",
                 "template": {"path": "t.yaml", "version": 1}}],
            "standard_catalog": catalog}


# positive: реальный реестр несёт таксономию и она согласована
def test_real_registry_has_three_tiers_and_profiles():
    tiers = [t["id"] for t in AR.obligation_tiers(REG)]
    assert sorted(tiers) == ["tier1", "tier2", "tier3"], "#609: ровно три яруса"
    assert "ai-product" in AR.profiles(REG), "default-профиль объявлен данными"


def test_real_registry_every_required_artifact_declares_ai_check():
    """#609 п.2: у каждого обязательного артефакта объявлено, что проверяет AI-агент."""
    for a in AR.required_artifacts(REG):
        assert (a.get("ai_check") or "").strip(), f"{a['id']} без ai_check"


def test_real_catalog_entries_are_tiered_and_have_ai_check():
    cat = AR.standard_catalog(REG)
    assert cat, "каталог стандарта непуст"
    for c in cat:
        assert c["tier"] in ("tier1", "tier2", "tier3")
        assert (c.get("ai_check") or "").strip(), f"{c['id']} без ai_check"


def test_profile_selects_applicable_tier_set():
    """Профиль ВЫБИРАЕТ набор: ai-product — все три яруса, library — только базовый."""
    assert set(AR.tiers_for_profile(REG, "ai-product")) == {"tier1", "tier2", "tier3"}
    assert AR.tiers_for_profile(REG, "library") == ["tier1"]
    assert AR.tiers_for_profile(REG, "нет-такого") == []          # fail-closed
    lib = AR.catalog_for_profile(REG, "library")
    full = AR.catalog_for_profile(REG, "ai-product")
    assert lib and len(lib) < len(full), "меньший профиль обязан выбирать меньший каталог"
    assert all(c["tier"] == "tier1" for c in lib)


# fail-closed: порча таксономии называется ошибкой
def test_check_catches_required_artifact_without_ai_check():
    reg = _min_reg_with_tiers([{"id": "readme", "name": "README", "tier": "tier1",
                                "path": "README.md", "ai_check": "y"}])
    reg["artifacts"][0].pop("ai_check")
    assert any("ai_check" in x for x in AR.check(reg))


def test_check_catches_unknown_tier_in_catalog():
    reg = _min_reg_with_tiers([{"id": "x", "name": "X", "tier": "tier9",
                                "path": "X.md", "ai_check": "y"}])
    assert any("tier" in x and "x" in x for x in AR.check(reg))


def test_check_catches_bad_applies_when():
    reg = _min_reg_with_tiers([{"id": "readme", "name": "README", "tier": "tier1",
                                "path": "README.md", "ai_check": "y"}])
    reg["obligation_tiers"][0]["applies_when"] = "whenever"
    assert any("applies_when" in x for x in AR.check(reg))


def test_check_catches_profile_referencing_unknown_tier():
    reg = _min_reg_with_tiers([{"id": "readme", "name": "README", "tier": "tier1",
                                "path": "README.md", "ai_check": "y"}])
    reg["profiles"]["library"]["includes_tiers"] = ["tier1", "tierX"]
    assert any("неизвестный ярус" in x for x in AR.check(reg))


def test_check_catches_catalog_without_ai_check():
    reg = _min_reg_with_tiers([{"id": "readme", "name": "README", "tier": "tier1",
                                "path": "README.md"}])
    assert any("ai_check" in x for x in AR.check(reg))


def test_check_catches_missing_or_multiple_locators():
    dup = _min_reg_with_tiers([{"id": "x", "name": "X", "tier": "tier1",
                                "path": "X.md", "ref": "policy", "ai_check": "y"}])
    assert any("локатор" in x for x in AR.check(dup))
    none = _min_reg_with_tiers([{"id": "x", "name": "X", "tier": "tier1", "ai_check": "y"}])
    assert any("локатор" in x for x in AR.check(none))


def test_check_catches_dangling_ref_and_contour():
    bad_ref = _min_reg_with_tiers([{"id": "x", "name": "X", "tier": "tier1",
                                    "ref": "no_such_artifact", "ai_check": "y"}])
    assert any("ref" in x for x in AR.check(bad_ref))
    bad_contour = _min_reg_with_tiers([{"id": "x", "name": "X", "tier": "tier1",
                                        "contour": "no_such_contour", "ai_check": "y"}])
    assert any("contour" in x for x in AR.check(bad_contour))
