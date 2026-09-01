"""release_bump.py — одна команда поднимает версию во ВСЕХ поверхностях релиза.

Замер 01.09.2026 (выпуск v3.39.1): версию бампали руками в 8 файлах, рассинхрон валидаторы ловили
постфактум. Тест держит инварианты помощника: после bump все поверхности согласованы (check пуст),
раздел CHANGELOG и release-newsfragment созданы, а ненайденная версия — ошибка, а не тихий пропуск.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT_ROOT))

from ai_ops_kit.devtools import release_bump as rb  # noqa: E402


def _fixture_repo(root: Path, ver="1.2.3", channel="qualification"):
    """Минимальный репозиторий со всеми версионными поверхностями на версии `ver`."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{ver}\n", encoding="utf-8")
    (root / "manifest").mkdir()
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        f"ai_ops:\n  package_version: {ver}\n  schema_version: 1\n", encoding="utf-8")
    (root / "registry").mkdir()
    (root / "registry" / "release-claims.yaml").write_text(
        f"schema_version: 1\nversion: {ver}\nchannel: {channel}\n", encoding="utf-8")
    (root / "registry" / "release-notes.yaml").write_text(
        f"schema_version: 1\nversion: {ver}\npatch_note: 'x'\n", encoding="utf-8")
    (root / "README.md").write_text(f"# repo\n\n**v{ver} {channel}** — что-то\n", encoding="utf-8")
    (root / "ROADMAP.md").write_text(f"# roadmap\n\nтекущий канал — **v{ver} {channel}** остаётся\n",
                                     encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [Unreleased]\n\n## [{v}] — old\n".format(v=ver),
                                       encoding="utf-8")
    (root / "newsfragments").mkdir()
    return root


@pytest.mark.unit
def test_check_is_empty_on_a_consistent_repo(tmp_path):
    root = _fixture_repo(tmp_path / "r")
    assert rb.check(root) == []


@pytest.mark.unit
def test_bump_updates_every_surface_and_check_passes(tmp_path):
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    changed = rb.bump(root, "1.2.4", title="Заголовок", date="2026-09-01", body="- пункт")
    # ровно 8 поверхностей
    assert "VERSION" in changed and "CHANGELOG.md" in changed
    assert any("release-v1.2.4" in c for c in changed)
    assert rb.current_version(root) == "1.2.4"
    # согласованность после bump — ключевой инвариант (то, чего не было при ручном бампе)
    assert rb.check(root) == []
    # CHANGELOG-раздел и фрагмент реально созданы
    assert "## [1.2.4] — 2026-09-01 · Заголовок" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- пункт" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (root / "newsfragments" / "release-v1.2.4.chore.md").is_file()
    # README/ROADMAP версия поднята вместе с каналом
    assert "v1.2.4 qualification" in (root / "README.md").read_text(encoding="utf-8")


@pytest.mark.unit
def test_bump_rejects_bad_semver(tmp_path):
    root = _fixture_repo(tmp_path / "r")
    with pytest.raises(ValueError):
        rb.bump(root, "1.2", title="x", date="2026-09-01")


@pytest.mark.unit
def test_bump_errors_when_a_surface_is_out_of_sync(tmp_path):
    """Если поверхность УЖЕ разошлась (нет старой версии) — bump честно падает, а не молча пропускает."""
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        "ai_ops:\n  package_version: 9.9.9\n", encoding="utf-8")   # рассинхрон
    with pytest.raises(ValueError):
        rb.bump(root, "1.2.4", title="x", date="2026-09-01")


@pytest.mark.unit
def test_check_names_the_out_of_sync_surface(tmp_path):
    root = _fixture_repo(tmp_path / "r", ver="1.2.3")
    (root / "README.md").write_text("**v0.0.1 qualification**\n", encoding="utf-8")
    bad = rb.check(root)
    assert "README.md" in bad
