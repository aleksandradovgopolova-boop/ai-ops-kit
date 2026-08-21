"""Зоны работы выводятся из `write_scope`, а не остаются `unspecified` на пути человека (заявка #138).

ПОЛЕ 17.08.2026, дочка ИИ-Среда: регистрация работы предупредила о пересечении зон СО ВСЕМИ четырьмя
активными записями сразу, при том что не пересекалось ни с одной. ЗАМЕР С КОНТРОЛЕМ на 3.36.12:
`classify` на двух работах с зонами `["unspecified"]` возвращает пересечение (`kind: area,
detail: [unspecified]`); те же работы с РЕАЛЬНЫМИ разными зонами — пустой список. Значит
предупреждение создавало само ЗАПОЛНЕНИЕ, а не совпадение зон.

ПРИЁМКА ИЗ ПЛАНА — ПАРА: работы с разными реальными зонами НЕ пересекаются, работы с общей зоной
пересекаются, и снятие вывода зон роняет именно этот тест. Плюс третий случай, из-за которого дефект
и был дефектом: две работы БЕЗ зон не пересекаются — неизвестность не является совпадением.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from ai_ops_kit.engine import work_areas
from ai_ops_kit.lifecycle import active_work


def _entry(wid, areas, **kw):
    e = {"id": wid, "affected_areas": areas, "branch": f"feature/{wid}",
         "machine": kw.get("machine", "m1"), "owner_session": kw.get("session", f"s-{wid}"),
         "status": "in-progress"}
    e.update({k: v for k, v in kw.items() if k not in ("machine", "session")})
    return e


# ─────────────────────── вывод зоны из scope ───────────────────────

def test_zone_is_the_directory_not_the_file_or_glob():
    assert work_areas.from_write_scope(["api/**", "db/x.py"]) == ["api", "db"]
    assert work_areas.from_write_scope(["ai_ops_kit/engine/", "tests/"]) == ["ai_ops_kit/engine", "tests"]


def test_scope_entry_without_slash_is_a_zone_too():
    """Прежняя формула требовала `"/" in p` и такие записи ТЕРЯЛА: работа со scope ["quality"]
    выглядела как работа без зон вообще."""
    assert work_areas.from_write_scope(["quality"]) == ["quality"]


def test_areas_for_prefers_declared_then_derived_then_admits_unknown():
    assert work_areas.areas_for({"affected_areas": ["core"]}, ["ai_ops_kit/ui/"]) == ["core"]
    assert work_areas.areas_for({"task_type": "QUICK"}, ["ai_ops_kit/ui/"]) == ["ai_ops_kit/ui"]
    assert work_areas.areas_for({}, None) == [work_areas.UNSPECIFIED]


# ─────────────────────── ПАРА замеров из плана ───────────────────────

def test_different_real_zones_do_not_intersect():
    mine = _entry("mine", work_areas.areas_for({}, ["ai_ops_kit/engine/"]))
    theirs = _entry("theirs", work_areas.areas_for({}, ["ai_ops_kit/ui/"]))
    found = active_work.classify([theirs], mine)
    assert [f for f in found if f["kind"] == "area"] == [], found


def test_shared_zone_does_intersect():
    mine = _entry("mine", work_areas.areas_for({}, ["ai_ops_kit/engine/", "tests/"]))
    theirs = _entry("theirs", work_areas.areas_for({}, ["ai_ops_kit/engine/"]))
    areas = [f for f in active_work.classify([theirs], mine) if f["kind"] == "area"]
    assert areas and areas[0]["detail"] == ["ai_ops_kit/engine"], areas


def test_unknown_zones_are_not_a_match():
    """ТА САМАЯ форма дефекта: две работы без зон «пересекались» друг с другом, и кит советовал
    человеку не трогать те же файлы, не зная ни одного файла."""
    mine = _entry("mine", [work_areas.UNSPECIFIED])
    theirs = _entry("theirs", [work_areas.UNSPECIFIED])
    assert [f for f in active_work.classify([theirs], mine) if f["kind"] == "area"] == []


def test_package_and_its_subsystem_do_intersect():
    """Работа, объявившая пакет целиком, ДЕРЖИТ и его подсистемы — вложенность это пересечение."""
    mine = _entry("mine", ["ai_ops_kit"])
    theirs = _entry("theirs", ["ai_ops_kit/engine"])
    areas = [f for f in active_work.classify([theirs], mine) if f["kind"] == "area"]
    assert areas and areas[0]["detail"] == ["ai_ops_kit/engine"], areas


# ─────────────────────── ШОВ: путь человека ───────────────────────

def test_seam_single_run_registers_derived_zones(tmp_path):
    """ШОВ: одиночный прогон — это путь, которым идёт человек. Если вывод зон до реестра не доходит,
    в `.ai/runtime/active-work.yaml` снова попадает `unspecified`, и пересекается всё со всем."""
    from ai_ops_kit.engine import ai_ops_run
    root = tmp_path / "child"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, capture_output=True)

    rep = ai_ops_run.run(task_text="почини опечатку", signals={"task_type": "QUICK"},
                         child_root=root, feature="areas-seam", engine="controller",
                         write_scope=["src/api/", "tests/"])
    assert rep["status"] == "planned", rep.get("error")
    reg = yaml.safe_load((root / ".ai" / "runtime" / "active-work.yaml").read_text(encoding="utf-8"))
    entry = next(w for w in reg["active"] if w["id"] == "areas-seam")
    assert entry["affected_areas"] == ["src/api", "tests"], entry["affected_areas"]
    assert work_areas.UNSPECIFIED not in entry["affected_areas"]


def test_seam_run_without_scope_admits_unknown_instead_of_inventing(tmp_path):
    """Обратная половина шва: выводить не из чего -> честное `unspecified`, а не выдуманная зона."""
    from ai_ops_kit.engine import ai_ops_run
    root = tmp_path / "child"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, capture_output=True)

    rep = ai_ops_run.run(task_text="почини опечатку", signals={"task_type": "QUICK"},
                         child_root=root, feature="areas-none", engine="controller")
    assert rep["status"] == "planned", rep.get("error")
    reg = yaml.safe_load((root / ".ai" / "runtime" / "active-work.yaml").read_text(encoding="utf-8"))
    entry = next(w for w in reg["active"] if w["id"] == "areas-none")
    assert entry["affected_areas"] == [work_areas.UNSPECIFIED]
