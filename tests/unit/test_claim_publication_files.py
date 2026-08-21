# -*- coding: utf-8 -*-
"""Публикация заявки файлом на работу в git — заявка одной машины видна другой.

РЕШЕНИЕ ВЛАДЕЛЬЦА 18.08.2026 (ep-2026-08-18-published-carrier-file-per-work): опубликованная заявка
живёт отдельным отслеживаемым файлом на пару (машина, работа) в `.ai/claims/`; уезжают только
объявленные поля, НЕ содержимое файлов; носитель работает офлайн.

ПАРА, а не один прогон (приёмка родительской работы): публикация выключена -> чужой заявки не видно;
включена -> вторая машина видит заявку первой и получает предупреждение о дубле ветки/работы.
"""

import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

pytestmark = pytest.mark.unit


@pytest.fixture
def aw():
    from ai_ops_kit.lifecycle import active_work
    return active_work


def _publish_config(root: Path, publish: bool):
    (root / ".ai-ops.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "team_coordination": {"publish": publish}},
                       allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------- носитель: пишет только объявленное

def test_publish_writes_only_declared_fields(aw, tmp_path):
    """Уезжают ровно PUBLISHED_FIELDS — и НИЧЕГО про содержимое файлов (условие 4 решения)."""
    entry = {"id": "w1", "branch": "feature/w1", "machine": "hostA", "owner_session": "s1",
             "started_at": "2026-08-18T10:00:00+00:00", "status": "in-progress",
             "affected_areas": ["core", "secret-internal-name"],   # НЕ должно уехать
             "workitem": "features/w1/workitem.yaml"}               # НЕ должно уехать
    p = aw.publish_claim(tmp_path, entry)
    rec = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert set(rec) - {"schema_version", "kind"} <= set(aw.PUBLISHED_FIELDS)
    assert "affected_areas" not in rec and "workitem" not in rec, rec
    assert rec["id"] == "w1" and rec["branch"] == "feature/w1" and rec["machine"] == "hostA"


def test_claims_dir_is_not_gitignored(aw):
    """Носитель обязан быть отслеживаемым — иначе он не доедет к команде через git."""
    rules = (KIT / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    # .ai/runtime/ игнорируется, а .ai/claims/ — НЕТ. Проверяем, что claims не попал под правило.
    assert ".ai/claims" not in rules or "merge=union" in rules  # claims не среди gitignore-правил
    assert str(aw.CLAIMS_DIR_REL) == ".ai/claims"


def test_unpublish_removes_only_own_pair(aw, tmp_path):
    aw.publish_claim(tmp_path, {"id": "w1", "machine": "hostA", "branch": "b1"})
    aw.publish_claim(tmp_path, {"id": "w1", "machine": "hostB", "branch": "b2"})
    assert aw.unpublish_claim(tmp_path, "hostA", "w1") is True
    left = aw.load_published_claims(tmp_path)
    assert [r["machine"] for r in left] == ["hostB"], "снята чужая пара или не та"


# ---------------------------------------------------------- чтение чужих заявок

def test_broken_claim_file_is_skipped_not_fatal(aw, tmp_path):
    d = tmp_path / ".ai" / "claims"
    d.mkdir(parents=True)
    (d / "good.yaml").write_text(yaml.safe_dump({"id": "w1", "machine": "hostA"}), encoding="utf-8")
    (d / "bad.yaml").write_text("id: [unterminated", encoding="utf-8")
    recs = aw.load_published_claims(tmp_path)
    assert [r["id"] for r in recs] == ["w1"], "битая чужая заявка уронила чтение всей карты"


def test_team_view_off_hides_others_on_when_published(aw, tmp_path, monkeypatch):
    """Пара: выключено -> только локальные; включено -> плюс чужие опубликованные."""
    monkeypatch.setattr(aw, "_machine", lambda: "hostLOCAL")
    aw.publish_claim(tmp_path, {"id": "wOther", "machine": "hostB", "branch": "b2",
                                "owner_session": "s2", "status": "in-progress"})
    local = [{"id": "wMine", "machine": "hostLOCAL", "branch": "b1", "status": "in-progress"}]

    off = aw.team_view(tmp_path, local, published=False)
    assert {w["id"] for w in off} == {"wMine"}, "выключенная публикация показала чужую заявку"

    on = aw.team_view(tmp_path, local, published=True)
    assert {w["id"] for w in on} == {"wMine", "wOther"}, "включённая публикация не показала чужую"


def test_team_view_excludes_own_published_copy(aw, tmp_path, monkeypatch):
    """Своя опубликованная копия не должна считаться дважды (локально + с носителя)."""
    monkeypatch.setattr(aw, "_machine", lambda: "hostLOCAL")
    aw.publish_claim(tmp_path, {"id": "wMine", "machine": "hostLOCAL", "branch": "b1"})
    local = [{"id": "wMine", "machine": "hostLOCAL", "branch": "b1", "status": "in-progress"}]
    view = aw.team_view(tmp_path, local, published=True)
    assert [w["id"] for w in view] == ["wMine"], "своя заявка задвоилась"


# ---------------------------------------------------------- цель #150: дубль ветки/работы между машинами

def test_second_machine_sees_duplicate_branch(aw, tmp_path, monkeypatch):
    """Ровно случай #150: вторая машина берёт ту же ВЕТКУ и обязана получить предупреждение."""
    monkeypatch.setattr(aw, "_machine", lambda: "hostA")
    aw.publish_claim(tmp_path, {"id": "wA", "machine": "hostA", "branch": "shared/branch",
                                "owner_session": "sA", "status": "in-progress"})
    # вторая машина проверяет ту же ветку
    monkeypatch.setattr(aw, "_machine", lambda: "hostB")
    against = aw.team_view(tmp_path, [], published=True)
    confs = aw.classify(against, {"id": "wB", "branch": "shared/branch",
                                  "machine": "hostB", "owner_session": "sB"})
    assert any(c["kind"] == "branch" for c in confs), confs


def test_second_machine_sees_duplicate_work(aw, tmp_path, monkeypatch):
    """Случай #150: вторая сессия берёт ту же РАБОТУ — это дубль (PR #526 так и выбросили)."""
    monkeypatch.setattr(aw, "_machine", lambda: "hostA")
    aw.publish_claim(tmp_path, {"id": "same-work", "machine": "hostA", "branch": "bA",
                                "owner_session": "sA", "status": "in-progress"})
    monkeypatch.setattr(aw, "_machine", lambda: "hostB")
    against = aw.team_view(tmp_path, [], published=True)
    confs = aw.classify(against, {"id": "same-work", "branch": "bB",
                                  "machine": "hostB", "owner_session": "sB"})
    assert any(c["kind"] == "same-work" for c in confs), confs


def test_off_no_cross_machine_warning(aw, tmp_path, monkeypatch):
    """Выключенная публикация -> чужой заявки не видно -> предупреждения о дубле НЕТ (честно)."""
    monkeypatch.setattr(aw, "_machine", lambda: "hostA")
    aw.publish_claim(tmp_path, {"id": "wA", "machine": "hostA", "branch": "shared/branch",
                                "owner_session": "sA", "status": "in-progress"})
    monkeypatch.setattr(aw, "_machine", lambda: "hostB")
    against = aw.team_view(tmp_path, [], published=False)
    confs = aw.classify(against, {"id": "wB", "branch": "shared/branch",
                                  "machine": "hostB", "owner_session": "sB"})
    assert confs == [], "выключенная публикация выдала предупреждение о чужой заявке"


# ---------------------------------------------------------- сквозь register/finish

def test_register_publishes_and_finish_unpublishes(aw, tmp_path, monkeypatch):
    monkeypatch.setattr(aw, "_machine", lambda: "hostA")
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sA", published=True, child_root=tmp_path)
    assert aw.load_published_claims(tmp_path), "register при публикации не создал файл заявки"
    aw.finish_cmd(reg, "w1", status="done", child_root=tmp_path, published=True)
    assert not aw.load_published_claims(tmp_path), "finish не снял опубликованную заявку"


def test_register_local_does_not_publish(aw, tmp_path, monkeypatch):
    monkeypatch.setattr(aw, "_machine", lambda: "hostA")
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sA", published=False, child_root=tmp_path)
    assert not (tmp_path / ".ai" / "claims").exists() or not aw.load_published_claims(tmp_path), \
        "выключенная публикация всё равно записала заявку на носитель"


# ---------------------------------------------------------- ШОВ: status показывает чужую заявку

def test_status_surfaces_another_machines_claim(aw, tmp_path, capsys):
    """ПРОБА ШВА: заявка другой машины доходит до человека, только если `status` строит ОБЩУЮ карту
    через team_view. Подмена на локальные заявки (мутация publish-seam-status-surfaces-team) обязана
    уронить этот тест: чужая заявка перестаёт быть видна, и status говорит «ничего не идёт».
    """
    from ai_ops_kit.cli import ai_ops_cli

    (tmp_path / ".ai" / "runtime").mkdir(parents=True)
    _publish_config(tmp_path, True)
    # локальный реестр пуст; заявка есть только у ДРУГОЙ машины (приехала бы через git)
    (tmp_path / ".ai" / "runtime" / "active-work.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "kind": "active-work", "active": []},
                       allow_unicode=True), encoding="utf-8")
    aw.publish_claim(tmp_path, {"id": "wOther", "machine": "hostB", "branch": "feature/other",
                                "owner_session": "sB", "started_at": "2026-08-18T10:00:00+00:00",
                                "status": "in-progress"})

    capsys.readouterr()
    ai_ops_cli.main(["status", str(tmp_path)])
    out = capsys.readouterr().out.lower()

    assert "работа идёт" in out or "в работе" in out, (
        "status не показал заявку другой машины — team_view не построен на этом пути:\n" + out)


def test_same_hostname_different_clone_is_still_visible(aw, tmp_path):
    """ЗАМЕР ЖИВОГО ПРОГОНА 18.08.2026: два клона на ОДНОМ хосте имеют одинаковое имя машины.
    Дедуп по имени машины прятал заявку соседнего клона — теперь дедуп по паре (машина, работа),
    и чужая работа того же хоста остаётся видна. Юнит-тесты с monkeypatch этого не поймали (разные
    имена), поймал только живой git-прогон — тест закрывает пробел."""
    # заявка "соседнего клона": то же имя хоста, но ДРУГАЯ работа; мой локальный реестр её не знает
    aw.publish_claim(tmp_path, {"id": "neighbour-work", "machine": "same-host",
                                "branch": "feature/neighbour", "owner_session": "sN",
                                "status": "in-progress"})
    local = [{"id": "my-work", "machine": "same-host", "branch": "feature/mine",
              "status": "in-progress"}]   # моя работа, тот же хост
    view = aw.team_view(tmp_path, local, published=True)
    assert {w["id"] for w in view} == {"my-work", "neighbour-work"}, (
        "заявка соседнего клона на том же хосте пропала — дедуп по имени машины, а не по паре")
