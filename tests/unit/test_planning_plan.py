"""Delivery plan: разбор, семантика, вывод статуса (v3.35 Product Operating Model).

Три теста на capability — positive, fail-closed, side-effect proof:
  * positive     — валидный план разбирается, статусы выводятся из графа;
  * fail-closed  — битый/пустой/циклический план НЕ выглядит как «работы нет»;
  * side-effect  — факт из WorkItem и реестра активных работ ПЕРЕБИВАЕТ объявленный статус.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import delivery_plan as P

MODEL = C.load_model()


def _write(root: Path, work, goals=None):
    data = {"schema_version": 1, "kind": "delivery-plan",
            "goals": goals or [{"id": "g1", "status": "active",
                                "outcome": {"user_can_do_it": False}}],
            "work": work}
    (root / "planning").mkdir(parents=True, exist_ok=True)
    (root / "planning" / "plan.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def _item(wid, **kw):
    base = {"id": wid, "title": f"работа {wid}", "type": "engineering", "goal": "g1",
            "status": "todo", "owner_role": "engineer", "depends_on": [],
            "write_scope": [f"src/{wid.lower()}/"]}
    base.update(kw)
    return base


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_valid_plan_parses_and_derives_status(tmp_path):
    _write(tmp_path, [_item("a", type="architecture", owner_role="architect"),
                      _item("b", depends_on=["a"])])
    pl = P.load(tmp_path)
    rep = P.validate(pl, MODEL)
    assert rep["errors"] == [], rep["errors"]
    res = P.resolve(pl, tmp_path, MODEL)
    assert res["a"]["status"] == "ready"
    assert res["b"]["status"] == "blocked"
    assert "a" in res["b"]["blocked_by"]
    # Причина названа словами, а не подразумевается: пустой список причин = молчаливый вывод.
    assert res["b"]["reasons"]


def test_derived_status_is_order_independent(tmp_path):
    """Перестановка строк в файле не меняет ответ: обход топологический, а не по порядку строк."""
    forward = [_item("a"), _item("b", depends_on=["a"]), _item("c", depends_on=["b"])]
    _write(tmp_path, forward)
    a = {k: v["status"] for k, v in P.resolve(P.load(tmp_path), tmp_path, MODEL).items()}
    _write(tmp_path, list(reversed(forward)))
    b = {k: v["status"] for k, v in P.resolve(P.load(tmp_path), tmp_path, MODEL).items()}
    assert a == b


def test_unblocks_counts_transitive_downstream(tmp_path):
    _write(tmp_path, [_item("a"), _item("b", depends_on=["a"]), _item("c", depends_on=["b"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["unblocks"] == 2      # B и C, а не только прямой потомок
    assert res["c"]["unblocks"] == 0


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_missing_plan_is_none_not_empty(tmp_path):
    """Отсутствие плана и пустой план — РАЗНЫЕ ответы; None означает «контур не заполнен»."""
    assert P.load(tmp_path) is None


def test_empty_file_raises_not_returns_empty(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text("", encoding="utf-8")
    with pytest.raises(P.PlanCorrupt):
        P.load(tmp_path)


def test_broken_yaml_raises(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text("work: [\n  - id: A\n   bad", encoding="utf-8")
    with pytest.raises(P.PlanCorrupt):
        P.load(tmp_path)


def test_cycle_is_error_not_warning(tmp_path):
    _write(tmp_path, [_item("a", depends_on=["b"]), _item("b", depends_on=["a"])])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("цикл" in x.lower() for x in rep["errors"])


def test_cycle_does_not_hang_resolve(tmp_path):
    """Цикл — ошибка валидатора, но resolve обязан завершиться и не молчать об этих элементах."""
    _write(tmp_path, [_item("a", depends_on=["b"]), _item("b", depends_on=["a"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert set(res) == {"a", "b"}


def test_unknown_dependency_blocks(tmp_path):
    """Зависимость вне плана НЕ считается закрытой: неизвестное не зелёное."""
    _write(tmp_path, [_item("a", depends_on=["nope"])])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["status"] == "blocked"
    assert "nope" in res["a"]["blocked_by"]


def test_plan_id_must_be_usable_by_the_engine(tmp_path):
    """Находка ревью: валидатор плана допускал `ARCH-01`, а движок требует slug нижнего регистра и
    падал сырым ValueError на `ai-ops run --feature ARCH-01`. Расхождение двух правил об одном id
    делало объявленный приоритет «факт из WorkItem > объявление человека» недостижимым для id из
    собственного шаблона кита."""
    _write(tmp_path, [_item("ARCH-01")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("нижн" in x.lower() or "slug" in x.lower() for x in rep["errors"]), rep["errors"]

    # Годный id проходит.
    _write(tmp_path, [_item("arch-01")])
    assert P.validate(P.load(tmp_path), MODEL)["errors"] == []


def test_vendor_field_is_rejected(tmp_path):
    """План называет РОЛЬ. Поле исполнителя привязало бы план продукта к вендору."""
    _write(tmp_path, [_item("a", runtime="claude-code")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("runtime" in x for x in rep["errors"])


def test_declared_derived_status_is_flagged(tmp_path):
    """`ready` в файле — расхождение: этот статус обязан считать граф."""
    _write(tmp_path, [_item("a", status="ready")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("ВЫВОДИМЫЙ" in x for x in rep["warnings"])


def test_unknown_role_and_type_are_errors(tmp_path):
    _write(tmp_path, [_item("a", owner_role="wizard", type="magic")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("owner_role" in x for x in rep["errors"])
    assert any("type" in x for x in rep["errors"])


def test_goal_must_resolve(tmp_path):
    _write(tmp_path, [_item("a", goal="nope")])
    rep = P.validate(P.load(tmp_path), MODEL)
    assert any("goal" in x for x in rep["errors"])


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def _write_workitem(root: Path, wid: str, status: str) -> Path:
    """WorkItem по тому же пути, по которому его ЧИТАЕТ продакшн-код: `features/<id>/workitem.yaml`.

    ТЕСТ БЫЛ ЗЕЛЁНЫМ ОТ СВОЙСТВА МАШИНЫ. Фикстура писала `features/A/` для элемента плана `a`:
    на macOS файловая система регистронезависимая, и `features/a/workitem.yaml` находил файл в
    `features/A/`; на Linux (CI) — нет, и `python39-compat` с `quality (fast)` падали. Локальный
    охват `full-current-python` этого увидеть НЕ МОГ по определению — ровно тот случай, ради
    которого объявлены два охвата доказательства.

    Каталог собирается из ТОГО ЖЕ `wid`, что и элемент плана, а не из литерала: это единственное,
    что мешает опечатке снова стать зелёной на одной ОС и красной на другой.
    """
    import os
    d = root / "features" / wid
    d.mkdir(parents=True, exist_ok=True)
    (d / "workitem.yaml").write_text(f"id: {wid}\nstatus: {status}\n", encoding="utf-8")
    # ПРОВЕРКА РЕГИСТРА — НА ЛЮБОЙ ОС. `is_file()` на macOS вернёт True и для `features/A/`, поэтому
    # спрашиваем у ОС ИМЕНА: так расхождение регистра краснеет там, где его написали, а не через
    # десять минут в CI на другой файловой системе.
    names = os.listdir(root / "features")
    assert wid in names, f"каталог работы создан под другим именем: {names} (ожидалось '{wid}')"
    return d / "workitem.yaml"


def test_workitem_fact_overrides_declared_status(tmp_path):
    """WorkItem закрыт гейтами -> элемент плана done, даже если в файле стоит todo."""
    wid = "a"
    _write(tmp_path, [_item(wid)])
    _write_workitem(tmp_path, wid, "done")
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["status"] == "done"
    assert res["a"]["source"] == "workitem"
    assert res["a"]["drift"]                       # расхождение с объявленным ВИДНО, а не скрыто


def _register_real(tmp_path, wid, areas):
    """Регистрация активной работы ЧЕРЕЗ САМ ДВИЖОК, а не рукописным YAML.

    Ревью нашло, что прежние фикстуры выдумывали форму: писали `areas:` и `workitem: A`, тогда как
    `active_work.register` пишет `affected_areas:` и `workitem: features/<id>/workitem.yaml`
    (ПУТЬ, не id). Тесты были зелёными на форме, которой движок не производит, — то есть проверяли
    моё представление, а не реальность. Единственная защита от повторения: фикстура обязана
    вызывать продакшн-запись, а не имитировать её.
    """
    from ai_ops_kit.lifecycle import active_work
    rt = tmp_path / ".ai" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    aw = rt / "active-work.yaml"
    rc = active_work.register(aw, wid, f"ai-ops/{wid}", list(areas), "sess-1",
                              workitem=f"features/{wid}/workitem.yaml")
    assert rc == 0, "регистрация активной работы не удалась"
    return aw


def test_active_work_makes_item_in_progress(tmp_path):
    """Форма записи — та, что производит движок (см. _register_real)."""
    _write(tmp_path, [_item("a")])
    _register_real(tmp_path, "a", ["src/a/"])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["status"] == "in_progress"
    assert res["a"]["source"] == "active-work"


def test_write_scope_conflict_with_active_work_blocks(tmp_path):
    """Пересечение области записи с активной работой блокирует — иначе две сессии рвут одно место.

    Форма записи — реальная (`affected_areas`, `workitem` путём). На рукописной форме этот тест был
    зелёным при полностью нерабочей проверке конфликта.
    """
    _write(tmp_path, [_item("a", write_scope=["src/shared/"])])
    _register_real(tmp_path, "other-work", ["src/shared/models/"])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["status"] == "blocked"
    assert res["a"]["conflicts_with"] == ["other-work"]


def test_path_shape_variants_still_conflict(tmp_path):
    """Находка ревью: сравнение областей записи строковое, без нормализации — `./src/`, `src/` и
    `src\\` считались непересекающимися, и три сессии уходили писать один каталог."""
    _write(tmp_path, [_item("a", write_scope=["./src/"])])
    _register_real(tmp_path, "other-work", ["src"])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["conflicts_with"] == ["other-work"], "./src/ и src — один каталог"


def test_global_write_scope_conflicts_with_everything(tmp_path):
    """Находка ревью: `write_scope: ["**"]` давал «пересечений нет» — потерян fail-closed, который
    в `engine/parallel_planner.py` уже починен как баг v3.6.5. Работа, пишущая всюду, конфликтует
    со всем: недоказанная безопасность не есть безопасность."""
    _write(tmp_path, [_item("a", write_scope=["**"])])
    _register_real(tmp_path, "other-work", ["src/api/"])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["a"]["conflicts_with"] == ["other-work"]


def test_human_decision_blocks_even_with_deps_done(tmp_path):
    _write(tmp_path, [_item("a", status="done"),
                      _item("b", depends_on=["a"], human_decision="нужно решение владельца")])
    res = P.resolve(P.load(tmp_path), tmp_path, MODEL)
    assert res["b"]["status"] == "blocked"
    assert any("решение человека" in r for r in res["b"]["reasons"])
