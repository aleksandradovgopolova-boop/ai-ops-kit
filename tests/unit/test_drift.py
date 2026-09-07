"""SR-14..16: РАСХОЖДЕНИЕ (drift) архитектуры дочки — отдельный класс находки (срез 4).

Проверяется: расхождение отличается от нарушения СЛОВОМ состояния, а не severity (SR-14); меряется
на ДИФФЕ — без изменённых путей not_checked, на унаследованном долге молчит (SR-15); снимок
архитектуры СОХРАНЯЕТСЯ в область дочки видимым шагом, и по нему расхождение измеримо (SR-16).
Тест поведенческий: импортирует planning/drift И зовёт его (save_snapshot/report), а также сверяет
проводку блока в governance_report.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import contours
from ai_ops_kit.planning import drift as D
from ai_ops_kit.planning import governance_report as G

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
SCHEMA = json.loads((PKG / "schemas" / "governance-report.schema.json").read_text(encoding="utf-8"))


def _child(tmp_path) -> Path:
    cfg = {"schema_version": 1, "kind": "ai-ops-child-config",
           "standard": {"version": 1, "profile": "ai-product"}}
    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── SR-15: расхождение меряется на диффе, а не на дереве ──

@pytest.mark.unit
def test_without_changed_files_block_is_not_checked_not_pass(tmp_path):
    """Вне контекста PR (нет изменённых путей) блок объявляет not_checked с причиной, не pass."""
    rep = D.report(_child(tmp_path), changed_files=None)
    assert rep["comparable"] is False
    assert rep["counts"]["not_checked"] >= 1 and rep["counts"]["pass"] == 0
    row = next(r for r in rep["rows"] if r["requirement"] == "drift::diff")
    assert row["status"] == "not_checked" and row.get("reason")


# ── SR-14: расхождение — свой РОД находки, назван словом, а не severity ──

@pytest.mark.unit
def test_source_of_truth_behind_surfaces_as_drift_class_word(tmp_path):
    """Источник истины контура отстал от кода: выходит в блок как РОД `drift` и слово `drift`,
    а не как нарушение (`violated`). Различие — словами (SR-14)."""
    model = contours.load_model()
    root = _child(tmp_path)
    # data_contracts: сигнал `supabase/migrations`, источник истины `context/system/DataMap.md`.
    _write(root, "context/system/DataMap.md", "# карта данных")
    _write(root, "supabase/migrations/0006.sql", "alter table users;")

    rep = D.report(root, changed_files=["supabase/migrations/0006.sql"], model=model)
    drifts = [r for r in rep["rows"] if r["status"] == "drift"]
    assert drifts, "описание контура отстало от кода — это расхождение"
    r = drifts[0]
    assert r["class"] == "drift" and r["status"] == "drift"
    assert "violated" not in {x["status"] for x in rep["rows"]}, "расхождение не называется нарушением"
    assert "РАСХОЖДЕНИЕ" in r["detail"] or "расхожден" in r["detail"].lower()

    # Источник истины обновлён вместе с кодом -> расхождения нет.
    rep2 = D.report(root, changed_files=["supabase/migrations/0006.sql",
                                         "context/system/DataMap.md"], model=model)
    assert not [r for r in rep2["rows"] if r["status"] == "drift"]


# ── SR-16: снимок архитектуры сохраняется в область дочки видимым шагом ──

@pytest.mark.unit
def test_snapshot_saved_into_child_area_is_a_visible_step(tmp_path):
    """save_snapshot кладёт снимок в область дочки (.ai-ops/), load_snapshot читает его оттуда."""
    root = _child(tmp_path)
    _write(root, "package.json", json.dumps({"dependencies": {"react": "^18"}}))
    assert D.load_snapshot(root) is None, "до видимого шага снимка нет"

    path = D.save_snapshot(root)
    assert path == root / D.SNAPSHOT_REL and path.is_file()
    assert path.relative_to(root).parts[0] == ".ai-ops", "снимок лежит в области дочки (SR-16)"
    saved = D.load_snapshot(root)
    assert saved and saved.get("kind") == "ArchitectureBaseline"


@pytest.mark.unit
def test_snapshot_drift_measured_on_diff_and_silent_on_untouched_tree(tmp_path):
    """Снимок разошёлся с кодом: расхождение объявляется, только если PR тронул архитектурные
    сигналы (SR-15); изменение, не касавшееся архитектуры, молчит, даже если снимок устарел."""
    root = _child(tmp_path)
    _write(root, "package.json", json.dumps({"dependencies": {"react": "^18"}}))
    D.save_snapshot(root)

    # Архитектуру сместили: появился API-эндпоинт — снимок теперь отстал.
    _write(root, "src/api/users.ts", "router.get('/users', handler)\n")

    # PR трогает архитектурный сигнал (api/), снимок в PR не обновлён -> расхождение.
    rep = D.report(root, changed_files=["src/api/users.ts"])
    snap = [r for r in rep["rows"] if r["requirement"] == "drift::architecture-snapshot"]
    assert snap and snap[0]["status"] == "drift"
    assert snap[0]["address"] == D.SNAPSHOT_REL

    # Тот же устаревший снимок, но PR НЕ касался архитектуры -> молчание (SR-15, унаследованный долг).
    rep2 = D.report(root, changed_files=["README.md"])
    assert not [r for r in rep2["rows"] if r["requirement"] == "drift::architecture-snapshot"
                and r["status"] == "drift"]


@pytest.mark.unit
def test_updating_snapshot_in_the_pr_clears_snapshot_drift(tmp_path):
    """Снимок обновлён в том же PR (видимый шаг сделан) -> расхождения снимка нет."""
    root = _child(tmp_path)
    _write(root, "package.json", json.dumps({"dependencies": {"react": "^18"}}))
    D.save_snapshot(root)
    _write(root, "src/api/users.ts", "router.get('/users', handler)\n")

    rep = D.report(root, changed_files=["src/api/users.ts", D.SNAPSHOT_REL])
    assert not [r for r in rep["rows"] if r["requirement"] == "drift::architecture-snapshot"
                and r["status"] == "drift"]


@pytest.mark.unit
def test_missing_snapshot_is_not_checked_with_reason(tmp_path):
    """Снимок не сохранён — сравнивать не с чем: not_checked с причиной, а не pass/drift (SR-16)."""
    root = _child(tmp_path)
    _write(root, "src/api/users.ts", "router.get('/users', handler)\n")
    rep = D.report(root, changed_files=["src/api/users.ts"])
    snap = next(r for r in rep["rows"] if r["requirement"] == "drift::architecture-snapshot")
    assert snap["status"] == "not_checked" and snap.get("reason")


# ── Проводка: блок drift едет в governance-отчёт и соответствует схеме ──

@pytest.mark.unit
def test_drift_block_wired_into_governance_report_and_matches_schema(tmp_path):
    root = _child(tmp_path)
    rep = G.build(root, changed_files=None)
    assert "drift" in rep, "блок расхождений не проведён в governance-отчёт"
    block = rep["drift"]
    props = SCHEMA["properties"]["drift"]
    for k in props["required"]:
        assert k in block, f"в блоке drift нет обязательного по схеме поля {k}"
    assert block["kind"] == props["properties"]["kind"]["const"] == "drift"
    assert block["class"] == "drift" and block["strength"] == "advisory"
    status_enum = set(props["properties"]["rows"]["items"]["properties"]["status"]["enum"])
    assert "drift" in status_enum and "violated" not in status_enum
    for r in block["rows"]:
        assert r["status"] in status_enum


@pytest.mark.unit
def test_render_names_drift_as_not_a_violation(tmp_path):
    """Текстовый отчёт называет расхождение расхождением, отдельно от нарушений (SR-14)."""
    rep = G.build(_child(tmp_path), changed_files=None)
    text = G.render(rep)
    assert "Расхождение" in text and "нарушение" in text.lower()
