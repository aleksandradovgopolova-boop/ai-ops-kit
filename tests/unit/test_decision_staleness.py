"""Продюсер устаревания решений (#635): возраст + изменение связанных файлов -> stale + причина.

Не «старое = плохое», а «предпосылки решения изменились». Честность: связь решение->файлы
опциональна (`related_files`); не объявлена -> изменения unavailable, устаревшим НЕ помечаем.
Помечаем только когда возраст выше порога И связанные файлы реально менялись после даты решения.
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import decision_staleness as ds
from ai_ops_kit.planning import next_work


def _git(root, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    env.setdefault("GIT_AUTHOR_NAME", "t"); env.setdefault("GIT_AUTHOR_EMAIL", "t@t")
    env.setdefault("GIT_COMMITTER_NAME", "t"); env.setdefault("GIT_COMMITTER_EMAIL", "t@t")
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def _repo(tmp_path, episodes):
    _git(tmp_path, "init", "-q")
    dec = tmp_path / "decisions"
    dec.mkdir()
    (dec / "registry.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "kind": "decisions-registry",
                        "principles": [], "episodes": episodes}, allow_unicode=True),
        encoding="utf-8")
    return tmp_path


def _iso(days_ago):
    return (_dt.date.today() - _dt.timedelta(days=days_ago)).isoformat()


def _episode(eid, days_ago, related=None):
    ep = {"id": eid, "question": "q", "decision": "d", "reason": "r",
          "reversibility": "two-way", "date": _iso(days_ago)}
    if related is not None:
        ep["related_files"] = related
    return ep


@pytest.mark.unit
def test_old_decision_with_a_changed_related_file_is_flagged(tmp_path):
    root = _repo(tmp_path, [_episode("DEC-1", 200, ["svc.py"])])
    (root / "svc.py").write_text("v2\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "change svc")   # коммит «сейчас» — после даты
    out = ds.assess_decisions(root)
    assert len(out) == 1 and out[0]["id"] == "DEC-1" and out[0]["stale"] is True
    assert out[0]["files_changed"] >= 1 and out[0]["age_days"] >= 200
    assert "предпосылки" in out[0]["reason"]


@pytest.mark.unit
def test_young_decision_is_not_flagged_even_if_files_changed(tmp_path):
    root = _repo(tmp_path, [_episode("DEC-2", 10, ["svc.py"])])
    (root / "svc.py").write_text("v2\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "change")
    assert ds.assess_decisions(root) == []                              # возраст ниже порога


@pytest.mark.unit
def test_old_decision_without_related_files_is_unavailable_not_stale(tmp_path):
    root = _repo(tmp_path, [_episode("DEC-3", 300)])                    # related_files не объявлены
    (root / "x.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "x")
    assert ds.assess_decisions(root) == []                              # нет доказательства сдвига -> не помечаем


@pytest.mark.unit
def test_old_decision_whose_files_did_not_change_after_the_date_is_not_flagged(tmp_path):
    root = _repo(tmp_path, [_episode("DEC-4", 200, ["svc.py"])])
    # файл закоммичен ДО даты решения (300 дней назад) и больше не менялся
    (root / "svc.py").write_text("v1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "old commit", date=f"{_iso(300)}T00:00:00")
    assert ds.assess_decisions(root) == []                              # изменений после даты нет


@pytest.mark.unit
def test_a_bad_date_is_skipped_not_crashed(tmp_path):
    root = _repo(tmp_path, [{"id": "DEC-5", "question": "q", "decision": "d", "reason": "r",
                             "reversibility": "two-way", "date": "не дата", "related_files": ["a"]}])
    assert ds.assess_decisions(root) == []                              # битая дата -> пропуск, не падение


@pytest.mark.unit
def test_next_surfaces_stale_decisions_in_section_five():
    """Проводка: раздел «чего никто не спрашивал» показывает устаревшее решение (advisory)."""
    rep = {"schema_version": 1, "plan_present": True, "staleness": {"dead_references": [], "plan_behind": None},
           "stale_decisions": [{"id": "DEC-9", "age_days": 210, "files_changed": 3,
                                "related_files": ["a.py"], "stale": True, "reason": "предпосылки могли измениться"}],
           "plan_errors": [], "plan_warnings": [], "roadmap": {"errors": [], "warnings": []},
           "where_are_we": "", "in_progress": [], "blocked": [], "ready": [], "next_best": None,
           "parallel_with": [], "parallel_skipped": [], "not_ready": [], "conflicts": []}
    text = next_work.render(rep)
    assert "ЧЕГО НИКТО НЕ СПРАШИВАЛ" in text and "DEC-9" in text and "advisory" in text
