"""Отбор следующей работы: допуск, ранжирование, параллельность (v3.35).

`next work` — не верхняя карточка бэклога, и это должно быть ПРОВЕРЯЕМО:
  * positive     — READY считается по зависимостям, выбор объяснён словами, параллельность найдена;
  * fail-closed  — «готовой работы нет» отличается от «всё сделано»; недоказанная параллельность
                   не объявляется безопасной;
  * side-effect  — незакрытое решение человека и конфликт записи выбивают кандидата из READY
                   с ИМЕНОВАННОЙ причиной.
"""
from __future__ import annotations

import pathlib

import yaml

from ai_ops_kit.planning import next_work as N
from ai_ops_kit.planning import roadmap as R


def _repo(tmp_path, work, goals=None, roadmap_goals=("g1",)):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "delivery-plan",
         "goals": goals or [{"id": "g1", "status": "active", "outcome": {"works": False}}],
         "work": work}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lines = ["# ROADMAP", "", "## Сейчас", ""]
    lines += [f"- `{g}` — пользователь получает результат" for g in roadmap_goals]
    lines += ["", "## Следующий результат", "", "- `next-thing` — пользователь может большее", "",
              "## Дальше", "", "- крупная возможность", "", "## Later", "", "- идея — не сейчас"]
    (tmp_path / "ROADMAP.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _item(wid, **kw):
    base = {"id": wid, "title": f"работа {wid}", "type": "engineering", "goal": "g1",
            "status": "todo", "owner_role": "engineer", "depends_on": [],
            "write_scope": [f"src/{wid.lower()}/"]}
    base.update(kw)
    return base


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_next_best_is_the_unblocker_with_reason(tmp_path):
    """ARCH разблокирует троих — она и должна быть выбрана, и причина названа словами."""
    r = _repo(tmp_path, [
        _item("arch-01", type="architecture", owner_role="architect", value="high",
              write_scope=["context/system/"]),
        _item("eng-01", depends_on=["arch-01"]),
        _item("eng-02", depends_on=["arch-01"]),
        _item("eng-03", depends_on=["arch-01"]),
        _item("ui-01", type="visual", owner_role="frontend", write_scope=["src/ui/"]),
    ])
    rep = N.compute(r)
    assert rep["next_best"]["id"] == "arch-01"
    assert any("разблокирует 3" in w for w in rep["next_best"]["why"])
    assert rep["next_best"]["owner_role"] == "architect"


def test_parallel_set_is_independent_and_non_overlapping(tmp_path):
    r = _repo(tmp_path, [
        _item("arch-01", type="architecture", owner_role="architect", value="high",
              write_scope=["context/system/"]),
        _item("eng-01", depends_on=["arch-01"]),
        _item("ui-01", type="visual", owner_role="frontend", write_scope=["src/ui/"]),
    ])
    rep = N.compute(r)
    assert [p["id"] for p in rep["parallel_with"]] == ["ui-01"]
    assert rep["parallel_with"][0]["owner_role"] == "frontend"


def test_four_questions_are_all_answered(tmp_path):
    r = _repo(tmp_path, [_item("a"), _item("b", depends_on=["a"])])
    rep = N.compute(r)
    for key in ("where_are_we", "in_progress", "blocked", "next_best"):
        assert key in rep
    text = N.render(rep)
    for q in ("ГДЕ МЫ СЕЙЧАС", "ЧТО ДЕЛАЕМ ПРЯМО СЕЙЧАС", "ЧТО БЛОКИРУЕТ РАБОТУ",
              "ЧТО ВЗЯТЬ СЛЕДУЮЩИМ"):
        assert q in text


def test_goal_priority_beats_equal_leverage(tmp_path):
    """При равном плече выбирается работа цели ПЕРВОГО приоритета — порядок goals это приоритет."""
    r = _repo(tmp_path,
              [_item("b-01", goal="g2"), _item("a-01", goal="g1")],
              goals=[{"id": "g1", "status": "active"}, {"id": "g2", "status": "active"}],
              roadmap_goals=("g1", "g2"))
    rep = N.compute(r)
    assert rep["next_best"]["id"] == "a-01"


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_no_ready_work_is_not_all_done(tmp_path):
    r = _repo(tmp_path, [_item("a", human_decision="жду решения"),
                         _item("b", depends_on=["a"])])
    rep = N.compute(r)
    assert rep["next_best"] is None
    assert "НЕ значит «всё сделано»" in N.render(rep)


def test_missing_plan_reports_gap_not_success(tmp_path):
    rep = N.compute(tmp_path)
    assert rep["plan_present"] is False
    assert rep["gap"]
    assert "не заполнен" in N.render(rep)


def test_item_without_write_scope_not_declared_parallel_safe(tmp_path):
    """Недоказанная безопасность — не безопасность: без write_scope в параллель не берём."""
    r = _repo(tmp_path, [
        _item("arch-01", type="architecture", owner_role="architect", value="high",
              write_scope=["context/system/"]),
        _item("eng-01", depends_on=["arch-01"]),
        _item("rev-01", type="review", owner_role="reviewer", write_scope=[]),
    ])
    rep = N.compute(r)
    assert "rev-01" not in [p["id"] for p in rep["parallel_with"]]
    assert any(s["id"] == "rev-01" for s in rep["parallel_skipped"])


def test_parallel_candidate_is_compared_with_next_best_itself(tmp_path):
    """Находка ревью: набор параллельных работ сверялся только МЕЖДУ СОБОЙ — `chosen` стартовал
    пустым, а `next_best` в сравнение не попадал. Кит утверждал «области записи не пересекаются»
    про работу, чей write_scope лежит ВНУТРИ scope выбранной следующей: две сессии уходили писать
    один файл, ровно тот вред, ради которого правило непересечения и существует."""
    r = _repo(tmp_path, [
        _item("w1", value="high", write_scope=["src/api/orders/"]),
        _item("w2", value="low", write_scope=["src/api/orders/validation.py"]),
    ])
    rep = N.compute(r)
    assert rep["next_best"]["id"] == "w1"
    assert "W2" not in [p["id"] for p in rep["parallel_with"]]
    assert any(s["id"] == "w2" for s in rep["parallel_skipped"])


def test_template_example_is_not_reported_as_real_work(tmp_path):
    """НАХОДКА ТРЁХ РЕВЬЮ: установщик копировал `templates/planning/plan.yaml` дословно, и сразу
    после установки кит уверенно советовал «Спроектировать pipeline», рапортовал «работа 1/5» и
    получал `✓` в doctor — то есть выдавал СВОЙ пример за состояние чужого продукта. Ровно то, что
    модель запрещает: догадка не публикуется как факт.

    Заготовка обязана быть распознаваема как заготовка и НЕ считаться заполненным контуром.
    """
    import shutil
    (tmp_path / "planning").mkdir()
    shutil.copy(pathlib.Path("templates/planning/plan.yaml"),
                tmp_path / "planning" / "plan.yaml")
    shutil.copy(pathlib.Path("templates/planning/ROADMAP.md"), tmp_path / "ROADMAP.md")
    rep = N.compute(tmp_path)
    assert rep.get("plan_is_template"), "шаблон не распознан как шаблон"
    assert rep["next_best"] is None, "кит советует работу из своего примера как настоящую"
    out = N.render(rep)
    assert "пример" in out.lower() or "шаблон" in out.lower(), out
    assert "Спроектировать pipeline" not in out


def test_missing_roadmap_is_error_in_report(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "delivery-plan",
         "goals": [{"id": "g1"}], "work": [_item("a")]},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    rep = N.compute(tmp_path)
    assert rep["roadmap"]["errors"]


def test_budget_unknown_does_not_block(tmp_path):
    """Нет оценки -> `unknown`, и это НЕ ноль и не запрет (инвариант 3.21)."""
    r = _repo(tmp_path, [_item("a")])
    rep = N.compute(r, budget_left=1000)
    assert rep["next_best"]["id"] == "a"
    adm = {c["id"]: c for c in rep["next_best"]["admission"]}
    assert adm["within_budget"]["ok"] is True
    assert adm["within_budget"].get("state") == "unknown"


def test_budget_overrun_removes_from_ready_with_named_reason(tmp_path):
    r = _repo(tmp_path, [_item("a", estimate_tokens=500_000)])
    rep = N.compute(r, budget_left=1000)
    assert rep["next_best"] is None
    assert rep["not_ready"]
    assert "within_budget" in rep["not_ready"][0]["blocked_by_admission"]


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_human_decision_keeps_item_out_of_ready(tmp_path):
    r = _repo(tmp_path, [_item("a", human_decision="нужно решение владельца")])
    rep = N.compute(r)
    assert rep["next_best"] is None
    assert any("решение человека" in x for b in rep["blocked"] for x in b["reasons"])


def test_active_work_conflict_excludes_candidate(tmp_path):
    r = _repo(tmp_path, [_item("a", write_scope=["src/shared/"])])
    rt = r / ".ai" / "runtime"
    rt.mkdir(parents=True)
    (rt / "active-work.yaml").write_text(
        "schema_version: 1\nkind: active-work\nactive:\n"
        "  - id: s1\n    workitem: OTHER\n    branch: b\n    areas: [src/shared/]\n"
        "    session: s\n    status: in-progress\n", encoding="utf-8")
    rep = N.compute(r)
    assert rep["next_best"] is None
    assert any("пересекается" in x for b in rep["blocked"] for x in b["reasons"])


# ── контракт ROADMAP ──────────────────────────────────────────────────────────────────────────

def test_roadmap_requires_now_and_next_outcome(tmp_path):
    (tmp_path / "ROADMAP.md").write_text("# ROADMAP\n\n## Дальше\n\n- что-то\n", encoding="utf-8")
    rep = R.check(tmp_path)
    assert any("сейчас" in e.lower() for e in rep["errors"])


def test_roadmap_flags_task_looking_item(tmp_path):
    (tmp_path / "ROADMAP.md").write_text(
        "# ROADMAP\n\n## Сейчас\n\n- сделать API для дашбордов\n\n"
        "## Следующий результат\n\n- `g1` — пользователь получает результат\n", encoding="utf-8")
    rep = R.check(tmp_path)
    assert any("ЗАДАЧУ" in w for w in rep["warnings"])


def test_roadmap_goal_without_work_is_warning(tmp_path):
    r = _repo(tmp_path, [_item("a")], roadmap_goals=("g1", "orphan-goal"))
    rep = N.compute(r)
    assert any("orphan-goal" in w for w in rep["roadmap"]["warnings"])


def test_work_goal_absent_from_roadmap_is_warning(tmp_path):
    r = _repo(tmp_path, [_item("a", goal="g9")],
              goals=[{"id": "g9", "status": "active"}], roadmap_goals=("g1",))
    rep = N.compute(r)
    assert any("работа без направления" in w for w in rep["roadmap"]["warnings"])
