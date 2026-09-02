"""#404: доставка обновляет living-status дочки, чтобы status-freshness не блокировал авто-PR.

РАЗВОДКА (по культуре репозитория «тест обязан краснеть на дефекте»): дефект — прогон НЕ трогал
статус-док, тот протухал, required-проверка дочки краснела. `test_reddens_on_the_bug` доказывает,
что до обновления док именно `stale`, а после — `ok`: контраст падает, если `refresh` станет no-op.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ai_ops_kit.engine import pipeline_setup
from ai_ops_kit.engine import living_status as ls
from ai_ops_kit.validation import validate_freshness as vf

TODAY = "2026-09-02"
_TODAY_D = date(2026, 9, 2)


def _write(root: Path, rel: str, *, template: bool = False, reviewed: str = "2026-01-01",
           stability: str = "volatile", frontmatter: bool = True) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter:
        tmpl = "template: true\n" if template else ""
        head = f"---\n{tmpl}read_tier: 1\nstability: {stability}\nreviewed_at: {reviewed}\n---\n\n"
    else:
        head = ""
    p.write_text(head + "# ProductStatus\n\n## Что реально готово\n\n| Область | Статус |\n|---|---|\n",
                 encoding="utf-8")
    return p


# ─── positive ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_refresh_bumps_reviewed_at_and_appends_entry(tmp_path):
    doc = _write(tmp_path, "context/product/ProductStatus.md", reviewed="2026-01-01")
    res = ls.refresh(tmp_path, "W-42", "починить экспорт CSV\nс переносами", today=TODAY)
    assert res == {"doc": "context/product/ProductStatus.md", "reviewed_at": TODAY,
                   "entry": "2026-09-02 — доставлена работа W-42: починить экспорт CSV с переносами"}
    txt = doc.read_text()
    assert f"reviewed_at: {TODAY}" in txt
    assert "## Журнал доставки (AI Ops)" in txt
    assert "доставлена работа W-42: починить экспорт CSV с переносами" in txt  # многострочность схлопнута


@pytest.mark.unit
def test_reddens_on_the_bug(tmp_path):
    """Прямая проба: без обновления док протух (дефект #404), после — свеж. Если refresh перестанет
    менять файл, ветка `after == "ok"` покраснеет — способность теста поймать регрессию доказана."""
    doc = _write(tmp_path, "context/product/ProductStatus.md", reviewed="2026-01-01")
    before = vf.assess(vf.frontmatter(doc.read_text()), _TODAY_D)[0]
    assert before == "stale", "предусловие пробы: до обновления volatile-док обязан быть протухшим"
    ls.refresh(tmp_path, "W-1", "任意", today=TODAY)
    after = vf.assess(vf.frontmatter(doc.read_text()), _TODAY_D)[0]
    assert after == "ok", "после доставки статус-док обязан стать свежим — иначе PR немёржабелен"


@pytest.mark.unit
def test_newest_entry_goes_on_top(tmp_path):
    _write(tmp_path, "context/product/ProductStatus.md")
    ls.refresh(tmp_path, "W-2", "первая", today="2026-09-02")
    ls.refresh(tmp_path, "W-3", "вторая", today="2026-09-03")
    txt = (tmp_path / "context/product/ProductStatus.md").read_text()
    assert txt.count("— доставлена работа") == 2
    assert txt.find("W-3") < txt.find("W-2")


# ─── no-op: лжи не добавляем ─────────────────────────────────────────────────

@pytest.mark.unit
def test_template_doc_is_never_touched(tmp_path):
    doc = _write(tmp_path, "context/product/ProductStatus.md", template=True)
    before = doc.read_text()
    assert ls.refresh(tmp_path, "W-1", "t", today=TODAY) is None
    assert doc.read_text() == before


@pytest.mark.unit
def test_no_managed_doc_returns_none(tmp_path):
    assert ls.refresh(tmp_path, "W-1", "t", today=TODAY) is None
    # файл без frontmatter конвенции свежести — не наш, наугад не сочиняем
    _write(tmp_path, "PROJECT_STATUS.md", frontmatter=False)
    assert ls.refresh(tmp_path, "W-1", "t", today=TODAY) is None


@pytest.mark.unit
def test_config_points_at_child_specific_doc(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("living_status:\n  doc: PROJECT_STATUS.md\n", encoding="utf-8")
    _write(tmp_path, "PROJECT_STATUS.md")
    res = ls.refresh(tmp_path, "W-9", "задача", today=TODAY)
    assert res is not None and res["doc"] == "PROJECT_STATUS.md"
    assert f"reviewed_at: {TODAY}" in (tmp_path / "PROJECT_STATUS.md").read_text()


# ─── проводка в пайплайн ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_commit_work_refreshes_status_before_commit(tmp_path, monkeypatch):
    """Шов доставки (`_commit_work`) вызывает refresh на пути commit+have_work — иначе фикс мёртв."""
    calls = []
    monkeypatch.setattr(pipeline_setup._living_status, "refresh",
                        lambda root, wid, task: calls.append((root, wid, task)))
    monkeypatch.setattr(pipeline_setup, "_has_changes", lambda root: True)
    monkeypatch.setattr(pipeline_setup, "_commit_on_branch", lambda root, br, msg: "deadbeef")
    monkeypatch.setattr(pipeline_setup, "_tree_clean", lambda root: True)
    sha, branch, _, _ = pipeline_setup._commit_work(
        str(tmp_path), "W-7", "задача", is_git=True, applied=True, authored=False,
        shell_changed=False, self_committed=False, head_sha=None,
        commit=True, reevaluate_only=False)
    assert sha == "deadbeef" and branch == "ai-ops/W-7"
    assert calls == [(str(tmp_path), "W-7", "задача")]


@pytest.mark.unit
def test_no_refresh_without_commit(tmp_path, monkeypatch):
    """reevaluate-only / commit=False не создаёт коммит -> статус-док не трогаем."""
    calls = []
    monkeypatch.setattr(pipeline_setup._living_status, "refresh",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(pipeline_setup, "_has_changes", lambda root: True)
    pipeline_setup._commit_work(
        str(tmp_path), "W-7", "задача", is_git=True, applied=True, authored=False,
        shell_changed=False, self_committed=False, head_sha=None,
        commit=False, reevaluate_only=False)
    assert calls == []
