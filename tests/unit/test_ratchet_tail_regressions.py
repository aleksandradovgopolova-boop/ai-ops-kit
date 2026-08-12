"""Регресс на два fail-open, закрытых хвостом ратчета (коммит 016dd9b, PR #78).

ЗАЧЕМ ЭТОТ ФАЙЛ. Хвостовой срез закрыл два настоящих дефекта — и приехал без единого теста
(11 файлов, все продакшн; в сообщении сказано «проверено пробой»). Проба глазами не остаётся в
репозитории: следующая правка вернёт fail-open молча, и ровно та ошибка, которую только что назвали
дорогой, повторится незамеченной. В репозитории, где каждая находка ревизии закрывалась
регресс-тестом, это единственный незакрытый случай — поэтому он закрывается здесь.

Оба дефекта — один класс: «не смог проверить» выдавалось за «проверено».
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import contours as _contours
from ai_ops_kit.planning import repo_audit

VALID_PLAN = """schema_version: 1
kind: delivery-plan
goals:
  - id: real-goal
    status: active
work:
  - id: w-01
    title: Настоящая работа
    type: engineering
    goal: real-goal
    status: todo
    owner_role: engineer
    write_scope: [src/]
"""


@pytest.fixture(scope="module")
def model():
    return _contours.load_model()


@pytest.fixture(scope="module")
def planning_contour(model):
    c = next((c for c in model["contours"] if c["id"] == "planning_execution"), None)
    assert c is not None, "контур planning_execution исчез из модели — тест потерял предмет"
    return c


def _state(root, contour, model):
    """Состояние контура planning_execution на подготовленном корне."""
    return repo_audit._contour_state(root, contour, {"tree_readable": True}, model)["state"]


def _with_plan(tmp_path, text):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(text, encoding="utf-8")
    return tmp_path


# ─── repo_audit: битый план больше не выдаётся за подтверждённый контур ──────────────────────────
@pytest.mark.unit
def test_valid_plan_verifies_the_contour(tmp_path, planning_contour, model):
    """positive: заполненный план закрывает контур — иначе следующий тест ничего не доказывает."""
    root = _with_plan(tmp_path, VALID_PLAN)
    assert _state(root, planning_contour, model) == repo_audit.VERIFIED


@pytest.mark.unit
def test_corrupt_plan_gives_unknown_not_verified(tmp_path, planning_contour, model):
    """fail-closed: НЕРАЗБИРАЕМЫЙ план -> UNKNOWN.

    Это и был дефект: `except: pass` оставлял состояние VERIFIED, то есть контур планирования
    объявлялся подтверждённым, хотя проверка не состоялась. Путь достижим по контракту —
    `delivery_plan.load()` на битом файле БРОСАЕТ `PlanCorrupt`.
    """
    root = _with_plan(tmp_path, "kind: delivery-plan\ngoals: [\n  - неразобранный YAML\n")
    state = _state(root, planning_contour, model)
    assert state == repo_audit.UNKNOWN, (
        f"битый план дал состояние {state!r}: «не смог проверить» снова выдано за «проверено»")


@pytest.mark.unit
def test_corrupt_plan_keeps_the_contour_out_of_ready(tmp_path, model):
    """Следствие, которое видит человек: контур НЕ попадает в `ready` отчёта аудита.

    Без этой проверки «UNKNOWN вместо VERIFIED» осталось бы косметикой — важно не название
    состояния, а то, что кит перестаёт называть контур готовым. Признак `closed` наружу не выходит, а
    вопросов у этого контура в модели нет вовсе, поэтому проверяется именно `ready` — то, что кит
    печатает владельцу.
    """
    good = repo_audit.audit(_with_plan(tmp_path / "good", VALID_PLAN), model=model)
    assert "planning_execution" in good["ready"], (
        f"заполненный план не дал готовности — тест потерял предмет: {good['by_state']}")

    broken = repo_audit.audit(_with_plan(tmp_path / "broken", "goals: [\n"), model=model)
    assert "planning_execution" not in broken["ready"], (
        "контур с НЕПРОВЕРЕННЫМ планом объявлен готовым — fail-open вернулся")


# ─── context_engine: причина берётся из исключения, а не выдумывается ────────────────────────────
def _child_repo(root):
    """Минимальный child с политиками доступа — как в селфтесте context_engine."""
    import yaml as _yaml

    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a * 0.9\n",
                                             encoding="utf-8")
    (root / "src" / "order.py").write_text("import pricing\n# fulfillment\n", encoding="utf-8")
    pol = root / ".ai" / "policies"
    pol.mkdir(parents=True, exist_ok=True)
    (pol / "access-filter.yaml").write_text(_yaml.safe_dump({
        "id": "T-AFP", "kind": "AccessFilterPolicy",
        "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}),
        encoding="utf-8")
    (pol / "data-classification.yaml").write_text(_yaml.safe_dump({
        "id": "T-DCP", "kind": "DataClassificationPolicy", "default_class": "internal",
        "rules": []}), encoding="utf-8")
    return root


@pytest.mark.unit
def test_graph_failure_is_named_not_reported_as_zero(monkeypatch, tmp_path):
    """`graph_added: 0` при СБОЕ обязан сопровождаться причиной.

    Ноль без причины неотличим от «граф построен, добавить было нечего» — тот же инвариант, что
    `unavailable != 0` в учёте стоимости и `unknown != not_changed` в контурах.
    """
    from ai_ops_kit.context import context_engine, repo_graph

    root = _child_repo(tmp_path)
    afp, dcp, _budget = context_engine.load_child_policies(root)
    monkeypatch.setattr(repo_graph, "build_graph",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("индекс графа битый")))

    view = context_engine.build_context(root, "discount", "executor", sha="abc123",
                                        afp=afp, dcp=dcp)
    used = view["sources_used"]
    assert used["graph_added"] == 0
    assert used.get("graph_reason"), "сбой графа снова неотличим от «добавить было нечего»"
    assert "RuntimeError" in used["graph_reason"], used["graph_reason"]


@pytest.mark.unit
def test_healthy_graph_reports_no_reason(tmp_path):
    """Обратная сторона: на исправном графе причины нет — иначе поле обесценится."""
    from ai_ops_kit.context import context_engine

    root = _child_repo(tmp_path)
    afp, dcp, _budget = context_engine.load_child_policies(root)
    view = context_engine.build_context(root, "discount", "executor", sha="abc123",
                                        afp=afp, dcp=dcp)
    assert view["sources_used"].get("graph_reason") is None, view["sources_used"]


@pytest.mark.unit
def test_semantic_reason_comes_from_the_exception(monkeypatch, tmp_path):
    """Причина отказа semantic-индекса берётся из исключения, а не выдумывается.

    Прежде на ЛЮБОЙ отказ дописывалось «нет подходящих файлов» — утверждение о причине, которой код
    не знает (мог быть отказ импорта, ввод-вывод, битый индекс). Строка уходит в отчёт
    (`sources_used.semantic_reason`), то есть человеку объясняли поведение придуманным поводом.
    """
    from ai_ops_kit.context import context_engine, semantic_lite

    root = _child_repo(tmp_path)
    afp, dcp, _budget = context_engine.load_child_policies(root)
    monkeypatch.setattr(semantic_lite, "build_index",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("индекс не читается")))

    # floor выше числа кандидатов -> semantic путь обязателен
    view = context_engine.build_context(root, "discount", "executor", sha="abc123",
                                        afp=afp, dcp=dcp, semantic_recall_floor=99)
    reason = view["sources_used"]["semantic_reason"]
    assert "OSError" in reason, f"причина не из исключения: {reason}"
    assert "индекс не читается" in reason, reason
