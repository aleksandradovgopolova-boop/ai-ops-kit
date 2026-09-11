"""Unit tests for tools/changelog_gen.py — CHANGELOG automation."""
from __future__ import annotations

import pytest

from ai_ops_kit.devtools import changelog_gen


@pytest.mark.unit
class TestCategorize:
    """Tests for _categorize(): extract category and description from commit subject."""

    def test_categorize_fix(self):
        """'fix(module): desc' → ('fix', 'desc')."""
        cat, desc = changelog_gen._categorize("fix(module): fix a bug")
        assert cat == "fix"
        assert desc == "fix a bug"

    def test_categorize_feat(self):
        """'feat: add feature' → ('feat', 'add feature')."""
        cat, desc = changelog_gen._categorize("feat: add feature")
        assert cat == "feat"
        assert desc == "add feature"

    def test_categorize_unknown(self):
        """'random message' → ('other', 'random message')."""
        cat, desc = changelog_gen._categorize("random message")
        assert cat == "other"
        assert desc == "random message"


@pytest.mark.unit
class TestValidate:
    """Tests for validate(): check CHANGELOG has entry for current VERSION."""

    def test_validate_returns_dict(self):
        """validate() returns dict with ok, version, found."""
        result = changelog_gen.validate()
        assert isinstance(result, dict)
        assert "ok" in result
        assert "version" in result
        assert "found" in result

    def test_validate_current_version_ok(self):
        """validate() result is consistent with VERSION file and CHANGELOG content."""
        result = changelog_gen.validate()
        version = changelog_gen.VERSION_PATH.read_text(encoding="utf-8").strip()
        assert result["version"] == version
        # ok and found must agree
        assert result["ok"] == result["found"]

    def test_validate_missing_version(self, tmp_path):
        """Fake CHANGELOG without version → ok=False."""
        fake_changelog = tmp_path / "CHANGELOG.md"
        fake_changelog.write_text("# CHANGELOG\n\n## [1.0.0] — 2025-01-01\n\nOld.\n")
        fake_version = tmp_path / "VERSION"
        fake_version.write_text("2.0.0\n")

        orig_cl = changelog_gen.CHANGELOG_PATH
        orig_v = changelog_gen.VERSION_PATH
        changelog_gen.CHANGELOG_PATH = fake_changelog
        changelog_gen.VERSION_PATH = fake_version
        try:
            r = changelog_gen.validate()
            assert r["ok"] is False
            assert r["found"] is False
        finally:
            changelog_gen.CHANGELOG_PATH = orig_cl
            changelog_gen.VERSION_PATH = orig_v

    def test_validate_present_version(self, tmp_path):
        """Fake CHANGELOG with version → ok=True."""
        fake_changelog = tmp_path / "CHANGELOG.md"
        fake_changelog.write_text("# CHANGELOG\n\n## [2.0.0] — 2026-01-01\n\nCurrent.\n")
        fake_version = tmp_path / "VERSION"
        fake_version.write_text("2.0.0\n")

        orig_cl = changelog_gen.CHANGELOG_PATH
        orig_v = changelog_gen.VERSION_PATH
        changelog_gen.CHANGELOG_PATH = fake_changelog
        changelog_gen.VERSION_PATH = fake_version
        try:
            r = changelog_gen.validate()
            assert r["ok"] is True
            assert r["found"] is True
        finally:
            changelog_gen.CHANGELOG_PATH = orig_cl
            changelog_gen.VERSION_PATH = orig_v


@pytest.mark.unit
class TestGenerate:
    """Tests for generate(): produce changelog draft from git commits."""

    def test_generate_empty_commits(self):
        """generate with HEAD..HEAD returns string with version."""
        result = changelog_gen.generate(from_ref="HEAD", to_ref="HEAD")
        assert isinstance(result, str)
        version = changelog_gen.VERSION_PATH.read_text(encoding="utf-8").strip()
        assert version in result

    def test_generate_has_version_header(self):
        """Output starts with '## ['."""
        result = changelog_gen.generate(from_ref="HEAD", to_ref="HEAD")
        assert result.startswith("## [")


@pytest.mark.unit
class TestHeadlinesBetween:
    """headlines_between(): срез заголовков CHANGELOG между версиями — носитель «что нового» в отчёт."""

    SAMPLE = (
        "# CHANGELOG\n\n## [Unreleased]\n\n"
        "## [4.1.0] — 2026-09-11 · Архитектурная конституция\n\nТело 4.1.0.\n"
        "## [4.0.0] — 2026-09-04 · снятие плоского слоя tools/ (BREAKING)\n\nТело 4.0.0.\n"
        "## [3.40.0] — 2026-09-03 · warn-минор перед 4.0\n\nТело 3.40.0.\n"
        "## [3.39.4] — 2026-09-01 · resume-субпарсер движка\n\nТело 3.39.4.\n"
    )

    def test_slice_between_two_versions_names_headlines(self):
        """old (исключая) -> new (включая): называет ровно заголовки промежуточных версий."""
        out = changelog_gen.headlines_between("3.39.4", "4.1.0", text=self.SAMPLE)
        assert out == [
            "4.1.0 — Архитектурная конституция",
            "4.0.0 — снятие плоского слоя tools/ (BREAKING)",
            "3.40.0 — warn-минор перед 4.0",
        ]
        # граница old ИСКЛЮЧЕНА — версии-источника в срезе нет
        assert not any(h.startswith("3.39.4") for h in out)
        # [Unreleased] не попадает
        assert not any("Unreleased" in h for h in out)

    def test_slice_extracts_title_after_middot(self):
        """Заголовок — часть после «·», без даты; порядок как в файле (новейшее сверху)."""
        out = changelog_gen.headlines_between("4.0.0", "4.1.0", text=self.SAMPLE)
        assert out == ["4.1.0 — Архитектурная конституция"]

    def test_slice_empty_when_bounds_unresolvable(self):
        """Нет границ / old>=new / нет текста -> ЧЕСТНО пустой срез (не выдумываем)."""
        assert changelog_gen.headlines_between(None, "4.1.0", text=self.SAMPLE) == []
        assert changelog_gen.headlines_between("4.1.0", "4.1.0", text=self.SAMPLE) == []
        assert changelog_gen.headlines_between("4.1.0", "3.39.4", text=self.SAMPLE) == []

    def test_slice_respects_limit(self):
        """limit ограничивает число пунктов (2-6 в брифинге)."""
        out = changelog_gen.headlines_between("3.39.4", "4.1.0", text=self.SAMPLE, limit=2)
        assert len(out) == 2 and out[0].startswith("4.1.0")

    def test_slice_reads_real_changelog_by_default(self):
        """Без text читает реальный CHANGELOG кита — заголовки между двумя его версиями находятся."""
        out = changelog_gen.headlines_between("4.0.0", "4.1.0")
        assert any(h.startswith("4.1.0 —") for h in out)


# TestSelftest удалён: тело переехало в tests/unit/test_changelog_gen_selftest.py
