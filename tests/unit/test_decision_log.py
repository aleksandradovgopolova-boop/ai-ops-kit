"""Тесты AI Decision Log (PR-18): расширяет реестр решений, СОХРАНЯЯ комментарии, и не ломает
существующий validate_decisions."""
from __future__ import annotations

import pytest
import yaml

from ai_ops_kit.governance import decision_log as dl
from validate_decisions import check as validate_decisions_check  # tests не пакет — импорт по имени ок

REGISTRY_WITH_OUTCOMES = """\
# ЭТОТ КОММЕНТАРИЙ ОБЯЗАН ВЫЖИТЬ ПОСЛЕ ВСТАВКИ
schema_version: 1
kind: decisions-registry

episodes:
  - id: ep-existing
    question: Как жить?
    decision: Хорошо
    reason: Потому что
    reversibility: two-way
    date: 2026-08-01

outcomes:
  - decision: ep-existing
"""

REGISTRY_EPISODES_LAST = """\
schema_version: 1
kind: decisions-registry

episodes:
  - id: ep-existing
    question: Q
    decision: D
    reason: R
    reversibility: two-way
    date: 2026-08-01
"""


def _write(root, text):
    (root / "decisions").mkdir(exist_ok=True)
    (root / dl.REGISTRY_REL).write_text(text, encoding="utf-8")


def _fields(decision_id="ai-2026-08-20-x"):
    return dict(decision_id=decision_id, question="Взять ли работу X?",
                decision="Взял X по совету next", reason="высший приоритет из живых целей",
                date="2026-08-20", data="next_work.compute: ready[0]=X",
                outcome="PR открыт", human_overrode=False)


def test_append_adds_ai_episode(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)
    ep = dl.log_ai_decision(tmp_path, **_fields())
    assert ep["actor"] == "ai"
    got = dl.ai_decisions(tmp_path)
    assert [e["id"] for e in got] == ["ai-2026-08-20-x"]
    assert got[0]["data"] and got[0]["outcome"] and got[0]["human_overrode"] is False


def test_comments_and_other_sections_survive(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)
    dl.log_ai_decision(tmp_path, **_fields())
    text = (tmp_path / dl.REGISTRY_REL).read_text(encoding="utf-8")
    assert "ЭТОТ КОММЕНТАРИЙ ОБЯЗАН ВЫЖИТЬ ПОСЛЕ ВСТАВКИ" in text
    # outcomes-секция цела и всё ещё резолвится
    data = yaml.safe_load(text)
    assert data["outcomes"] == [{"decision": "ep-existing"}]


def test_registry_stays_valid_for_existing_validator(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)
    dl.log_ai_decision(tmp_path, **_fields())
    data = yaml.safe_load((tmp_path / dl.REGISTRY_REL).read_text(encoding="utf-8"))
    errors, _ = validate_decisions_check(data)
    assert errors == []          # существующий гейт остаётся зелёным


def test_append_when_episodes_is_last_section(tmp_path):
    _write(tmp_path, REGISTRY_EPISODES_LAST)
    dl.log_ai_decision(tmp_path, **_fields())
    got = dl.ai_decisions(tmp_path)
    assert len(got) == 1
    data = yaml.safe_load((tmp_path / dl.REGISTRY_REL).read_text(encoding="utf-8"))
    assert len(data["episodes"]) == 2


def test_duplicate_id_is_refused(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)
    with pytest.raises(dl.RegistryError):
        dl.log_ai_decision(tmp_path, **_fields(decision_id="ep-existing"))


def test_missing_required_field_refused(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)
    with pytest.raises(dl.RegistryError):
        dl.build_ai_episode(decision_id="ai-x", question="", decision="d",
                            reason="r", date="2026-08-20", data="d")


def test_bad_date_refused(tmp_path):
    with pytest.raises(dl.RegistryError):
        dl.build_ai_episode(decision_id="ai-x", question="q", decision="d",
                            reason="r", date="20.08.2026", data="d")


def test_missing_registry_refused(tmp_path):
    with pytest.raises(dl.RegistryError):
        dl.append_ai_decision(tmp_path, dl.build_ai_episode(**_fields()))


def test_ai_decisions_filters_by_actor(tmp_path):
    _write(tmp_path, REGISTRY_WITH_OUTCOMES)   # ep-existing без actor
    dl.log_ai_decision(tmp_path, **_fields())
    ids = [e["id"] for e in dl.ai_decisions(tmp_path)]
    assert "ep-existing" not in ids and "ai-2026-08-20-x" in ids
