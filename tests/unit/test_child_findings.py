"""Гранулярные тесты child_findings (#585): findings/from-children → планирование.

Ключевое доказательство: наблюдение из findings/from-children порождает ВИДИМОГО владельцу
кандидата/урок; открытое наблюдение → кандидат-работа (DRAFT, требует решения человека); закрытые →
уроки-прецеденты. Ничего не пишется.
"""
from __future__ import annotations

import yaml

from ai_ops_kit.engops import kit_feedback
from ai_ops_kit.intelligence import child_findings as cf


def _write_obs(kit_root, oid, *, state, cls="defect", child="bnbm"):
    d = kit_root / kit_feedback.KIT_DIR
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "kind": "KitObservation", "id": oid,
           "at": "2026-09-07T00:00:00+00:00", "statement": f"наблюдение {oid} из прогона",
           "observation_class": cls, "severity": "p1", "state": state,
           "child": {"name": child, "path": f"/tmp/{child}"},
           "evidence": [{"kind": "note", "text": "e"}]}
    (d / f"{oid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def test_open_observation_becomes_visible_candidate(tmp_path):
    """Открытое (delivered) наблюдение → кандидат-работа DRAFT, требующая решения человека."""
    _write_obs(tmp_path, "obs-open", state="delivered")
    proj = cf.project_findings(tmp_path)
    assert proj["open_count"] == 1
    assert len(proj["candidates"]) == 1
    c = proj["candidates"][0]
    assert c["status"] == "draft" and c["active"] is False
    assert c["requires_human_decision"] is True
    assert c["source_observation"] == "obs-open"


def test_resolved_observation_becomes_lesson_not_candidate(tmp_path):
    """Закрытое (became_work) наблюдение НЕ кандидат, но входит в урок-прецедент (видим владельцу)."""
    _write_obs(tmp_path, "obs-done", state="became_work")
    proj = cf.project_findings(tmp_path)
    assert proj["open_count"] == 0
    assert proj["candidates"] == []
    assert len(proj["precedents"]) == 1
    assert proj["precedents"][0]["case_count"] == 1


def test_precedent_from_findings_has_no_causation(tmp_path):
    """Урок из наблюдений — прецедент (факт+число случаев), без утверждения причинности (#586)."""
    _write_obs(tmp_path, "o1", state="became_work", child="a")
    _write_obs(tmp_path, "o2", state="became_work", child="b")
    proj = cf.project_findings(tmp_path)
    p = proj["precedents"][0]
    assert p["case_count"] == 2
    assert not ({"causation", "rule", "transferable", "recommendation"} & set(p))


def test_candidate_not_active_without_human_decision(tmp_path):
    """Кандидат из наблюдения не становится активной работой сам по себе."""
    _write_obs(tmp_path, "obs-x", state="accepted")
    c = cf.project_findings(tmp_path)["candidates"][0]
    assert c["active"] is False and c["requires_human_decision"] is True


def test_empty_channel_is_empty_projection(tmp_path):
    """Нет наблюдений → пустая проекция (не выдуманный список)."""
    proj = cf.project_findings(tmp_path)
    assert proj["observation_count"] == 0
    assert proj["candidates"] == [] and proj["precedents"] == []


def test_projection_writes_nothing(tmp_path):
    """Проекция read-only: файлов не создаёт и не меняет (writer ≠ judge)."""
    _write_obs(tmp_path, "obs-ro", state="delivered")
    before = sorted((tmp_path / kit_feedback.KIT_DIR).glob("*.yaml"))
    cf.project_findings(tmp_path)
    after = sorted((tmp_path / kit_feedback.KIT_DIR).glob("*.yaml"))
    assert before == after
