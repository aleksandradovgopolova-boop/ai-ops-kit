"""Autonomous Replanning Loop (капстоун Фазы 5) — цикл сам сводит приоритеты плана к реальности.

Что проверяется (мутационно — снятие поведения красит соответствующий тест):
  * positive     — переприоритизация отражает реальностью-ранжированный порядок next_work и несёт
                   ПОДПИСЬ «почему» у каждой позиции; граница автономии названа в самом отчёте;
  * INVARIANT    — переприоритизация НЕ добавляет и НЕ удаляет работы (провал ии-среды невозможен по
                   механизму): если композиция уронит работу, apply отказывает (blocked), файл не
                   пишется;
  * write-scope  — apply пишет МАШИННЫЙ артефакт `.ai/project/replan/latest.yaml`, а НЕ авторский
                   `planning/plan.yaml`; структурные предложения в артефакт не попадают;
  * fail-closed  — kill-switch (env/файл) глушит запись; «не проверено» (нет плана, бэклог
                   недоступен) называется, а не сворачивается в «расхождений нет»;
  * determinism  — модель не зовётся (budget=0), отчёт воспроизводим.
"""
from __future__ import annotations

import yaml

from ai_ops_kit.intelligence import replan_loop as RL


# ── фикстура дочернего плана (без git: git_disagreements честно скажет «не измерено») ────────────

