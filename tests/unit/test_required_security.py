"""SEC-001/SEC-008: безопасность — ДВА обязательных артефакта репозитория (v7).

Решение владельца: безопасность разведена на два документа. `SECURITY.md` (корень) описывает
АРХИТЕКТУРУ безопасности (модель угроз, вход, права, классификация, защиты AI — SEC-008); внешний
путь раскрытия уязвимостей переехал в `security/security-policy.md` (SEC-001). Оба обязательны у всех
дочек. Держим: манифест объявляет оба и даёт шаблоны; шаблоны едут; кит догфудит (оба заполнены, не
черновики); сидинг кладёт черновики в чистый репозиторий; версия стандарта учла новый состав.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]

REQUIRED_SECURITY = ("SECURITY.md", "security/security-policy.md")


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "installer_ai_ops_security_under_test", KIT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_templates_ship():
    assert (KIT / "templates" / "system" / "SECURITY.md").is_file(), \
        "шаблон SECURITY.md (архитектура безопасности) обязан ехать (SEC-008)"
    assert (KIT / "templates" / "system" / "security-policy.md").is_file(), \
        "шаблон security-policy.md (политика раскрытия) обязан ехать (SEC-001)"


def test_manifest_declares_both_security_artifacts_with_templates():
    m = yaml.safe_load((KIT / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))
    pom = m["session_orchestration"]["product_operating_model"]
    for rel in REQUIRED_SECURITY:
        assert rel in pom["required_repo_artifacts"], f"{rel} должен быть обязательным артефактом"
    assert pom["templates"].get("security", "").endswith("system/SECURITY.md"), "нет шаблона security"
    assert pom["templates"].get("security_policy", "").endswith("system/security-policy.md"), \
        "нет шаблона security_policy"


def test_security_md_template_is_architecture_not_policy():
    """Корневой SECURITY.md — про АРХИТЕКТУРУ безопасности (модель угроз), а не про путь раскрытия."""
    text = (KIT / "templates" / "system" / "SECURITY.md").read_text(encoding="utf-8")
    assert "Модель угроз" in text, "шаблон SECURITY.md должен нести раздел модели угроз (SEC-008)"
    assert "security/security-policy.md" in text, "SECURITY.md должен ссылаться на политику раскрытия"


def test_kit_dogfoods_both_filled():
    """Кит удовлетворяет собственное правило: оба security-артефакта есть и НЕ черновики."""
    for rel in REQUIRED_SECURITY:
        p = KIT / rel
        assert p.is_file(), f"у самого кита нет {rel} — правило не догфудится"
        text = p.read_text(encoding="utf-8")
        assert "template: true" not in text, f"{rel} кита — черновик-шаблон, а должен быть заполнен"
        assert "status: draft" not in text, f"{rel} кита помечен draft — own-medicine краснеет"
        assert "Это заготовка" not in text, f"{rel} кита остался заготовкой"


def test_seeding_creates_both_drafts_in_clean_repo(tmp_path):
    """Сидинг обязательных артефактов кладёт черновики обоих security-файлов в чистый репозиторий."""
    mod = _load_installer()
    mod._child_scaffolding()._seed_planning_contour(tmp_path)
    for rel in REQUIRED_SECURITY:
        seeded = tmp_path / rel
        assert seeded.is_file(), f"сидинг не создал {rel} из шаблона"
        assert "status: draft" in seeded.read_text(encoding="utf-8"), f"сиженный {rel} не помечен draft"


def test_seeding_is_idempotent_and_nondestructive(tmp_path):
    """Сидинг не затирает уже существующие security-файлы."""
    mod = _load_installer()
    (tmp_path / "SECURITY.md").write_text("# моя архитектура\nграницы\n", encoding="utf-8")
    (tmp_path / "security").mkdir()
    (tmp_path / "security" / "security-policy.md").write_text("# моя политика\nконтакт\n", encoding="utf-8")
    mod._child_scaffolding()._seed_planning_contour(tmp_path)
    assert (tmp_path / "SECURITY.md").read_text(encoding="utf-8") == "# моя архитектура\nграницы\n", \
        "сидинг затёр существующий SECURITY.md"
    assert (tmp_path / "security" / "security-policy.md").read_text(encoding="utf-8") == \
        "# моя политика\nконтакт\n", "сидинг затёр существующий security-policy.md"


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
    """Отпечаток стандарта в синхроне после разведения безопасности на два артефакта (ратчет SR-1)."""
    from ai_ops_kit.planning import standard as S
    assert S.compute_fingerprint() == S.load()["requirements_fingerprint"], \
        "состав требований изменился — поднимите standard_version и отпечаток"
    assert S.current_version() >= 7, "standard_version должен вырасти после разведения безопасности"
