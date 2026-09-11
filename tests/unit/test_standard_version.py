"""SR-1..4: стандарт репозитория как версионируемый объект, отдельный от версии пакета."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from ai_ops_kit.planning import repo_audit as RA
from ai_ops_kit.planning import standard as S

KIT = Path(__file__).resolve().parents[2]


def _load_installer():
    spec = importlib.util.spec_from_file_location("installer_ai_ops_std_under_test",
                                                  KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── SR-1: версия + отпечаток-ратчет ──

def test_fingerprint_in_sync_with_declared():
    """Отпечаток состава требований совпадает с объявленным — иначе состав правили без bump версии."""
    declared = S.load()["requirements_fingerprint"]
    assert S.compute_fingerprint() == declared, (
        "состав требований изменился, а requirements_fingerprint/standard_version — нет; "
        "поднимите standard_version и обновите отпечаток (ратчет SR-1)")


def test_standard_version_is_int_and_separate_from_package():
    assert isinstance(S.current_version(), int) and S.current_version() >= 1
    pkg_ver = (KIT / "VERSION").read_text(encoding="utf-8").strip()
    assert str(S.current_version()) != pkg_ver, "версия стандарта не должна совпадать с версией пакета"


def test_fingerprint_changes_when_requirements_change(tmp_path):
    """Добавление обязательной секции меняет отпечаток (чувствительность ратчета)."""
    (tmp_path / "registry").mkdir()
    (tmp_path / "manifest").mkdir()
    (tmp_path / "quality").mkdir()
    pom = {"contours": [{"id": "c", "source_of_truth": [
        {"path": "A.md", "required": True, "required_sections": ["Context"]}]}]}
    (tmp_path / "registry" / "product-operating-model.yaml").write_text(
        yaml.safe_dump(pom), encoding="utf-8")
    fp1 = S.compute_fingerprint(tmp_path)
    pom["contours"][0]["source_of_truth"][0]["required_sections"].append("Failure Modes")
    (tmp_path / "registry" / "product-operating-model.yaml").write_text(
        yaml.safe_dump(pom), encoding="utf-8")
    fp2 = S.compute_fingerprint(tmp_path)
    assert fp1 != fp2, "новая обязательная секция обязана менять отпечаток (SR-1)"


# ── SR-2: манифест ссылается на существующие реестры ──

def test_standard_manifest_references_existing_sources():
    std = S.load()
    assert std.get("sources"), "манифест стандарта обязан ССЫЛАТЬСЯ на реестры состава (SR-2)"
    rs = S.requirement_set()
    assert rs["required_artifacts"] and rs["required_sections"], \
        "состав требований читается из реестров и непуст (SR-2)"


# ── #609: ярусный каталог — часть версионируемой поверхности стандарта ──

def test_standard_catalog_feeds_requirement_surface():
    """Каталог стандарта по ярусам входит в состав требований (SR-1/SR-2, #609)."""
    rs = S.requirement_set()
    assert any(a.startswith("tier:") for a in rs["required_artifacts"]), \
        "ярусные артефакты каталога обязаны попадать в поверхность требований (#609)"


def test_catalog_change_moves_fingerprint(tmp_path):
    """Смена состава каталога/ярусов меняет отпечаток — ратчет чувствует новый обязательный артефакт."""
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "standard.yaml").write_text(
        "default_profile: ai-product\n", encoding="utf-8")
    ar = {"registry_type": "artifact-registry",
          "profiles": {"ai-product": {"includes_tiers": ["tier1"]}},
          "standard_catalog": [{"id": "readme", "tier": "tier1", "path": "README.md",
                                "ai_check": "x"}]}
    (tmp_path / "registry" / "artifact-registry.yaml").write_text(
        yaml.safe_dump(ar), encoding="utf-8")
    fp1 = S.compute_fingerprint(tmp_path)
    ar["standard_catalog"].append({"id": "security", "tier": "tier1", "path": "SECURITY.md",
                                   "ai_check": "y"})
    (tmp_path / "registry" / "artifact-registry.yaml").write_text(
        yaml.safe_dump(ar), encoding="utf-8")
    assert fp1 != S.compute_fingerprint(tmp_path), "новый ярусный артефакт обязан менять отпечаток"


# ── SR-3: update_channel влияет на поведение ──

def test_update_channel_is_meaningful():
    mod = _load_installer()
    # неизвестный канал → ref не выдаётся (значение канала влияет на результат — поле не мёртвое)
    res = mod.resolve_update_ref("не-канал")
    assert res["ref"] is None and res["kind"] is None, \
        "значение update_channel обязано влиять на выбор ревизии (SR-3)"
    assert "не-канал" in res["channel"]


# ── SR-4: дочка объявляет версию, status отвечает ──

def test_package_standard_version_reads_registry():
    mod = _load_installer()
    assert mod.package_standard_version() == S.current_version()


def test_child_standard_version_reads_config():
    mod = _load_installer()
    assert mod.child_standard_version({"standard": {"version": 3}}) == 3
    assert mod.child_standard_version({}) is None


def test_status_diff_installed_vs_available():
    avail = S.current_version()
    assert S.status(avail)["changed"] is False
    beh = S.status(avail - 1)
    assert beh["behind"] is True and beh["changed"] is True
    assert S.status(None)["installed"] is None


def test_example_config_declares_standard_and_init_substitutes(tmp_path):
    import re
    mod = _load_installer()
    text = (KIT / "examples" / "child-config.example.yaml").read_text(encoding="utf-8")
    assert re.search(r"^standard:", text, re.M), "заготовка конфига обязана объявлять standard (SR-4)"
    sv = mod.package_standard_version()
    # `.*` после `standard:` — строка блока несёт инлайн-комментарий (`standard:   # SR-4 …`); без
    # него подстановка молча не срабатывала и маскировалась, пока версия примера совпадала с текущей.
    out = re.sub(r"(^standard:.*\n(?:.*\n)*?\s*version:\s*)\S+", rf"\g<1>{sv}", text, count=1, flags=re.M)
    cfg = yaml.safe_load(out)
    assert cfg["standard"]["version"] == sv, "init обязан подставить версию стандарта пакета"


def test_audit_reports_standard_version_and_sync(tmp_path):
    rep = RA.audit(KIT)
    assert rep["standard"]["version"] == S.current_version()
    assert rep["standard"]["fingerprint_in_sync"] is True
