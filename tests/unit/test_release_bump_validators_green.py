"""release_bump.py — после бампа ОБА релизных валидатора зелены (не только `check` помощника).

Замер 01.09.2026 (выпуск v3.39.1): рассинхрон версий валидаторы ловили ПОСТФАКТУМ. Критерий работы
`release-helper-bumps-all-version-surfaces` требует прямо: после команды «версии совпадают во всех
точках И ОБА ВАЛИДАТОРА ЗЕЛЕНЫ» (validate_release_claims, validate_ai_first_registry). Соседний
test_release_bump.py держит первую половину (`rb.check(root) == []`); здесь — вторая, которой там
не было: выход помощника сверяется НЕ его собственной проверкой, а РЕАЛЬНЫМИ правилами обоих
валидаторов, чтобы «зелёное по мнению помощника» не разошлось с «зелёным по мнению валидатора».

Валидаторы читают весь репозиторий (числа агентов/гейтов и т.п.), поэтому целиком на синтетической
фикстуре их не гонишь — здесь берутся ИМЕННО версионные правила каждого:
  * release_claims: `authoritative_version_errors` — публичная поверхность (README/ROADMAP) объявляет
    текущую версию по образцу из release-claims, и она обязана совпасть с VERSION;
  * ai_first_registry: инвариант `manifest.ai_ops.package_version == VERSION` (check_manifest,
    правило «манифест не расходится с файлом VERSION»).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

KIT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT_ROOT))

from ai_ops_kit.devtools import release_bump as rb  # noqa: E402
from ai_ops_kit.validation import validate_release_claims as vrc  # noqa: E402


def _fixture_repo(root: Path, ver="1.2.3", channel="qualification"):
    """Репозиторий со всеми версионными поверхностями И полями, которые читают оба валидатора."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{ver}\n", encoding="utf-8")
    (root / "manifest").mkdir()
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        f"ai_ops:\n  package_version: {ver}\n  schema_version: 1\n", encoding="utf-8")
    (root / "registry").mkdir()
    # authoritative_version — то, по чему release_claims сверяет публичную поверхность с VERSION.
    (root / "registry" / "release-claims.yaml").write_text(
        "schema_version: 1\n"
        f"version: {ver}\n"
        f"channel: {channel}\n"
        "authoritative_version:\n"
        "  - {file: README.md,  pattern: '\\*\\*v(\\d+\\.\\d+\\.\\d+) {channel}\\*\\*'}\n"
        "  - {file: ROADMAP.md, pattern: 'текущий канал — \\*\\*v(\\d+\\.\\d+\\.\\d+) {channel}\\*\\*'}\n",
        encoding="utf-8")
    (root / "registry" / "release-notes.yaml").write_text(
        f"schema_version: 1\nversion: {ver}\npatch_note: 'x'\n", encoding="utf-8")
    (root / "README.md").write_text(f"# repo\n\n**v{ver} {channel}** — что-то\n", encoding="utf-8")
    (root / "ROADMAP.md").write_text(
        f"# roadmap\n\nтекущий канал — **v{ver} {channel}** остаётся\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# CHANGELOG\n\n## [Unreleased]\n\n## [{v}] — old\n".format(v=ver), encoding="utf-8")
    (root / "newsfragments").mkdir()
    return root


def _release_claims(root: Path) -> dict:
    return yaml.safe_load((root / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


@pytest.mark.unit
def test_release_claims_authoritative_version_green_after_bump(tmp_path):
    """release_claims: после бампа README/ROADMAP объявляют новую версию — версионных ошибок нет."""
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    # до бампа поверхность на старой версии, но VERSION тоже — согласовано, ошибок нет
    assert vrc.authoritative_version_errors(_release_claims(root), pkg=root) == []
    rb.bump(root, "1.2.4", title="Заголовок", date="2026-09-01", body="- пункт")
    # после бампа VERSION=1.2.4, и публичная поверхность обязана объявлять ровно её
    assert vrc.authoritative_version_errors(_release_claims(root), pkg=root) == []


@pytest.mark.unit
def test_release_claims_catches_surface_left_behind(tmp_path):
    """Контроль остроты: если поверхность НЕ поднять, тот же валидатор краснеет — проверка не слепа."""
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    (root / "VERSION").write_text("1.2.4\n", encoding="utf-8")  # VERSION ушёл, README отстал
    errs = vrc.authoritative_version_errors(_release_claims(root), pkg=root)
    assert any("README.md" in e for e in errs)


@pytest.mark.unit
def test_manifest_matches_version_after_bump(tmp_path):
    """ai_first_registry-инвариант: manifest.package_version == VERSION держится после бампа."""
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    rb.bump(root, "1.2.4", title="x", date="2026-09-01")
    manifest = yaml.safe_load((root / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert str(manifest["ai_ops"]["package_version"]) == version == "1.2.4"