def _repo(tmp_path, work, goals=None):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "delivery-plan",
         "goals": goals or [{"id": "g1", "status": "active", "outcome": {"works": False}}],
         "work": work}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lines = ["# ROADMAP", "", "## Сейчас", "", "- `g1` — пользователь получает результат", "",
             "## Следующий результат", "", "- `next-thing` — большее", "",
             "## Дальше", "", "- крупная возможность", "", "## Later", "", "- идея"]
    (tmp_path / "ROADMAP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _item(wid, **kw):
    base = {"id": wid, "title": f"работа {wid}", "type": "engineering", "goal": "g1",
            "status": "todo", "owner_role": "engineer", "depends_on": [],
            "write_scope": [f"src/{wid.lower()}/"]}
    base.update(kw)
    return base


def _two_ready(tmp_path):
    """small объявлен ПЕРВЫМ, но big снимает ожидание с двоих -> реальность ставит big выше."""
    return _repo(tmp_path, [
        _item("small", value="low", write_scope=["src/small/"]),
        _item("big", value="high", write_scope=["context/system/"], type="architecture",
              owner_role="architect"),
        _item("dep1", depends_on=["big"], write_scope=["src/dep1/"]),
        _item("dep2", depends_on=["big"], write_scope=["src/dep2/"]),
    ])


# ── positive: переприоритизация отражает реальность и несёт провенанс ────────────────────────────

def test_report_names_the_autonomy_boundary(tmp_path):
    rep = RL.replan_report(_two_ready(tmp_path), backlog=False)
    # Граница «переприоритизация — авто, структура — предложением» названа в самом отчёте.
    assert rep["autonomy"] == "reprioritize-auto; structure-proposed"


def test_reprioritization_reflects_reality_ranking_and_marks_moves(tmp_path):
    rep = RL.replan_report(_two_ready(tmp_path), backlog=False)
    order = [r["id"] for r in rep["reprioritization"]]
    # big снимает ожидание с двоих -> реальность ставит его выше объявленного порядка.
    assert order[0] == "big", order
    assert order.index("big") < order.index("small")
    # сдвиг относительно объявленного порядка помечен.
    big = next(r for r in rep["reprioritization"] if r["id"] == "big")
    assert big["moved"] is True


def test_every_reprioritized_item_carries_why(tmp_path):
    """Как судейский вердикт, порядок без объяснения непроверяем — у каждой позиции есть «почему»."""
    rep = RL.replan_report(_two_ready(tmp_path), backlog=False)
    assert rep["reprioritization"]                      # непусто
    for r in rep["reprioritization"]:
        assert r["why"] and all(isinstance(w, str) and w for w in r["why"]), r


# ── INVARIANT: состав работ не меняется (провал ии-среды невозможен по механизму) ────────────────

def test_same_work_set_predicate_names_drops_and_additions():
    assert RL._check_same_work_set(["a", "b"], ["b", "a"]) is None      # переупорядочивание — ок
    dropped = RL._check_same_work_set(["a", "b", "c"], ["a", "b"])
    assert dropped and "пропали" in dropped and "'c'" in dropped
    added = RL._check_same_work_set(["a"], ["a", "x"])
    assert added and "появились" in added and "'x'" in added


def test_apply_blocks_when_composition_drops_a_work(tmp_path, monkeypatch):
    """КЛЮЧЕВАЯ защита. Если перепланирование уронит работу (как writer в ии-среде), apply отказывает
    и НИЧЕГО не пишет. Пара к test_apply_writes_artifact: без мутации те же данные -> applied."""
    child = _two_ready(tmp_path)
    orig = RL.understand

    def _drops_one(observed):
        intent = orig(observed)
        intent["reprioritization"] = intent["reprioritization"][1:]     # уронили одну готовую работу
        return intent

    monkeypatch.setattr(RL, "understand", _drops_one)
    res = RL.apply_reprioritization(child, now="2026-08-31T00:00:00")
    assert res["status"] == "blocked", res
    assert "состав" in res["reason"].lower()
    assert not (child / RL.LATEST_REL).exists()          # файл НЕ записан


def test_apply_writes_artifact_when_composition_is_honest(tmp_path):
    """Пара к предыдущему: без мутации те же данные -> applied и артефакт записан."""
    child = _two_ready(tmp_path)
    res = RL.apply_reprioritization(child, now="2026-08-31T00:00:00")
    assert res["status"] == "applied", res
    assert (child / RL.LATEST_REL).exists()


# ── write-scope: машинный артефакт, а не авторский план; предложения в артефакт не попадают ───────

def test_apply_never_touches_the_authored_plan(tmp_path):
    child = _two_ready(tmp_path)
    plan_path = child / "planning" / "plan.yaml"
    before = plan_path.read_bytes()
    RL.apply_reprioritization(child, now="2026-08-31T00:00:00")
    # Авторский план побайтно не тронут — кит переписывает НЕ его.
    assert plan_path.read_bytes() == before
    art = yaml.safe_load((child / RL.LATEST_REL).read_text(encoding="utf-8"))
    assert art["kind"] == "replan-reprioritization"
    assert art["actor"] == "replan-loop"
    assert "СОСТАВ РАБОТ НЕ ИЗМЕНЁН" in art["provenance"]
    # Структурные предложения в машинный артефакт НЕ попадают — только порядок.
    assert "proposals" not in art
    assert all(set(o.keys()) <= {"id", "rank", "score", "why"} for o in art["order"])


def test_dry_run_writes_nothing(tmp_path):
    child = _two_ready(tmp_path)
    res = RL.apply_reprioritization(child, dry_run=True, now="2026-08-31T00:00:00")
    assert res["status"] == "dry_run"
    assert res["order"]                                  # порядок посчитан
    assert not (child / RL.LATEST_REL).exists()          # но файл не записан


# ── fail-closed: kill-switch и честные UNKNOWN ───────────────────────────────────────────────────

def test_kill_switch_env_silences_write(tmp_path, monkeypatch):
    child = _two_ready(tmp_path)
    monkeypatch.setenv(RL.REPLAN_OFF_ENV, "off")
    res = RL.apply_reprioritization(child, now="2026-08-31T00:00:00")
    assert res["status"] == "disabled" and "off" in res["reason"]
    assert not (child / RL.LATEST_REL).exists()


def test_kill_switch_sentinel_file_silences_write(tmp_path):
    child = _two_ready(tmp_path)
    sentinel = child / RL.REPLAN_OFF_SENTINEL
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("off", encoding="utf-8")
    res = RL.apply_reprioritization(child, now="2026-08-31T00:00:00")
    assert res["status"] == "disabled"
    assert not (child / RL.LATEST_REL).exists()


def test_no_plan_is_named_not_silently_agreed(tmp_path):
    """Пустой каталог: «плана нет» — названный пробел, а НЕ «расхождений нет»."""
    rep = RL.replan_report(tmp_path, backlog=False)
    assert rep["plan_present"] is False
    assert rep["reprioritization"] == []
    assert rep["unverified"]                             # причина названа
    assert rep["complete"] is False


def test_backlog_unavailable_is_named(tmp_path):
    """Бэклог (GitHub Issues) недоступен в тесте -> честный UNKNOWN, не «дублей/сдвигов нет»."""
    rep = RL.replan_report(_two_ready(tmp_path), backlog=True)
    assert rep["backlog"]["ok"] is False
    assert any("бэклог" in u.lower() for u in rep["unverified"])
    assert rep["complete"] is False


def test_git_not_measured_without_repo_is_named(tmp_path):
    rep = RL.replan_report(_two_ready(tmp_path), backlog=False)
    assert any("git" in u.lower() for u in rep["unverified"])


# ── структурные предложения из ИЗМЕРЕННОГО расхождения (класс B/C, только с одобрения) ────────────

def test_git_disagreement_becomes_close_to_history_proposal():
    observed = {"actionable": [], "declared_order": [], "plan_drift": [],
                "git": {"measured": True,
                        "errors": ["work[w1]: статус 'todo', а коммиты ветки уже в 'main' — "
                                   "изменения работы в базе"]}}
    intent = RL.understand(observed)
    props = intent["proposals"]
    assert len(props) == 1
    assert props[0]["kind"] == "close-to-history"
    assert props[0]["class"] == "B"
    assert props[0]["requires_approval"] is True


def test_resolve_drift_becomes_reconcile_proposal():
    observed = {"actionable": [], "declared_order": [], "git": {"measured": True, "errors": []},
                "plan_drift": [{"id": "w2", "title": "t", "drift": "объявлено 'todo', по факту 'in_progress'"}]}
    intent = RL.understand(observed)
    props = intent["proposals"]
    assert any(p["kind"] == "reconcile-status" and p["target"] == "w2" for p in props)
    assert all(p["requires_approval"] for p in props)


# ── determinism: модель не зовётся, отчёт воспроизводим ──────────────────────────────────────────

def test_apply_declares_zero_model_calls(tmp_path):
    res = RL.apply_reprioritization(_two_ready(tmp_path), now="2026-08-31T00:00:00")
    assert res["budget"]["max_model_calls"] == 0


def test_report_is_deterministic(tmp_path):
    child = _two_ready(tmp_path)
    a = RL.replan_report(child, backlog=False)
    b = RL.replan_report(child, backlog=False)
    assert a == b
