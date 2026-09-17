"""Релиз гасит очередь заявлений, и что она пуста — проверяемо (аудит A2, `release-drains-...`).

Повод. towncrier настроен собирать CHANGELOG.md из newsfragments/, но релиз кита `build` не звал —
очередь копилась сотнями фрагментов. Дренаж впаян в `release_bump` (сборка на бампе), а гейт на
самом выпуске доказывает результат «на релизе очередь пуста». Здесь стережём обе половины:
  * валидатор краснит непустую очередь ТОЛЬКО в release-режиме, вне релиза — совет (иначе он блокировал
    бы обычную работу: каждый PR добавляет фрагмент);
  * гейт реально ВЫЗЫВАЕТСЯ в release.yml, до создания тега, под условием needed;
  * bump() при доступном towncrier сгребает накопленную очередь в раздел CHANGELOG и очищает её.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))

from ai_ops_kit.validation import validate_changelog_queue_drained as vq  # noqa: E402
from ai_ops_kit.devtools import release_bump as rb  # noqa: E402

pytestmark = pytest.mark.unit


def _news(root: Path, names: list[str]) -> Path:
    d = root / "newsfragments"
    d.mkdir(parents=True, exist_ok=True)
    (d / "README.md").write_text("как называть фрагмент\n", encoding="utf-8")
    for n in names:
        (d / n).write_text(f"заявление {n}\n", encoding="utf-8")
    return d


# ── валидатор: острый в release-режиме, совет вне релиза ────────────────────────
class TestValidatorGatesOnlyAtRelease:
    def test_nonempty_queue_is_green_without_release_flag(self, tmp_path):
        """Между релизами непустая очередь — норма, а не нарушение."""
        _news(tmp_path, ["a.feat.md", "b.fix.md"])
        assert vq.check(tmp_path, release=False) == []
        assert vq.main(["--root", str(tmp_path)]) == 0

    def test_nonempty_queue_reddens_the_release(self, tmp_path):
        """КОНТРОЛЬ остроты: с --release непустая очередь краснит (иначе гейт слеп)."""
        _news(tmp_path, ["a.feat.md", "b.fix.md"])
        errs = vq.check(tmp_path, release=True)
        assert errs and "непуста" in errs[0]
        assert vq.main(["--release", "--root", str(tmp_path)]) == 1

    def test_empty_queue_passes_the_release(self, tmp_path):
        """Пустая очередь (только README) на релизе — зелено."""
        _news(tmp_path, [])
        assert vq.check(tmp_path, release=True) == []
        assert vq.main(["--release", "--root", str(tmp_path)]) == 0


# ── гейт реально вызывается на выпуске, до тега ─────────────────────────────────
class TestGateIsWiredIntoRelease:
    def _release_steps(self):
        wf = yaml.safe_load((KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
        return wf["jobs"]["release"]["steps"]

    def _gate_step(self):
        for s in self._release_steps():
            if "validate_changelog_queue_drained.py" in str(s.get("run", "")):
                return s
        raise AssertionError("в release.yml нет шага, вызывающего гейт дренажа очереди")

    def test_gate_is_called_with_release_flag(self):
        assert "--release" in str(self._gate_step()["run"]), \
            "гейт вызван без --release — вне release-режима он всегда зелёный, то есть не гейт"

    def test_gate_is_conditional_on_need_release(self):
        assert str(self._gate_step().get("if")) == "steps.check_release.outputs.needed == 'true'"

    def test_gate_runs_before_the_tag_is_created(self):
        steps = self._release_steps()
        gate_idx = steps.index(self._gate_step())
        tag_idx = next(i for i, s in enumerate(steps)
                       if "gh release create" in str(s.get("run", "")))
        assert gate_idx < tag_idx, "гейт стоит после создания тега — тег вышел бы до проверки"


# ── bump() при доступном towncrier сгребает очередь и очищает её ────────────────
def _release_repo(root: Path, ver="1.2.3", channel="qualification"):
    """Репозиторий с версионными поверхностями И towncrier-конфигом + маркером в CHANGELOG."""
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
    (root / "CHANGELOG.md").write_text(
        "# CHANGELOG\n\n## [Unreleased]\n\n<!-- towncrier release notes start -->\n\n"
        f"## [{ver}] — 2026-01-01 · старое\n\nбыло раньше\n", encoding="utf-8")
    # towncrier-конфиг БЕЗ package (в фикстуре пакета нет; версия задаётся --version в build).
    (root / "pyproject.toml").write_text(
        "[tool.towncrier]\n"
        'directory = "newsfragments"\n'
        'filename = "CHANGELOG.md"\n'
        'title_format = "## [{version}] — {project_date}"\n'
        'issue_format = "{issue}"\n'
        '[[tool.towncrier.type]]\ndirectory = "feat"\nname = "Новое"\nshowcontent = true\n'
        '[[tool.towncrier.type]]\ndirectory = "fix"\nname = "Исправлено"\nshowcontent = true\n',
        encoding="utf-8")
    return root


def test_bump_drains_the_queue_into_the_changelog(tmp_path):
    """При доступном towncrier bump() сгребает накопленные заявления в раздел и очищает очередь."""
    pytest.importorskip("towncrier", reason="towncrier не установлен — дренаж проверяется в релизном окружении")
    root = _release_repo(tmp_path / "r", ver="1.2.3")
    _news(root, ["feature-x.feat.md", "bug-y.fix.md"])

    changed = rb.bump(root, "1.2.4", title="Заголовок релиза", date="2026-09-17")

    assert rb.current_version(root) == "1.2.4"
    assert rb.check(root) == []                       # версии согласованы
    assert "CHANGELOG.md" in changed
    ch = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    # шапка в формате кита (её ждёт извлекатель записок release.yml)
    assert "## [1.2.4] — 2026-09-17 · Заголовок релиза" in ch
    # накопленные заявления сгребены под категории
    assert "feature-x" in ch and "bug-y" in ch
    # очередь очищена — остался только README
    left = [p.name for p in (root / "newsfragments").glob("*.md") if p.name != "README.md"]
    assert left == [], f"очередь не очищена после релиза: {left}"
    # гейт на выпуске теперь зелёный на этом дереве
    assert vq.check(root, release=True) == []


def test_bump_without_towncrier_config_uses_manual_section(tmp_path):
    """Без towncrier-дренажа (нет конфига/маркера) bump() пишет раздел вручную и не падает —
    путь для не-китового/офлайн-репозитория. Детерминирован независимо от наличия towncrier."""
    root = _release_repo(tmp_path / "r", ver="1.2.3")
    # убираем конфиг towncrier -> _towncrier_ready == False -> ручной путь
    (root / "pyproject.toml").write_text("[tool.other]\nx = 1\n", encoding="utf-8")
    changed = rb.bump(root, "1.2.4", title="Ручной", date="2026-09-17", body="- пункт")
    ch = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.2.4] — 2026-09-17 · Ручной" in ch
    assert "- пункт" in ch
    assert any("release-v1.2.4" in c for c in changed)
