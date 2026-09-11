"""SEC-001: SECURITY.md — обязательный артефакт репозитория с сидингом и doctor-проверкой (#826).

Держим: манифест объявляет SECURITY.md обязательным и даёт шаблон; шаблон едет; кит догфудит
(корневой SECURITY.md заполнен, не черновик); сидинг кладёт черновик в чистый репозиторий; версия
стандарта учла новый обязательный артефакт (отпечаток в синхроне).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "installer_ai_ops_security_under_test", KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_ships():
    assert (KIT / "templates" / "system" / "SECURITY.md").is_file(), \
        "шаблон SECURITY.md обязан ехать (SEC-001)"


def test_manifest_declares_security_required_with_template():
    m = yaml.safe_load((KIT / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))
    pom = m["session_orchestration"]["product_operating_model"]
    assert "SECURITY.md" in pom["required_repo_artifacts"], "SECURITY.md должен быть обязательным артефактом"
    assert pom["templates"].get("security", "").endswith("system/SECURITY.md"), "нет шаблона security"


def test_kit_dogfoods_a_real_security_md():
    """Кит удовлетворяет собственное правило: корневой SECURITY.md есть и НЕ черновик."""
    p = KIT / "SECURITY.md"
    assert p.is_file(), "у самого кита нет корневого SECURITY.md — правило не догфудится"
    text = p.read_text(encoding="utf-8")
    assert "template: true" not in text, "SECURITY.md кита — черновик-шаблон, а должен быть заполнен"
    assert "status: draft" not in text, "SECURITY.md кита помечен draft — own-medicine краснеет"


def test_seeding_creates_draft_in_clean_repo(tmp_path):
    """Сидинг обязательных артефактов кладёт черновик SECURITY.md в чистый репозиторий."""
    mod = _load_installer()
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    mod._child_scaffolding()._seed_planning_contour(tmp_path)
    seeded = tmp_path / "SECURITY.md"
    assert seeded.is_file(), "сидинг не создал SECURITY.md из шаблона"
    assert "status: draft" in seeded.read_text(encoding="utf-8"), "сиженный SECURITY.md не помечен draft"


def test_seeding_is_idempotent_and_nondestructive(tmp_path):
    """Сидинг не затирает уже существующий SECURITY.md."""
    mod = _load_installer()
    (tmp_path / "SECURITY.md").write_text("# моя политика\nконтакт\n", encoding="utf-8")
    mod._child_scaffolding()._seed_planning_contour(tmp_path)
    assert (tmp_path / "SECURITY.md").read_text(encoding="utf-8") == "# моя политика\nконтакт\n", \
        "сидинг затёр существующий SECURITY.md"


def test_seeding_skips_draft_when_policy_lives_in_docs_security(tmp_path):
    """Дочка держит реальную политику в docs/security/security-policy.md — сидинг НЕ кладёт корневой
    черновик SECURITY.md и честно называет найденное (existing-at:), не переносит сам (ии-среда)."""
    mod = _load_installer()
    pol = tmp_path / "docs" / "security" / "security-policy.md"
    pol.parent.mkdir(parents=True)
    pol.write_text("# Политика безопасности\n\nКанал приёма: security@пример. " + ("текст. " * 30),
                   encoding="utf-8")
    out = mod._child_scaffolding()._seed_planning_contour(tmp_path)
    assert not (tmp_path / "SECURITY.md").exists(), \
        "сидинг засеял конкурирующий пустой SECURITY.md поверх реальной политики в docs/security/"
    sec = next(x for x in out if x["artifact"] == "SECURITY.md")
    assert sec["action"] == "existing-at:docs/security/security-policy.md", sec


def test_kit_draft_is_not_treated_as_existing_security(tmp_path):
    """Прежний кит-черновик SECURITY.md в docs/security/ НЕ считается существующим — иначе фикс
    замаскировал бы реально невыполненное требование."""
    mod = _load_installer()
    stub = tmp_path / "docs" / "security" / "SECURITY.md"
    stub.parent.mkdir(parents=True)
    stub.write_text("---\nstatus: draft\n---\n\n> **Это заготовка.**\n", encoding="utf-8")
    out = mod._child_scaffolding()._seed_planning_contour(tmp_path)
    sec = next(x for x in out if x["artifact"] == "SECURITY.md")
    assert sec["action"] == "created-draft", \
        f"кит-черновик в docs/security/ ошибочно принят за существующий: {sec}"


def test_standard_version_reflects_new_required_artifact():
    """Отпечаток стандарта в синхроне после добавления обязательного артефакта (ратчет SR-1)."""
    from ai_ops_kit.planning import standard as S
    assert S.compute_fingerprint() == S.load()["requirements_fingerprint"], \
        "новый обязательный артефакт изменил состав — поднимите standard_version и отпечаток"
    assert S.current_version() >= 6, "standard_version должен вырасти после добавления SECURITY.md"
