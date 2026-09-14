"""Гранулярные тесты passport_generator (мигрировано из test_passport_generator_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import passport_generator as PG
from ai_ops_kit.planning import product_templates as PT

REG = AR.load()
REQUIRED = AR.artifact(REG, "product_passport")["structure"]["required_sections"]


def _repo(tmp_path):
    """Небольшой, но реальный репозиторий: README, VERSION, тест, CI, манифест."""
    (tmp_path / "README.md").write_text("# Акме\n\nСервис учёта заявок для складов.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("2.3.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='acme'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    gh = tmp_path / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yml").write_text("name: ci\non: [push]\n", encoding="utf-8")
    return tmp_path


# ── positive ────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGeneratedPassport:
    def test_structurally_valid(self, tmp_path):
        r = _repo(tmp_path)
        text = PG.generate(r, reg=REG)
        (r / ".ai-ops").mkdir()
        (r / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(text, encoding="utf-8")
        art = AR.artifact(REG, "product_passport")
        assert PT.state_of(r, art, REG)["state"] == PT.VALID

    def test_content_filled_not_just_headers(self, tmp_path):
        r = _repo(tmp_path)
        text = PG.generate(r, reg=REG)
        filled, empty = PG.is_filled(text, REQUIRED)
        assert filled, f"пустые разделы: {empty}"

    def test_facts_from_real_files(self, tmp_path):
        r = _repo(tmp_path)
        secs = PG.sections(r)
        assert "2.3.0" in secs["Версия и последний релиз"]["value"]
        assert secs["Версия и последний релиз"]["state"] == PG.VERIFIED
        assert "Green" in secs["Здоровье (продукт / технологии / delivery)"]["value"]


# ── fail-closed ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFailClosed:
    def test_headers_only_not_filled(self):
        stub = "<!-- template-version: 1 -->\n# Product Passport\n" + \
               "".join(f"## {s}\n" for s in REQUIRED)
        filled, empty = PG.is_filled(stub, REQUIRED)
        assert not filled
        assert set(empty) == set(REQUIRED)

    def test_empty_repo_honest_unknowns(self, tmp_path):
        secs = PG.sections(tmp_path)
        assert secs["Название и описание"]["state"] == PG.UNKNOWN
        assert secs["Версия и последний релиз"]["state"] == PG.UNKNOWN
        assert "неизвестно" in secs["Версия и последний релиз"]["value"].lower()


# ── side-effect ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSideEffects:
    def test_non_derivable_sections_unknown(self, tmp_path):
        r = _repo(tmp_path)
        secs = PG.sections(r)
        assert secs["Аудитория и проблема"]["state"] == PG.UNKNOWN
        assert secs["Owner и команда"]["state"] == PG.UNKNOWN
        assert secs["Аудитория и проблема"]["value"].strip()

    def test_tech_health_unknown_when_unreadable(self):
        h = PG._tech_health({"tree_readable": False})
        assert h["band"] == "unknown"


# ── milestone читает горизонт «Сейчас», а не только литерал «Now» ─────────────────
# Регресс: канонический roadmap кита и русскоязычных дочек называет горизонт «Сейчас».
# Прежде _milestone искал `if "now" in headers` и на своём же roadmap выдавал «неизвестно».

@pytest.mark.unit
class TestMilestoneReadsHorizon:
    def _roadmap(self, tmp_path, heading):
        (tmp_path / "ROADMAP.md").write_text(
            f"# ROADMAP\n\n## {heading}\n\n- `cel-1` — команда работает над продуктом.\n"
            "- `cel-2` — владелец говорит продуктом.\n\n## Later\n\n- потом.\n",
            encoding="utf-8")
        return tmp_path

    def test_reads_russian_seichas_header(self, tmp_path):
        r = self._roadmap(tmp_path, "Сейчас")
        m = PG.sections(r)["Текущий milestone и прогресс"]
        assert m["state"] == PG.INFERRED
        assert "cel-1" in m["value"]

    def test_reads_english_now_header(self, tmp_path):
        r = self._roadmap(tmp_path, "Now")
        m = PG.sections(r)["Текущий milestone и прогресс"]
        assert m["state"] == PG.INFERRED
        assert "cel-1" in m["value"]

    def test_unknown_when_no_roadmap(self, tmp_path):
        m = PG.sections(tmp_path)["Текущий milestone и прогресс"]
        assert m["state"] == PG.UNKNOWN


# ── имя репозитория продукт-, а не каталого-центрично (git-worktree) ──────────────

@pytest.mark.unit
class TestRepoName:
    def _git(self, cwd, *args):
        import subprocess
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       capture_output=True, text=True)

    def test_name_from_origin_remote_not_dir(self, tmp_path):
        # Каталог назван служебно (как worktree), а origin указывает на продукт.
        work = tmp_path / "whale-status-dashboard-02f8c3"
        work.mkdir()
        self._git(work, "init", "-q")
        self._git(work, "remote", "add", "origin",
                  "https://github.com/example/ai-ops-kit.git")
        assert PG._repo_name(work) == "ai-ops-kit"

    def test_name_falls_back_to_dir_without_git(self, tmp_path):
        d = tmp_path / "acme"
        d.mkdir()
        assert PG._repo_name(d) == "acme"
